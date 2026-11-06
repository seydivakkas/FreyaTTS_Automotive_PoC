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
    actual_value: float
    unit: str
    status: str              # "PASS", "WARN", "FAIL"
    is_breached: bool


@dataclass
class SLAReport:
    overall_status: str
    compliance_score_pct: float
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
    - Tüm sesli asistan bileşenlerinden telemetri toplar.
    - Prometheus text exposition formatında (/metrics) dışa aktarır.
    - Canlı SLA kurallarını değerlendirerek ihlalleri tespit eder.
    - Grafana ve web arayüzleri için konsolide JSON paneli sağlar.
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

        # Ağ & AudioSocket
        self.audiosocket_packet_loss_ratio: float = 0.002  # %0.2
        self.audiosocket_jitter_ms: float = 2.4            # 2.4 ms

        # TTS & Akustik
        self.tts_rtf_ema: float = 0.18                     # Real-Time Factor (0.18x)
        self.inference_latencies: collections.deque = collections.deque(maxlen=200)
        # Başlangıç referans latansları (ms)
        for val in [110.0, 125.0, 130.0, 145.0, 160.0, 180.0, 210.0]:
            self.inference_latencies.append(val)

        # Müşteri Deneyimi & Kuyruk
        self.csat_scores: collections.deque = collections.deque(maxlen=100)
        for s in [4.5, 4.8, 5.0, 4.2, 4.7]:
            self.csat_scores.append(s)
        self.queue_wait_times_sec: collections.deque = collections.deque(maxlen=100)
        self.queue_wait_times_sec.append(8.5)

        # Lead Dönüşüm
        self.total_leads: int = 42
        self.converted_appointments: int = 36

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
        duration_sec: float = 60.0,
        packet_loss_pct: Optional[float] = None,
        jitter_ms: Optional[float] = None,
        csat_score: Optional[float] = None,
        queue_wait_sec: Optional[float] = None,
        converted_to_appointment: bool = False,
    ) -> None:
        """Bir çağrı tamamlandığında metrikleri günceller."""
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
            if converted_to_appointment:
                self.converted_appointments += 1
            self.total_leads += 1

    def record_tts_inference(self, duration_audio_sec: float, inference_time_sec: float) -> None:
        """FreyaTTS sentez gecikmesi ve RTF değerini kaydeder."""
        if inference_time_sec > 0:
            rtf = inference_time_sec / max(0.01, duration_audio_sec)
            lat_ms = inference_time_sec * 1000.0
            with self._lock:
                self.inference_latencies.append(lat_ms)
                # RTF EMA
                self.tts_rtf_ema = round((0.2 * rtf) + (0.8 * self.tts_rtf_ema), 3)

    def get_latency_percentiles(self) -> Dict[str, float]:
        """P50, P90, P95 ve P99 inferans gecikmelerini hesaplar."""
        with self._lock:
            arr = list(self.inference_latencies)
        if not arr:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}

        np_arr = np.array(arr)
        return {
            "p50": round(float(np.percentile(np_arr, 50)), 1),
            "p90": round(float(np.percentile(np_arr, 90)), 1),
            "p95": round(float(np.percentile(np_arr, 95)), 1),
            "p99": round(float(np.percentile(np_arr, 99)), 1),
        }

    def evaluate_sla_status(self) -> SLAReport:
        """Canlı SLA kurallarını değerlendirir ve rapor döner."""
        now_iso = datetime.now(timezone.utc).isoformat()
        percentiles = self.get_latency_percentiles()
        p95_lat = percentiles["p95"]

        with self._lock:
            # 1. Yanıtlama / Tamamlama Oranı
            total = self.total_calls_completed + self.total_calls_failed
            answer_rate = (
                round((self.total_calls_completed / total) * 100.0, 2)
                if total > 0
                else 100.0
            )

            # 2. MOS Skoru
            packet_loss_pct = self.audiosocket_packet_loss_ratio * 100.0
            mos = calculate_itu_mos(
                rtt_ms=25.0,
                jitter_ms=self.audiosocket_jitter_ms,
                packet_loss_pct=packet_loss_pct,
            )

            # 3. GPU Telemetrisi
            gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
            vram_pct = gpu_snap.vram_occupancy_percent
            temp_c = gpu_snap.gpu_temperature_c

            # 4. Kuyruk Bekleme Süresi
            avg_wait = (
                round(float(np.mean(self.queue_wait_times_sec)), 1)
                if self.queue_wait_times_sec
                else 0.0
            )

        checks: List[SLACheckItem] = []

        # Check 1: P95 Latans
        lat_breach = p95_lat > self.sla_config.max_p95_latency_ms
        checks.append(
            SLACheckItem(
                metric_name="tts_p95_latency",
                description="P95 TTS Sentez Gecikmesi",
                target=f"< {self.sla_config.max_p95_latency_ms} ms",
                actual_value=p95_lat,
                unit="ms",
                status="FAIL" if lat_breach else ("WARN" if p95_lat > self.sla_config.max_p95_latency_ms * 0.85 else "PASS"),
                is_breached=lat_breach,
            )
        )

        # Check 2: Yanıtlama Oranı
        ans_breach = answer_rate < self.sla_config.min_call_answer_rate_pct
        checks.append(
            SLACheckItem(
                metric_name="call_answer_rate",
                description="Çağrı Başarı / Yanıtlama Oranı",
                target=f">= %{self.sla_config.min_call_answer_rate_pct}",
                actual_value=answer_rate,
                unit="%",
                status="FAIL" if ans_breach else "PASS",
                is_breached=ans_breach,
            )
        )

        # Check 3: MOS Ses Kalitesi
        mos_breach = mos < self.sla_config.min_mos_score
        checks.append(
            SLACheckItem(
                metric_name="sip_mos_score",
                description="SIP Hat Ses Kalitesi (MOS)",
                target=f">= {self.sla_config.min_mos_score}",
                actual_value=mos,
                unit="MOS",
                status="FAIL" if mos_breach else ("WARN" if mos < 4.2 else "PASS"),
                is_breached=mos_breach,
            )
        )

        # Check 4: Paket Kaybı
        loss_breach = packet_loss_pct > self.sla_config.max_packet_loss_pct
        checks.append(
            SLACheckItem(
                metric_name="packet_loss",
                description="AudioSocket Paket Kayıp Oranı",
                target=f"< %{self.sla_config.max_packet_loss_pct}",
                actual_value=round(packet_loss_pct, 2),
                unit="%",
                status="FAIL" if loss_breach else "PASS",
                is_breached=loss_breach,
            )
        )

        # Check 5: GPU VRAM
        vram_breach = vram_pct > self.sla_config.max_gpu_vram_pct
        checks.append(
            SLACheckItem(
                metric_name="gpu_vram_occupancy",
                description="GPU VRAM Bellek Doluluğu",
                target=f"< %{self.sla_config.max_gpu_vram_pct}",
                actual_value=vram_pct,
                unit="%",
                status="FAIL" if vram_breach else ("WARN" if vram_pct > 80.0 else "PASS"),
                is_breached=vram_breach,
            )
        )

        # Check 6: GPU Sıcaklık
        temp_breach = temp_c > self.sla_config.max_gpu_temp_c
        checks.append(
            SLACheckItem(
                metric_name="gpu_temperature",
                description="GPU Çekirdek Sıcaklığı",
                target=f"< {self.sla_config.max_gpu_temp_c} °C",
                actual_value=temp_c,
                unit="°C",
                status="FAIL" if temp_breach else ("WARN" if temp_c > 75.0 else "PASS"),
                is_breached=temp_breach,
            )
        )

        # Check 7: Kuyruk Bekleme Süresi
        wait_breach = avg_wait > self.sla_config.max_queue_wait_sec
        checks.append(
            SLACheckItem(
                metric_name="queue_wait_time",
                description="Ortalama Kuyruk Bekleme Süresi",
                target=f"< {self.sla_config.max_queue_wait_sec} sn",
                actual_value=avg_wait,
                unit="sn",
                status="FAIL" if wait_breach else "PASS",
                is_breached=wait_breach,
            )
        )

        total_cnt = len(checks)
        breached_cnt = sum(1 for c in checks if c.is_breached)
        passed_cnt = total_cnt - breached_cnt
        score = round((passed_cnt / total_cnt) * 100.0, 1)

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
        Prometheus exposition formatında (version 0.0.4) tüm sistem metriklerini üretir.
        """
        percentiles = self.get_latency_percentiles()
        gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
        cache_metrics = telephony_audio_cache.get_metrics()
        trunks = sip_trunk_failover_manager.list_trunks()

        with self._lock:
            active = self.active_calls
            inbound = self.total_calls_inbound
            outbound = self.total_calls_outbound
            completed = self.total_calls_completed
            failed = self.total_calls_failed
            pkt_loss = self.audiosocket_packet_loss_ratio
            jitter = self.audiosocket_jitter_ms
            rtf = self.tts_rtf_ema
            mos = calculate_itu_mos(rtt_ms=25.0, jitter_ms=jitter, packet_loss_pct=pkt_loss * 100.0)
            avg_csat = round(float(np.mean(self.csat_scores)), 2) if self.csat_scores else 5.0
            avg_wait = round(float(np.mean(self.queue_wait_times_sec)), 2) if self.queue_wait_times_sec else 0.0
            conv_rate = round((self.converted_appointments / max(1, self.total_leads)) * 100.0, 2)

        # Devre kesici numerik durum: CLOSED=0, HALF_OPEN=1, OPEN=2
        cb_val = 0
        if gpu_snap.circuit_state == CircuitState.HALF_OPEN.value:
            cb_val = 1
        elif gpu_snap.circuit_state == CircuitState.OPEN.value:
            cb_val = 2

        lines: List[str] = [
            "# HELP freya_active_calls Anlık devam eden toplam aktif telefon görüşmesi sayısı.",
            "# TYPE freya_active_calls gauge",
            f"freya_active_calls {active}",
            "",
            "# HELP freya_calls_total Başlatılan ve sonlanan toplam telefon görüşmeleri.",
            "# TYPE freya_calls_total counter",
            f'freya_calls_total{{direction="inbound"}} {inbound}',
            f'freya_calls_total{{direction="outbound"}} {outbound}',
            f'freya_calls_total{{status="completed"}} {completed}',
            f'freya_calls_total{{status="failed"}} {failed}',
            "",
            "# HELP freya_audiosocket_packet_loss_ratio Asterisk AudioSocket paket kayıp oranı (0.0 - 1.0).",
            "# TYPE freya_audiosocket_packet_loss_ratio gauge",
            f"freya_audiosocket_packet_loss_ratio {pkt_loss:.4f}",
            "",
            "# HELP freya_audiosocket_jitter_ms Asterisk AudioSocket hat gecikme sapması (jitter).",
            "# TYPE freya_audiosocket_jitter_ms gauge",
            f"freya_audiosocket_jitter_ms {jitter:.2f}",
            "",
            "# HELP freya_sip_mos_score Tahmini telefon ses kalitesi Mean Opinion Score (1.0 - 4.5).",
            "# TYPE freya_sip_mos_score gauge",
            f"freya_sip_mos_score {mos:.2f}",
            "",
            "# HELP freya_tts_rtf FreyaTTS Gerçek Zamanlılık Katsayısı (Real-Time Factor).",
            "# TYPE freya_tts_rtf gauge",
            f"freya_tts_rtf {rtf:.3f}",
            "",
            "# HELP freya_tts_inference_latency_ms FreyaTTS ODE inferans gecikmesi yüzdelikleri.",
            "# TYPE freya_tts_inference_latency_ms gauge",
            f'freya_tts_inference_latency_ms{{quantile="0.50"}} {percentiles["p50"]}',
            f'freya_tts_inference_latency_ms{{quantile="0.90"}} {percentiles["p90"]}',
            f'freya_tts_inference_latency_ms{{quantile="0.95"}} {percentiles["p95"]}',
            f'freya_tts_inference_latency_ms{{quantile="0.99"}} {percentiles["p99"]}',
            "",
            "# HELP freya_gpu_vram_occupancy_ratio GPU VRAM doluluk oranı (0.0 - 1.0).",
            "# TYPE freya_gpu_vram_occupancy_ratio gauge",
            f"freya_gpu_vram_occupancy_ratio {gpu_snap.vram_occupancy_percent / 100.0:.3f}",
            "",
            "# HELP freya_gpu_temperature_celsius GPU çekirdek sıcaklığı (°C).",
            "# TYPE freya_gpu_temperature_celsius gauge",
            f"freya_gpu_temperature_celsius {gpu_snap.gpu_temperature_c:.1f}",
            "",
            "# HELP freya_gpu_circuit_breaker_state GPU Devre Kesici durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN).",
            "# TYPE freya_gpu_circuit_breaker_state gauge",
            f"freya_gpu_circuit_breaker_state {cb_val}",
            "",
            "# HELP freya_audio_cache_hit_rate_percent Sık kullanılan 25 kalıp cümlenin RAM önbellek isabet oranı.",
            "# TYPE freya_audio_cache_hit_rate_percent gauge",
            f"freya_audio_cache_hit_rate_percent {cache_metrics.get('hit_rate_percent', 0.0):.2f}",
            "",
            "# HELP freya_customer_csat_average Ortalama müşteri memnuniyet skoru (1.0 - 5.0).",
            "# TYPE freya_customer_csat_average gauge",
            f"freya_customer_csat_average {avg_csat:.2f}",
            "",
            "# HELP freya_queue_wait_time_seconds Ekspertiz lifti ve operatör kuyruk bekleme süresi.",
            "# TYPE freya_queue_wait_time_seconds gauge",
            f"freya_queue_wait_time_seconds {avg_wait:.1f}",
            "",
            "# HELP freya_lead_conversion_rate_percent Çağrıların randevuya dönüşme oranı (Lead Conversion %).",
            "# TYPE freya_lead_conversion_rate_percent gauge",
            f"freya_lead_conversion_rate_percent {conv_rate:.2f}",
            "",
        ]

        # SIP Trunk bazlı metrikler
        lines.append("# HELP freya_sip_trunk_status SIP Trunk hat durumu (1=HEALTHY, 0.5=DEGRADED, 0=DOWN).")
        lines.append("# TYPE freya_sip_trunk_status gauge")
        for t in trunks:
            st = t["status"]
            val = 1.0 if st == TrunkStatus.HEALTHY.value else (0.5 if st == TrunkStatus.DEGRADED.value else 0.0)
            lines.append(f'freya_sip_trunk_status{{trunk_id="{t["trunk_id"]}",priority="{t["priority"]}"}} {val}')

        lines.append("")
        lines.append("# HELP freya_sip_trunk_rtt_ms SIP OPTIONS ping RTT gecikmesi (ms).")
        lines.append("# TYPE freya_sip_trunk_rtt_ms gauge")
        for t in trunks:
            lines.append(f'freya_sip_trunk_rtt_ms{{trunk_id="{t["trunk_id"]}"}} {t["rtt_ms"]:.1f}')

        lines.append("")
        return "\n".join(lines)

    def get_live_dashboard_summary(self) -> Dict[str, Any]:
        """Grafana panelleri ve web dashboard için konsolide JSON özeti üretir."""
        sla_report = self.evaluate_sla_status()
        percentiles = self.get_latency_percentiles()
        gpu_snap = gpu_health_circuit_breaker.sample_telemetry()
        cache_metrics = telephony_audio_cache.get_metrics()
        trunks = sip_trunk_failover_manager.list_trunks()

        with self._lock:
            mos = calculate_itu_mos(
                rtt_ms=25.0,
                jitter_ms=self.audiosocket_jitter_ms,
                packet_loss_pct=self.audiosocket_packet_loss_ratio * 100.0,
            )
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sla": sla_report.to_dict(),
                "telephony": {
                    "active_calls": self.active_calls,
                    "total_calls_inbound": self.total_calls_inbound,
                    "total_calls_outbound": self.total_calls_outbound,
                    "total_calls_completed": self.total_calls_completed,
                    "total_calls_failed": self.total_calls_failed,
                    "estimated_mos": mos,
                    "packet_loss_percent": round(self.audiosocket_packet_loss_ratio * 100.0, 3),
                    "jitter_ms": round(self.audiosocket_jitter_ms, 2),
                },
                "tts_performance": {
                    "rtf": round(self.tts_rtf_ema, 3),
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
                },
                "trunks": trunks,
                "audio_cache": {
                    "cached_phrases_count": cache_metrics.get("cached_phrases_count", 0),
                    "hit_rate_percent": cache_metrics.get("hit_rate_percent", 0.0),
                    "total_lookups": cache_metrics.get("total_lookups", 0),
                },
                "crm_kpis": {
                    "csat_average": round(float(np.mean(self.csat_scores)), 2) if self.csat_scores else 5.0,
                    "conversion_rate_percent": round((self.converted_appointments / max(1, self.total_leads)) * 100.0, 1),
                    "total_leads": self.total_leads,
                    "converted_appointments": self.converted_appointments,
                },
            }
        return summary


# Global Singleton Instance
dashboard_metrics_collector = RealtimeDashboardMetricsCollector()

