"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

from __future__ import annotations

import logging
import random
import re
import socket
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("sip_trunk_failover")


class TrunkStatus(str, Enum):
    HEALTHY = "HEALTHY"          # Sağlıklı (OPTIONS yanıtı alındı, RTT kabul edilebilir)
    DEGRADED = "DEGRADED"        # Yüksek gecikme veya kısmi paket kaybı (> 150 ms)
    DOWN = "DOWN"                # Hat çöktü / Yanıt yok / 503 Service Unavailable
    MAINTENANCE = "MAINTENANCE"  # Manuel bakım / Boşaltma (Draining) modu


@dataclass
class SIPTrunk:
    trunk_id: str
    name: str
    host: str
    port: int = 5060
    transport: str = "UDP"
    priority: int = 1               # 1: Ana Operatörler, 2: Yedek / Felaket Kurtarma
    weight: int = 50                # Ağırlıklı Round-Robin ağırlığı (örn. 60, 30, 10)
    max_channels: int = 30          # Eşzamanlı kanal sınırı
    status: TrunkStatus = TrunkStatus.HEALTHY
    rtt_ms: float = 25.0
    rtt_ema_ms: float = 25.0
    consecutive_failures: int = 0
    active_calls: int = 0
    total_calls_routed: int = 0
    total_failovers_triggered: int = 0
    last_checked_at: str = ""
    last_healthy_at: str = ""
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class TrunkSelectionResult:
    trunk_id: str
    trunk_name: str
    host: str
    port: int
    dial_channel: str               # Örn: PJSIP/05321234567@turk_telekom_trunk
    priority: int
    is_failover: bool
    failover_reason: str
    active_calls: int
    available_channels: int
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PingResult:
    trunk_id: str
    success: bool
    rtt_ms: float
    status_code: int
    status_message: str
    checked_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_sip_options_packet(
    trunk: SIPTrunk,
    local_ip: str = "127.0.0.1",
    local_port: int = 5060,
    call_id: Optional[str] = None,
) -> bytes:
    """RFC 3261 uyumlu SIP OPTIONS yoklama (ping) paketi üretir."""
    c_id = call_id or f"{uuid.uuid4().hex}@{local_ip}"
    tag = uuid.uuid4().hex[:8]
    branch = f"z9hG4bK.{uuid.uuid4().hex[:12]}"

    sip_msg = (
        f"OPTIONS sip:{trunk.host}:{trunk.port} SIP/2.0\r\n"
        f"Via: SIP/2.0/{trunk.transport.upper()} {local_ip}:{local_port};branch={branch};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <sip:freya-monitor@{local_ip}>;tag={tag}\r\n"
        f"To: <sip:{trunk.host}:{trunk.port}>\r\n"
        f"Call-ID: {c_id}\r\n"
        f"CSeq: 1 OPTIONS\r\n"
        f"User-Agent: FreyaTTS-Automotive/1.0\r\n"
        f"Accept: application/sdp\r\n"
        f"Content-Length: 0\r\n\r\n"
    )
    return sip_msg.encode("utf-8")


def parse_sip_response(data: bytes) -> Tuple[int, str]:
    """Gelen SIP yanıtından durum kodunu ve mesajını ayıklar (örn. 200 OK)."""
    text = data.decode("utf-8", errors="ignore")
    lines = text.split("\r\n")
    if lines:
        status_line = lines[0]
        # Örn: SIP/2.0 200 OK
        match = re.search(r"SIP/2\.0\s+(\d{3})\s*(.*)", status_line)
        if match:
            code = int(match.group(1))
            msg = match.group(2).strip()
            return code, msg
    return 0, "Unknown Response"


