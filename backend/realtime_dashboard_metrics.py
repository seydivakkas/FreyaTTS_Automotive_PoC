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

import collections
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from backend.audio_archive_compliance import audio_archive_engine
from backend.gpu_health_circuit_breaker import CircuitState, gpu_health_circuit_breaker
from backend.pause_breath_cleaner import telephony_audio_cache
from backend.sip_trunk_failover import TrunkStatus, sip_trunk_failover_manager

logger = logging.getLogger("realtime_dashboard_metrics")


class SLAComplianceLevel(str, Enum):
    HEALTHY = "HEALTHY"      # Tüm SLA eşikleri karşılanıyor (%100 uyum)
    WARNING = "WARNING"      # 1-2 metrik uyarı sınırında
    BREACHED = "BREACHED"    # En az bir kritik SLA eşiği aşıldı
    NO_DATA = "veri yok"     # Hiçbir metrik ölçülmedi: uyumlu DEĞİL, bilinmiyor


# Ölçümü olmayan SLA kontrolünün durumu ("geçti" sayılmaz)
NO_DATA_STATUS = "veri yok"


@dataclass
class SLAConfig:
    max_p95_latency_ms: float = 250.0        # P95 inferans gecikmesi < 250 ms
    min_call_answer_rate_pct: float = 98.0   # Çağrı tamamlama / yanıtlama oranı > %98
    min_mos_score: float = 4.1               # Ses kalitesi MOS skoru > 4.1
    max_packet_loss_pct: float = 1.0         # Asterisk AudioSocket paket kaybı < %1.0
    max_gpu_vram_pct: float = 90.0           # GPU VRAM doluluğu < %90
    max_gpu_temp_c: float = 82.0             # GPU çekirdek sıcaklığı < 82°C
    max_queue_wait_sec: float = 30.0         # Maksimum bekleme süresi < 30 sn


@dataclass
class SLACheckItem:
    metric_name: str
    description: str
    target: str
    actual_value: Optional[float]   # None = ölçülmedi
    unit: str
    status: str              # "PASS", "WARN", "FAIL" veya "veri yok"
    is_breached: bool


@dataclass
class SLAReport:
    overall_status: str
    compliance_score_pct: Optional[float]   # None = hiç ölçüm yok
    evaluated_at: str
    total_checks: int
    passed_checks: int
    breached_checks: int
    checks: List[SLACheckItem]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "compliance_score_pct": self.compliance_score_pct,
            "evaluated_at": self.evaluated_at,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "breached_checks": self.breached_checks,
            "checks": [asdict(c) for c in self.checks],
        }


def calculate_itu_mos(
    rtt_ms: float = 25.0,
    jitter_ms: float = 2.0,
    packet_loss_pct: float = 0.0,
) -> float:
    """
    ITU-T G.107 E-Model standardına dayalı tahmini Mean Opinion Score (MOS) hesaplar.
    Mükemmel ses kalitesi: 4.3 - 4.5
    Kabul edilebilir telefon kalitesi: 4.0 - 4.2
    Bozulmuş ses kalitesi: < 3.8
    """
    # Baz R faktörü (G.711 / PCM / Opus)
    r = 94.0

    # Gecikme cezası (Id)
    one_way_delay = (rtt_ms / 2.0) + (jitter_ms * 2.0)
    if one_way_delay > 100.0:
        r -= 0.024 * one_way_delay + 0.11 * max(0.0, one_way_delay - 177.3)
    else:
        r -= 0.024 * one_way_delay

    # Paket kaybı cezası (Ie)
    # %1 paket kaybı ~ 5 R puanı düşürür
    r -= packet_loss_pct * 7.5

    # R-faktörünü 0 - 100 arasına sınırla
    r = max(0.0, min(100.0, r))

    # R faktöründen MOS dönüşümü (ITU-T G.107 formülü)
    if r < 0:
        mos = 1.0
    elif r > 100:
        mos = 4.5
    else:
        mos = 1.0 + (0.035 * r) + (r * (r - 60.0) * (100.0 - r) * 7.0e-6)

    return round(float(np.clip(mos, 1.0, 4.5)), 2)