class SIPTrunkFailoverManager:
    """
    Çoklu SIP Trunk Sağlık Kontrolü, Ağırlıklı Round-Robin (WRR) ve
    100 ms Altında Otomatik Yük Devretme (Sub-second Failover) Yöneticisi.
    """

    def __init__(
        self,
        *,
        degraded_rtt_threshold_ms: float = 150.0,
        down_rtt_threshold_ms: float = 500.0,
        failure_threshold: int = 2,
        recovery_success_target: int = 2,
        rtt_ema_alpha: float = 0.3,
    ):
        self.degraded_rtt_threshold_ms = degraded_rtt_threshold_ms
        self.down_rtt_threshold_ms = down_rtt_threshold_ms
        self.failure_threshold = failure_threshold
        self.recovery_success_target = recovery_success_target
        self.rtt_ema_alpha = rtt_ema_alpha

        self._lock = threading.Lock()
        self._trunks: Dict[str, SIPTrunk] = {}
        self._consecutive_successes: Dict[str, int] = {}
        self._simulated_down_trunks: set[str] = set()

        # Özel yoklama simülatörü (Test ortamı için)
        self.mock_probe_func: Optional[Callable[[SIPTrunk], Tuple[bool, float, int, str]]] = None

        # Varsayılan Türkiye Kurumsal Telekomünikasyon Trunkları
        self._load_default_trunks()

    def _load_default_trunks(self) -> None:
        """Varsayılan 3 kurumsal SIP trunk hattını yükler."""
        defaults = [
            SIPTrunk(
                trunk_id="turk_telekom_trunk",
                name="Türk Telekom Kurumsal SIP Trunk",
                host="sip.turktelekom.com.tr",
                port=5060,
                priority=1,
                weight=60,
                max_channels=30,
                rtt_ms=22.0,
                rtt_ema_ms=22.0,
                last_healthy_at=datetime.now(timezone.utc).isoformat(),
            ),
            SIPTrunk(
                trunk_id="turkcell_superonline_trunk",
                name="Turkcell Superonline SIP Trunk",
                host="sip.superonline.net",
                port=5060,
                priority=1,
                weight=30,
                max_channels=30,
                rtt_ms=18.0,
                rtt_ema_ms=18.0,
                last_healthy_at=datetime.now(timezone.utc).isoformat(),
            ),
            SIPTrunk(
                trunk_id="vodafone_net_trunk",
                name="Vodafone Net Yedek / Felaket Kurtarma Trunk",
                host="sip.vodafone.com.tr",
                port=5060,
                priority=2,  # İkincil öncelik (Yedek)
                weight=10,
                max_channels=20,
                rtt_ms=32.0,
                rtt_ema_ms=32.0,
                last_healthy_at=datetime.now(timezone.utc).isoformat(),
            ),
        ]
        for t in defaults:
            self._trunks[t.trunk_id] = t
            self._consecutive_successes[t.trunk_id] = 0

    def add_or_update_trunk(self, trunk: SIPTrunk) -> None:
        """Yeni bir SIP trunk ekler veya mevcut trunk'ı günceller."""
        with self._lock:
            self._trunks[trunk.trunk_id] = trunk
            if trunk.trunk_id not in self._consecutive_successes:
                self._consecutive_successes[trunk.trunk_id] = 0

    def get_trunk(self, trunk_id: str) -> Optional[SIPTrunk]:
        """Belirtilen trunk nesnesini döndürür."""
        with self._lock:
            return self._trunks.get(trunk_id)

    def list_trunks(self) -> List[Dict[str, Any]]:
        """Tüm SIP trunk hatlarını durum ve telemetri bilgileriyle listeler."""
        with self._lock:
            return [t.to_dict() for t in self._trunks.values()]

    def ping_trunk(self, trunk_id: str, timeout_sec: float = 1.0) -> PingResult:
        """
        Belirtilen trunk'a SIP OPTIONS pingi gönderir ve RTT süresini ölçer.
        Durum geçişlerini (HEALTHY, DEGRADED, DOWN) günceller.
        """
        with self._lock:
            trunk = self._trunks.get(trunk_id)
            if not trunk:
                raise ValueError(f"Bilinmeyen SIP Trunk: {trunk_id}")

        now_iso = datetime.now(timezone.utc).isoformat()

        # Simülasyon modunda mı?
        if trunk_id in self._simulated_down_trunks:
            success = False
            rtt_ms = 999.0
            status_code = 503
            status_msg = "Simulated Network Failure (No SIP Response)"
        elif self.mock_probe_func is not None:
            success, rtt_ms, status_code, status_msg = self.mock_probe_func(trunk)
        else:
            success, rtt_ms, status_code, status_msg = self._send_udp_options_probe(trunk, timeout_sec)

        # Durum makinesini güncelle
        with self._lock:
            trunk.last_checked_at = now_iso
            trunk.rtt_ms = round(rtt_ms, 2)

            if success:
                # EMA güncelle
                trunk.rtt_ema_ms = round(
                    (self.rtt_ema_alpha * rtt_ms) + ((1.0 - self.rtt_ema_alpha) * trunk.rtt_ema_ms),
                    2,
                )
                trunk.consecutive_failures = 0
                trunk.last_healthy_at = now_iso
                trunk.last_error = ""

                self._consecutive_successes[trunk_id] = self._consecutive_successes.get(trunk_id, 0) + 1

                # DEGRADED veya HEALTHY kontrolü
                if trunk.status != TrunkStatus.MAINTENANCE:
                    if (
                        trunk.rtt_ema_ms >= self.degraded_rtt_threshold_ms
                        or trunk.rtt_ms >= self.degraded_rtt_threshold_ms
                    ):
                        trunk.status = TrunkStatus.DEGRADED
                    elif self._consecutive_successes[trunk_id] >= self.recovery_success_target:
                        trunk.status = TrunkStatus.HEALTHY

            else:
                trunk.consecutive_failures += 1
                self._consecutive_successes[trunk_id] = 0
                trunk.last_error = f"{status_code} {status_msg}"

                if trunk.status != TrunkStatus.MAINTENANCE:
                    if trunk.consecutive_failures >= self.failure_threshold:
                        if trunk.status != TrunkStatus.DOWN:
                            logger.warning(
                                "SIP Trunk ÇÖKTÜ (DOWN)! Trunk: %s (%s) | Hata: %s",
                                trunk_id,
                                trunk.name,
                                trunk.last_error,
                            )
                        trunk.status = TrunkStatus.DOWN
                    else:
                        trunk.status = TrunkStatus.DEGRADED

        return PingResult(
            trunk_id=trunk_id,
            success=success,
            rtt_ms=round(rtt_ms, 2),
            status_code=status_code,
            status_message=status_msg,
            checked_at=now_iso,
        )

    def ping_all_trunks(self, timeout_sec: float = 1.0) -> List[PingResult]:
        """Tüm kayıtlı trunk hatlarını yoklar."""
        with self._lock:
            trunk_ids = list(self._trunks.keys())
        results = []
        for t_id in trunk_ids:
            res = self.ping_trunk(t_id, timeout_sec=timeout_sec)
            results.append(res)
        return results

    def _send_udp_options_probe(
        self,
        trunk: SIPTrunk,
        timeout_sec: float = 1.0,
    ) -> Tuple[bool, float, int, str]:
        """Fiziksel UDP soketi üzerinden SIP OPTIONS paketi gönderip yanıt bekler."""
        packet = build_sip_options_packet(trunk)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout_sec)

        t_start = time.monotonic()
        try:
            sock.sendto(packet, (trunk.host, trunk.port))
            data, _ = sock.recvfrom(4096)
            t_end = time.monotonic()
            rtt_ms = (t_end - t_start) * 1000.0

            code, msg = parse_sip_response(data)
            # SIP 200, 401 (Unauthorized - sunucu ayakta ama auth istiyor), 404, 405 hepsi canlilik gostergesidir
            if 200 <= code < 500:
                return True, rtt_ms, code, msg
            else:
                return False, rtt_ms, code, msg

        except socket.timeout:
            return False, timeout_sec * 1000.0, 408, "Request Timeout"
        except Exception as e:
            return False, 999.0, 503, str(e)
        finally:
            sock.close()

    def select_best_trunk(
        self,
        destination_phone: str = "",
        force_priority: Optional[int] = None,
        exclude_trunk_ids: Optional[List[str]] = None,
    ) -> TrunkSelectionResult:
        """
        Giden bir arama için en uygun SIP trunk'ı seçer (< 100 ms karar süresi).
        Ağırlıklı Round-Robin (WRR) ve Öncelik tabanlı Failover uygular.
        """
        exclude_set = set(exclude_trunk_ids or [])
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            # 1. Kullanılabilir trunkları filtrele
            candidate_trunks: List[SIPTrunk] = []
            for t in self._trunks.values():
                if t.trunk_id in exclude_set:
                    continue
                if t.status in (TrunkStatus.DOWN, TrunkStatus.MAINTENANCE):
                    continue
                if t.active_calls >= t.max_channels:
                    continue
                candidate_trunks.append(t)

            # Aday trunk bulunamadıysa (Felaket durumu)
            if not candidate_trunks:
                # Son çare: Down olsa bile en yüksek öncelikli trunk'a yönlendir
                fallback_trunks = [
                    t for t in self._trunks.values()
                    if t.trunk_id not in exclude_set and t.status != TrunkStatus.MAINTENANCE
                ]
                if fallback_trunks:
                    chosen = min(fallback_trunks, key=lambda x: x.priority)
                    return TrunkSelectionResult(
                        trunk_id=chosen.trunk_id,
                        trunk_name=chosen.name,
                        host=chosen.host,
                        port=chosen.port,
                        dial_channel=f"PJSIP/{destination_phone}@{chosen.trunk_id}",
                        priority=chosen.priority,
                        is_failover=True,
                        failover_reason="Tüm birincil ve ikincil trunklar arızalı! Son çare denemesi.",
                        active_calls=chosen.active_calls,
                        available_channels=max(0, chosen.max_channels - chosen.active_calls),
                        timestamp=now_iso,
                    )
                else:
                    raise RuntimeError("Hiçbir SIP Trunk hattı mevcut veya kullanılabilir değil!")

            # 2. Öncelik Seviyesine Göre Grupla (En düşük sayı = En yüksek öncelik)
            min_priority = (
                force_priority
                if force_priority is not None
                else min(t.priority for t in candidate_trunks)
            )
            priority_candidates = [t for t in candidate_trunks if t.priority == min_priority]

            if not priority_candidates:
                # Talep edilen öncelikte trunk yoksa mevcut en iyi önceliğe geç (Failover)
                min_priority = min(t.priority for t in candidate_trunks)
                priority_candidates = [t for t in candidate_trunks if t.priority == min_priority]

            # 3. Ağırlıklı Round-Robin (Weighted Round-Robin) Seçimi
            # Ağırlık ve boş kanal kapasitesi oranında seçim
            weights = [max(1, t.weight) for t in priority_candidates]
            chosen_trunk = random.choices(priority_candidates, weights=weights, k=1)[0]

            is_failover = (chosen_trunk.priority > 1) or bool(exclude_set)
            failover_reason = (
                f"Birincil hatlar arızalı/dolu olduğu için {chosen_trunk.priority}. öncelikli yedek hatta geçildi."
                if is_failover
                else ""
            )

            # İstatistikleri artır
            chosen_trunk.total_calls_routed += 1
            if is_failover:
                chosen_trunk.total_failovers_triggered += 1

            dial_str = destination_phone or "SAMPLE_DEST"
            dial_channel = f"PJSIP/{dial_str}@{chosen_trunk.trunk_id}"

            return TrunkSelectionResult(
                trunk_id=chosen_trunk.trunk_id,
                trunk_name=chosen_trunk.name,
                host=chosen_trunk.host,
                port=chosen_trunk.port,
                dial_channel=dial_channel,
                priority=chosen_trunk.priority,
                is_failover=is_failover,
                failover_reason=failover_reason,
                active_calls=chosen_trunk.active_calls,
                available_channels=max(0, chosen_trunk.max_channels - chosen_trunk.active_calls),
                timestamp=now_iso,
            )

    def failover_reroute(
        self,
        failed_trunk_id: str,
        destination_phone: str = "",
        error_reason: str = "Congestion / Channel Unavailable",
    ) -> TrunkSelectionResult:
        """
        Çağrı başlatma sırasında (AMI Originate) hata alındığında 100 ms içinde
        alternatif SIP trunk'a yönlendirme (Sub-second Failover) yapar.
        """
        with self._lock:
            failed_trunk = self._trunks.get(failed_trunk_id)
            if failed_trunk:
                failed_trunk.consecutive_failures += 1
                failed_trunk.last_error = error_reason
                failed_trunk.total_failovers_triggered += 1
                if failed_trunk.consecutive_failures >= self.failure_threshold:
                    failed_trunk.status = TrunkStatus.DOWN

        logger.warning(
            "SIP Trunk Hatası! Sub-second Failover tetikleniyor: %s (Hata: %s)",
            failed_trunk_id,
            error_reason,
        )

        return self.select_best_trunk(
            destination_phone=destination_phone,
            exclude_trunk_ids=[failed_trunk_id],
        )

    def increment_active_call(self, trunk_id: str) -> None:
        """Trunk üzerindeki aktif çağrı sayısını 1 artırır."""
        with self._lock:
            t = self._trunks.get(trunk_id)
            if t:
                t.active_calls = min(t.max_channels, t.active_calls + 1)

    def decrement_active_call(self, trunk_id: str) -> None:
        """Trunk üzerindeki aktif çağrı sayısını 1 azaltır."""
        with self._lock:
            t = self._trunks.get(trunk_id)
            if t:
                t.active_calls = max(0, t.active_calls - 1)

    def set_trunk_maintenance(self, trunk_id: str, maintenance: bool = True) -> None:
        """Trunk'ı bakım/boşaltma moduna alır veya moddan çıkarır."""
        with self._lock:
            t = self._trunks.get(trunk_id)
            if t:
                t.status = TrunkStatus.MAINTENANCE if maintenance else TrunkStatus.HEALTHY

    def simulate_trunk_outage(self, trunk_id: str, outage: bool = True) -> None:
        """Test amaçlı olarak trunk arızasını simüle eder."""
        with self._lock:
            if outage:
                self._simulated_down_trunks.add(trunk_id)
                t = self._trunks.get(trunk_id)
                if t:
                    t.status = TrunkStatus.DOWN
                    t.last_error = "Simulated Telecom Fiber Outage"
            else:
                self._simulated_down_trunks.discard(trunk_id)
                t = self._trunks.get(trunk_id)
                if t:
                    t.status = TrunkStatus.HEALTHY
                    t.consecutive_failures = 0
                    t.last_error = ""


# Global Singleton Instance
sip_trunk_failover_manager = SIPTrunkFailoverManager()