class RealtimeDashboardMetricsCollector:
    """
    Prometheus / Grafana Exporter ve Canlı SLA İzleme Kolektörü.
    - Yalnızca GERÇEK olaylardan (çağrı başlangıç/bitiş, TTS sentez ölçümü) beslenir.
    - Ölçülmemiş değer None'dur (JSON'da null); Prometheus çıktısında örnek hiç yazılmaz.
    - Veri olmayan SLA kontrolü "veri yok" durumundadır, "geçti" sayılmaz.
    """

    def __init__(self, sla_config: Optional[SLAConfig] = None):
        self.sla_config = sla_config or SLAConfig()
        self._lock = threading.Lock()

        # Telemetri Sayaçları ve Pencereleri
        self.active_calls: int = 0
        self.total_calls_inbound: int = 0
        self.total_calls_outbound: int = 0
        self.total_calls_completed: int = 0
        self.total_calls_failed: int = 0

        # Ağ & AudioSocket: yalnızca gerçek ölçüm gelirse dolar
        self.audiosocket_packet_loss_ratio: Optional[float] = None
        self.audiosocket_jitter_ms: Optional[float] = None

        # TTS & Akustik: ölçüm yoksa None / boş
        self.tts_rtf_ema: Optional[float] = None
        self.inference_latencies: collections.deque = collections.deque(maxlen=200)

        # Müşteri Deneyimi & Kuyruk: yalnızca gerçek (dışarıdan bildirilen) CSAT ve bekleme süreleri
        self.csat_scores: collections.deque = collections.deque(maxlen=100)
        self.queue_wait_times_sec: collections.deque = collections.deque(maxlen=100)

    def record_call_start(self, direction: str = "inbound") -> None:
        """Yeni bir çağrı başladığında sayaçları artırır."""
        with self._lock:
            self.active_calls += 1
            if direction == "outbound":
                self.total_calls_outbound += 1
            else:
                self.total_calls_inbound += 1

    def record_call_end(
        self,
        *,
        success: bool = True,
        duration_sec: Optional[float] = None,
        packet_loss_pct: Optional[float] = None,
        jitter_ms: Optional[float] = None,
        csat_score: Optional[float] = None,
        queue_wait_sec: Optional[float] = None,
        converted_to_appointment: bool = False,
    ) -> None:
        """Bir çağrı tamamlandığında metrikleri günceller.

        converted_to_appointment geriye dönük uyumluluk için kabul edilir ama bellekte
        sayaç tutulmaz: lead/randevu verisi veritabanından hesaplanır.
        """
        with self._lock:
            self.active_calls = max(0, self.active_calls - 1)
            if success:
                self.total_calls_completed += 1
            else:
                self.total_calls_failed += 1

            if packet_loss_pct is not None:
                self.audiosocket_packet_loss_ratio = max(0.0, packet_loss_pct / 100.0)
            if jitter_ms is not None:
                self.audiosocket_jitter_ms = max(0.0, jitter_ms)
            if csat_score is not None:
                self.csat_scores.append(csat_score)
            if queue_wait_sec is not None:
                self.queue_wait_times_sec.append(queue_wait_sec)

    def record_tts_inference(self, duration_audio_sec: float, inference_time_sec: float) -> None:
        """FreyaTTS sentez gecikmesi ve RTF değerini kaydeder."""
        if inference_time_sec > 0:
            rtf = inference_time_sec / max(0.01, duration_audio_sec)
            lat_ms = inference_time_sec * 1000.0
            with self._lock:
                self.inference_latencies.append(lat_ms)
                # RTF EMA (ilk ölçüm doğrudan başlangıç değeridir)
                if self.tts_rtf_ema is None:
                    self.tts_rtf_ema = round(rtf, 3)
                else:
                    self.tts_rtf_ema = round((0.2 * rtf) + (0.8 * self.tts_rtf_ema), 3)

    def get_latency_percentiles(self) -> Dict[str, Optional[float]]:
        """P50, P90, P95 ve P99 inferans gecikmelerini hesaplar; ölçüm yoksa hepsi None."""
        with self._lock:
            arr = list(self.inference_latencies)
        if not arr:
            return {"p50": None, "p90": None, "p95": None, "p99": None}

        np_arr = np.array(arr)
        return {
            "p50": round(float(np.percentile(np_arr, 50)), 1),
            "p90": round(float(np.percentile(np_arr, 90)), 1),
            "p95": round(float(np.percentile(np_arr, 95)), 1),
            "p99": round(float(np.percentile(np_arr, 99)), 1),
        }

    @staticmethod
    def _crm_counts() -> Dict[str, Optional[int]]:
        """Lead ve randevu sayılarını veritabanından okur; okunamazsa None döner."""
        try:
            from sqlalchemy import func, select

            from backend.db import Appointment, Conversation, Session

            with Session() as db:
                leads = db.scalar(select(func.count()).select_from(Conversation))
                appts = db.scalar(
                    select(func.count()).select_from(Appointment).where(Appointment.status != "cancelled")
                )
            return {"total_leads": int(leads or 0), "appointments": int(appts or 0)}
        except Exception:
            logger.debug("CRM sayaçları okunamadı", exc_info=True)
            return {"total_leads": None, "appointments": None}

    def evaluate_sla_status(self) -> SLAReport:
        """Canlı SLA kurallarını değerlendirir; verisi olmayan kontrol "veri yok" olur."""
        now_iso = datetime.now(timezone.utc).isoformat()
        percentiles = self.get_latency_percentiles()
        p95_lat = percentiles["p95"]

        with self._lock:
            # 1. Yanıtlama / Tamamlama Oranı (çağrı yoksa None)
            total = self.total_calls_completed + self.total_calls_failed
            answer_rate = (
                round((self.total_calls_completed / total) * 100.0, 2) if total > 0 else None
            )

            # 2. Paket kaybı (yalnızca gerçek ölçümse)
            packet_loss_pct = (
                self.audiosocket_packet_loss_ratio * 100.0
                if self.audiosocket_packet_loss_ratio is not None
                else None
            )

            # 3. Kuyruk Bekleme Süresi
            avg_wait = (
                round(float(np.mean(self.queue_wait_times_sec)), 1)
                if self.queue_wait_times_sec
                else None
            )

        # GPU Telemetrisi (kilit dışında; ölçülemeyen değer None)
        gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
        vram_pct = gpu_snap.vram_occupancy_percent
        temp_c = gpu_snap.gpu_temperature_c

        cfg = self.sla_config
        checks: List[SLACheckItem] = []

        def add(name, desc, target, value, unit, breach, warn=False):
            """value None ise 'veri yok'; aksi halde PASS/WARN/FAIL."""
            if value is None:
                checks.append(SLACheckItem(name, desc, target, None, unit, NO_DATA_STATUS, False))
                return
            br = bool(breach)
            checks.append(
                SLACheckItem(name, desc, target, value, unit, "FAIL" if br else ("WARN" if warn else "PASS"), br)
            )

        add(
            "tts_p95_latency", "P95 TTS Sentez Gecikmesi", f"< {cfg.max_p95_latency_ms} ms",
            p95_lat, "ms",
            p95_lat is not None and p95_lat > cfg.max_p95_latency_ms,
            p95_lat is not None and p95_lat > cfg.max_p95_latency_ms * 0.85,
        )
        add(
            "call_answer_rate", "Çağrı Başarı / Yanıtlama Oranı", f">= %{cfg.min_call_answer_rate_pct}",
            answer_rate, "%",
            answer_rate is not None and answer_rate < cfg.min_call_answer_rate_pct,
        )
        # MOS: gerçek ölçüm kaynağı yok (RTCP/ses analizi bağlı değil) → her zaman veri yok
        add("sip_mos_score", "SIP Hat Ses Kalitesi (MOS)", f">= {cfg.min_mos_score}", None, "MOS", False)
        add(
            "packet_loss", "AudioSocket Paket Kayıp Oranı", f"< %{cfg.max_packet_loss_pct}",
            round(packet_loss_pct, 2) if packet_loss_pct is not None else None, "%",
            packet_loss_pct is not None and packet_loss_pct > cfg.max_packet_loss_pct,
        )
        add(
            "gpu_vram_occupancy", "GPU VRAM Bellek Doluluğu", f"< %{cfg.max_gpu_vram_pct}",
            vram_pct, "%",
            vram_pct is not None and vram_pct > cfg.max_gpu_vram_pct,
            vram_pct is not None and vram_pct > 80.0,
        )
        add(
            "gpu_temperature", "GPU Çekirdek Sıcaklığı", f"< {cfg.max_gpu_temp_c} °C",
            temp_c, "°C",
            temp_c is not None and temp_c > cfg.max_gpu_temp_c,
            temp_c is not None and temp_c > 75.0,
        )
        add(
            "queue_wait_time", "Ortalama Kuyruk Bekleme Süresi", f"< {cfg.max_queue_wait_sec} sn",
            avg_wait, "sn",
            avg_wait is not None and avg_wait > cfg.max_queue_wait_sec,
        )

        total_cnt = len(checks)
        evaluated = [c for c in checks if c.status != NO_DATA_STATUS]
        breached_cnt = sum(1 for c in evaluated if c.is_breached)
        passed_cnt = len(evaluated) - breached_cnt

        if not evaluated:
            # Hiçbir metrik ölçülmedi: "geçti" demek yanıltıcı olur
            overall = SLAComplianceLevel.NO_DATA.value
            score: Optional[float] = None
        else:
            score = round((passed_cnt / len(evaluated)) * 100.0, 1)
            if breached_cnt == 0:
                overall = SLAComplianceLevel.HEALTHY.value
            elif breached_cnt <= 2:
                overall = SLAComplianceLevel.WARNING.value
            else:
                overall = SLAComplianceLevel.BREACHED.value

        return SLAReport(
            overall_status=overall,
            compliance_score_pct=score,
            evaluated_at=now_iso,
            total_checks=total_cnt,
            passed_checks=passed_cnt,
            breached_checks=breached_cnt,
            checks=checks,
        )

    def generate_prometheus_metrics_text(self) -> str:
        """
        Prometheus exposition formatında (version 0.0.4) sistem metriklerini üretir.
        Verisi olmayan metriklerin örneği (sample) hiç yazılmaz; 0 basılmaz.
        """
        percentiles = self.get_latency_percentiles()
        gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
        cache_metrics = telephony_audio_cache.get_metrics()
        trunks = sip_trunk_failover_manager.list_trunks()
        crm = self._crm_counts()

        with self._lock:
            active = self.active_calls
            inbound = self.total_calls_inbound
            outbound = self.total_calls_outbound
            completed = self.total_calls_completed
            failed = self.total_calls_failed
            pkt_loss = self.audiosocket_packet_loss_ratio
            jitter = self.audiosocket_jitter_ms
            rtf = self.tts_rtf_ema
            avg_csat = round(float(np.mean(self.csat_scores)), 2) if self.csat_scores else None
            avg_wait = round(float(np.mean(self.queue_wait_times_sec)), 2) if self.queue_wait_times_sec else None

        lines: List[str] = []

        def gauge(name: str, help_text: str, samples: List[Tuple[str, Any]], fmt: str = "{}") -> None:
            """Yalnızca değeri olan örnekleri yazar; hiç örnek yoksa metriği tamamen atlar."""
            valid = [(lbl, v) for lbl, v in samples if v is not None]
            if not valid:
                return
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            for lbl, v in valid:
                lines.append(f"{name}{lbl} {fmt.format(v)}")
            lines.append("")

        gauge("freya_active_calls", "Anlık devam eden toplam aktif telefon görüşmesi sayısı.", [("", active)])
        lines.extend([
            "# HELP freya_calls_total Başlatılan ve sonlanan toplam telefon görüşmeleri.",
            "# TYPE freya_calls_total counter",
            f'freya_calls_total{{direction="inbound"}} {inbound}',
            f'freya_calls_total{{direction="outbound"}} {outbound}',
            f'freya_calls_total{{status="completed"}} {completed}',
            f'freya_calls_total{{status="failed"}} {failed}',
            "",
        ])
        gauge("freya_audiosocket_packet_loss_ratio", "Asterisk AudioSocket paket kayıp oranı (0.0 - 1.0).",
              [("", pkt_loss)], "{:.4f}")
        gauge("freya_audiosocket_jitter_ms", "Asterisk AudioSocket hat gecikme sapması (jitter).",
              [("", jitter)], "{:.2f}")
        # freya_sip_mos_score bilerek yok: gerçek MOS ölçümü bulunmuyor
        gauge("freya_tts_rtf", "FreyaTTS Gerçek Zamanlılık Katsayısı (Real-Time Factor).", [("", rtf)], "{:.3f}")
        gauge(
            "freya_tts_inference_latency_ms", "FreyaTTS ODE inferans gecikmesi yüzdelikleri.",
            [
                ('{quantile="0.50"}', percentiles["p50"]),
                ('{quantile="0.90"}', percentiles["p90"]),
                ('{quantile="0.95"}', percentiles["p95"]),
                ('{quantile="0.99"}', percentiles["p99"]),
            ],
        )
        vram = gpu_snap.vram_occupancy_percent
        gauge("freya_gpu_vram_occupancy_ratio", "GPU VRAM doluluk oranı (0.0 - 1.0).",
              [("", vram / 100.0 if vram is not None else None)], "{:.3f}")
        gauge("freya_gpu_temperature_celsius", "GPU çekirdek sıcaklığı (°C).",
              [("", gpu_snap.gpu_temperature_c)], "{:.1f}")

        # Devre kesici numerik durum: CLOSED=0, HALF_OPEN=1, OPEN=2
        cb_val = 0
        if gpu_snap.circuit_state == CircuitState.HALF_OPEN.value:
            cb_val = 1
        elif gpu_snap.circuit_state == CircuitState.OPEN.value:
            cb_val = 2
        gauge("freya_gpu_circuit_breaker_state", "GPU Devre Kesici durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN).",
              [("", cb_val)])
        gauge("freya_audio_cache_hit_rate_percent", "RAM ses önbelleği isabet oranı (hiç sorgu yoksa yazılmaz).",
              [("", cache_metrics.get("hit_rate_percent"))], "{:.2f}")
        gauge("freya_customer_csat_average", "Dışarıdan bildirilen gerçek CSAT ortalaması (1.0 - 5.0).",
              [("", avg_csat)], "{:.2f}")
        gauge("freya_queue_wait_time_seconds", "Bildirilen kuyruk bekleme süresi ortalaması.",
              [("", avg_wait)], "{:.1f}")
        gauge("freya_leads_total", "Veritabanındaki görüşme (lead) sayısı.", [("", crm["total_leads"])])
        # Lead dönüşüm oranı yok: görüşme ile randevu arasında bağ tutulmuyor

        # SIP Trunk bazlı metrikler (RTT yalnızca ölçüldüyse)
        status_samples: List[Tuple[str, Any]] = []
        rtt_samples: List[Tuple[str, Any]] = []
        for t in trunks:
            st = t["status"]
            if st == TrunkStatus.HEALTHY.value:
                val: Optional[float] = 1.0
            elif st == TrunkStatus.DEGRADED.value:
                val = 0.5
            elif st == TrunkStatus.DOWN.value:
                val = 0.0
            else:
                val = None  # unknown: durum doğrulanmadı
            status_samples.append((f'{{trunk_id="{t["trunk_id"]}",priority="{t["priority"]}"}}', val))
            rtt_samples.append((f'{{trunk_id="{t["trunk_id"]}"}}', t.get("rtt_ms")))
        gauge("freya_sip_trunk_status", "SIP Trunk hat durumu (1=HEALTHY, 0.5=DEGRADED, 0=DOWN).", status_samples)
        gauge("freya_sip_trunk_rtt_ms", "SIP OPTIONS ping RTT gecikmesi (ms).", rtt_samples, "{:.1f}")

        return "\n".join(lines)

    def get_live_dashboard_summary(self) -> Dict[str, Any]:
        """Grafana panelleri ve web dashboard için konsolide JSON özeti (ölçülmeyen değer null)."""
        sla_report = self.evaluate_sla_status()
        percentiles = self.get_latency_percentiles()
        gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
        cache_metrics = telephony_audio_cache.get_metrics()
        trunks = sip_trunk_failover_manager.list_trunks()
        crm = self._crm_counts()

        with self._lock:
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sla": sla_report.to_dict(),
                "telephony": {
                    "active_calls": self.active_calls,
                    "total_calls_inbound": self.total_calls_inbound,
                    "total_calls_outbound": self.total_calls_outbound,
                    "total_calls_completed": self.total_calls_completed,
                    "total_calls_failed": self.total_calls_failed,
                    # Gerçek MOS ölçümü yok
                    "estimated_mos": None,
                    "packet_loss_percent": (
                        round(self.audiosocket_packet_loss_ratio * 100.0, 3)
                        if self.audiosocket_packet_loss_ratio is not None
                        else None
                    ),
                    "jitter_ms": (
                        round(self.audiosocket_jitter_ms, 2) if self.audiosocket_jitter_ms is not None else None
                    ),
                },
                "tts_performance": {
                    "rtf": round(self.tts_rtf_ema, 3) if self.tts_rtf_ema is not None else None,
                    "p50_latency_ms": percentiles["p50"],
                    "p90_latency_ms": percentiles["p90"],
                    "p95_latency_ms": percentiles["p95"],
                    "p99_latency_ms": percentiles["p99"],
                },
                "hardware": {
                    "gpu_name": gpu_snap.gpu_name,
                    "vram_occupancy_percent": gpu_snap.vram_occupancy_percent,
                    "gpu_temperature_c": gpu_snap.gpu_temperature_c,
                    "circuit_state": gpu_snap.circuit_state,
                    "simulated": gpu_snap.simulated,
                },
                "trunks": trunks,
                "audio_cache": {
                    "cached_phrases_count": cache_metrics.get("cached_phrases_count", 0),
                    "hit_rate_percent": cache_metrics.get("hit_rate_percent"),
                    "total_lookups": cache_metrics.get("total_lookups", 0),
                },
                "crm_kpis": {
                    # Gerçek CSAT yalnızca dışarıdan bildirilen puanlardır; tahmini duygu skoru buraya girmez
                    "csat_average": (
                        round(float(np.mean(self.csat_scores)), 2) if self.csat_scores else None
                    ),
                    "total_leads": crm["total_leads"],
                    "appointments_total": crm["appointments"],
                    # Görüşme↔randevu bağı tutulmadığından oran hesaplanamaz
                    "conversion_rate_percent": None,
                    "converted_appointments": None,
                },
            }
        return summary


# Global Singleton Instance
dashboard_metrics_collector = RealtimeDashboardMetricsCollector()
