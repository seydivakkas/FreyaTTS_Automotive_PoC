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
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import torch

logger = logging.getLogger("gpu_health_circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"          # Normal sağlıklı durum: GPU ODE / CUDA devrede
    HALF_OPEN = "HALF_OPEN"    # İyileşme / deneme durumu: Sınırlı kota ile test ediliyor
    OPEN = "OPEN"              # Devre kesildi / Arıza modu: GPU yükü durduruldu, failover aktif


class FailoverMode(str, Enum):
    CPU_CACHE = "cpu_cache"                  # Önbelleğe alınmış 8 kHz ses ve CPU int8 moduna geçiş
    OPERATOR_TRANSFER = "operator_transfer"  # Canlı operatöre SIP warm transfer
    GRACEFUL_DEGRADE = "graceful_degrade"    # ODE adım sayısını ve oturum kotasını düşürme


@dataclass
class GpuTelemetrySnapshot:
    gpu_available: bool
    gpu_name: str
    # Ölçülemeyen değerler None'dur (0 veya uydurma varsayılan DEĞİL).
    vram_total_mb: Optional[float]
    vram_used_mb: Optional[float]
    vram_free_mb: Optional[float]
    vram_occupancy_percent: Optional[float]
    gpu_temperature_c: Optional[float]
    gpu_utilization_percent: Optional[float]
    inference_latency_ms: Optional[float]
    inference_latency_ema_ms: Optional[float]
    circuit_state: str
    timestamp: str
    # True ise değerler gerçek donanımdan değil, simülasyon girdisinden gelir.
    simulated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CircuitBreakerConfig:
    vram_threshold_percent: float = 90.0      # %90 VRAM doluluğu üzerinde tetiklenir
    temp_threshold_c: float = 82.0            # 82°C çekirdek sıcaklığı üzerinde tetiklenir
    latency_threshold_ms: float = 400.0       # 400 ms ODE inferans gecikmesi üzerinde tetiklenir
    consecutive_failure_limit: int = 3        # Arka arkaya 3 eşik ihlalinde devre kesilir
    cooldown_seconds: float = 15.0            # OPEN durumunda bekleme süresi (sn)
    half_open_success_target: int = 5         # HALF_OPEN'dan CLOSED'a geçiş için başarılı adım sayısı
    default_failover_mode: FailoverMode = FailoverMode.CPU_CACHE


@dataclass
class FailoverAction:
    mode: str
    reason: str
    details: Dict[str, Any]
    recommended_prompt: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GpuHealthCircuitBreaker:
    """
    GPU VRAM / Sıcaklık / Gecikme Telemetrisi ve Akıllı Failover Devre Kesici (Circuit Breaker).
    - VRAM doluluğu (> %90), sıcaklık (> 82°C) veya ODE inferans gecikmesi (> 400 ms) aşıldığında
      sistemin çökmesini (CUDA OOM) engeller.
    - Yeni gelen çağrıları anında hafif CPU int8 STT + önbellek moduna veya canlı operatöre yönlendirir.
    - CLOSED -> OPEN -> HALF_OPEN -> CLOSED durum geçişlerini otomatik yönetir.
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        simulate_hardware: bool = False,
    ):
        self.config = config or CircuitBreakerConfig()
        self.simulate_hardware = simulate_hardware
        self._lock = threading.Lock()

        # Durum değişkenleri
        self.state: CircuitState = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.half_open_successes: int = 0
        self.trip_timestamp: float = 0.0
        self.total_trip_count: int = 0
        self.last_trip_reason: str = ""

        # Gecikme izleme penceresi
        self.latency_history: collections.deque = collections.deque(maxlen=50)
        # Henüz ölçüm yoksa None (uydurma başlangıç referansı kullanılmaz)
        self.latency_ema_ms: Optional[float] = None
        self.ema_alpha: float = 0.25

        # Simülasyon değişkenleri (Birim testleri ve senaryolar için)
        self._sim_vram_percent: Optional[float] = None
        self._sim_temp_c: Optional[float] = None
        self._sim_latency_ms: Optional[float] = None

    def _probe_nvidia_smi(self) -> Optional[Tuple[float, float, float, float]]:
        """nvidia-smi komutu ile sıcaklık, kullanılan bellek, toplam bellek ve kullanım %'sini sorgular."""
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                if len(parts) >= 4:
                    temp_c = float(parts[0])
                    used_mb = float(parts[1])
                    total_mb = float(parts[2])
                    util_pct = float(parts[3])
                    return temp_c, used_mb, total_mb, util_pct
        except Exception:
            pass
        return None

    def _probe_gpu_hardware(self) -> Tuple[bool, str, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], bool]:
        """
        Donanım durumunu sorgular.
        Döner: (available, name, total_mb, used_mb, free_mb, occupancy_pct, temp_c, util_pct, simulated)
        Bilinmeyen değerler None döner.
        """
        # 1. Simülasyon değerleri önceliklidir (test amaçlı); yalnızca verilen alanlar dolu, gerisi None
        if self._sim_vram_percent is not None or self._sim_temp_c is not None:
            occ_pct = self._sim_vram_percent
            return True, "simulated", None, None, None, occ_pct, self._sim_temp_c, None, True

        # 2. Gerçek donanım sorgusu
        has_cuda = torch.cuda.is_available() and torch.cuda.device_count() > 0
        gpu_name = torch.cuda.get_device_name(0) if has_cuda else "unknown"

        # Ölçülemeyen her değer None kalır (0 / 35°C gibi uydurma varsayılan yok)
        total_mb: Optional[float] = None
        used_mb: Optional[float] = None
        free_mb: Optional[float] = None
        occupancy_pct: Optional[float] = None
        temp_c: Optional[float] = None
        util_pct: Optional[float] = None

        if has_cuda:
            try:
                free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                total_mb = round(total_bytes / (1024 * 1024), 1)
                free_mb = round(free_bytes / (1024 * 1024), 1)
                used_mb = round((total_bytes - free_bytes) / (1024 * 1024), 1)
                occupancy_pct = round((used_mb / total_mb) * 100.0, 1) if total_mb > 0 else None
            except Exception as e:
                logger.warning("torch.cuda.mem_get_info başarısız: %s", e)

            # nvidia-smi ile sıcaklık ve kullanım oranı
            smi_data = self._probe_nvidia_smi()
            if smi_data is not None:
                temp_c, smi_used, smi_total, util_pct = smi_data
                if not total_mb:
                    total_mb = smi_total
                    used_mb = smi_used
                    free_mb = max(0.0, total_mb - used_mb)
                    occupancy_pct = round((used_mb / total_mb) * 100.0, 1) if total_mb > 0 else None

        return has_cuda, gpu_name, total_mb, used_mb, free_mb, occupancy_pct, temp_c, util_pct, False

    def record_inference_latency(self, latency_ms: float) -> None:
        """Sentezlenen cümlenin ODE inferans gecikmesini kaydeder ve EMA'yı günceller."""
        with self._lock:
            self.latency_history.append(latency_ms)
            if self.latency_ema_ms is None:
                self.latency_ema_ms = float(latency_ms)
            else:
                self.latency_ema_ms = (self.ema_alpha * latency_ms) + ((1.0 - self.ema_alpha) * self.latency_ema_ms)

    def record_cuda_oom_event(self, details: str = "") -> None:
        """CUDA OOM riski algılandığında veya istisnası fırlatıldığında anında devreyi keser (OPEN)."""
        with self._lock:
            self.state = CircuitState.OPEN
            self.trip_timestamp = time.monotonic()
            self.total_trip_count += 1
            self.last_trip_reason = f"CUDA Out of Memory (OOM) Tetiklendi! {details}".strip()
            self.consecutive_failures = self.config.consecutive_failure_limit
            logger.critical("GPU Devre Kesici ACİL AÇILDI (OPEN): %s", self.last_trip_reason)

    def sample_telemetry(self) -> GpuTelemetrySnapshot:
        """Anlık telemetri fotoğrafını çeker ve durum makinesini (state machine) işletir."""
        with self._lock:
            has_cuda, name, total_mb, used_mb, free_mb, occ_pct, temp_c, util_pct, simulated = self._probe_gpu_hardware()

            # Simülasyon gecikmesi (ölçüm yoksa None)
            latest_latency = self._sim_latency_ms if self._sim_latency_ms is not None else (
                self.latency_history[-1] if self.latency_history else None
            )
            current_ema = self._sim_latency_ms if self._sim_latency_ms is not None else self.latency_ema_ms
            if self._sim_latency_ms is not None:
                simulated = True

            # Eşik İhlalleri Denetimi (ölçülemeyen değer ihlal sayılmaz)
            violations = []
            if occ_pct is not None and occ_pct >= self.config.vram_threshold_percent:
                violations.append(f"VRAM doluluğu aşıldı (%{occ_pct:.1f} >= %{self.config.vram_threshold_percent:.1f})")
            if temp_c is not None and temp_c >= self.config.temp_threshold_c:
                violations.append(f"GPU sıcaklığı aşıldı ({temp_c:.1f}°C >= {self.config.temp_threshold_c:.1f}°C)")
            if current_ema is not None and current_ema >= self.config.latency_threshold_ms:
                violations.append(f"ODE inferans gecikmesi aşıldı ({current_ema:.1f} ms >= {self.config.latency_threshold_ms:.1f} ms)")

            now_mono = time.monotonic()

            # Durum Makinesi Geçişleri
            if self.state == CircuitState.CLOSED:
                if violations:
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= self.config.consecutive_failure_limit:
                        self.state = CircuitState.OPEN
                        self.trip_timestamp = now_mono
                        self.total_trip_count += 1
                        self.last_trip_reason = " | ".join(violations)
                        logger.warning("GPU Devre Kesici AÇILDI (OPEN)! Sebep: %s", self.last_trip_reason)
                else:
                    self.consecutive_failures = 0

            elif self.state == CircuitState.OPEN:
                # Cooldown süresi doldu mu kontrol et
                elapsed = now_mono - self.trip_timestamp
                if elapsed >= self.config.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_successes = 0
                    logger.info("GPU Devre Kesici YARI-AÇIK (HALF_OPEN) durumuna geçti. İyileşme test ediliyor.")

            elif self.state == CircuitState.HALF_OPEN:
                if violations:
                    # İyileşme aşamasında tekrar eşik aşılırsa derhal OPEN durumuna dön
                    self.state = CircuitState.OPEN
                    self.trip_timestamp = now_mono
                    self.last_trip_reason = "HALF_OPEN aşamasında tekrar eşik ihlali: " + " | ".join(violations)
                    logger.warning("GPU Devre Kesici tekrar AÇILDI (OPEN): %s", self.last_trip_reason)
                else:
                    self.half_open_successes += 1
                    if self.half_open_successes >= self.config.half_open_success_target:
                        self.state = CircuitState.CLOSED
                        self.consecutive_failures = 0
                        self.last_trip_reason = ""
                        logger.info("GPU Devre Kesici tamamen İYİLEŞTİ ve KAPANDI (CLOSED). Normal GPU sentezi aktif.")

            return GpuTelemetrySnapshot(
                gpu_available=has_cuda,
                gpu_name=name,
                vram_total_mb=total_mb,
                vram_used_mb=used_mb,
                vram_free_mb=free_mb,
                vram_occupancy_percent=occ_pct,
                gpu_temperature_c=temp_c,
                gpu_utilization_percent=util_pct,
                inference_latency_ms=round(latest_latency, 2) if latest_latency is not None else None,
                inference_latency_ema_ms=round(current_ema, 2) if current_ema is not None else None,
                circuit_state=self.state.value,
                timestamp=datetime.now(timezone.utc).isoformat(),
                simulated=simulated,
            )

    def should_allow_gpu_task(self, sample_now: bool = False) -> bool:
        """Yeni bir GPU sentez/inferans işinin başlatılmasına izin verilip verilmeyeceğini belirler."""
        if sample_now:
            self.sample_telemetry()
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.HALF_OPEN:
                # Yarı açık durumda yükün %50'sini GPU'ya yönlendirerek test et
                return (self.half_open_successes % 2) == 0
            # OPEN durumunda GPU'ya kesinlikle iş verilmez
            return False

    def get_failover_action(
        self,
        call_session_id: str = "",
        context: str = "",
        preferred_mode: Optional[Union[str, FailoverMode]] = None,
    ) -> FailoverAction:
        """
        GPU aşırı yüklendiğinde veya devre kesildiğinde uygulanacak eylemi üretir.
        """
        mode = preferred_mode or self.config.default_failover_mode
        if isinstance(mode, str):
            mode = FailoverMode(mode)

        snap = self.sample_telemetry()
        reason = self.last_trip_reason or f"GPU Devre Kesici Aktif ({self.state.value})"

        if mode == FailoverMode.OPERATOR_TRANSFER:
            return FailoverAction(
                mode=FailoverMode.OPERATOR_TRANSFER.value,
                reason=reason,
                details={
                    "session_id": call_session_id,
                    "target_extension": "1001",
                    "vram_occupancy_percent": snap.vram_occupancy_percent,
                    "gpu_temperature_c": snap.gpu_temperature_c,
                },
                recommended_prompt="Sistem yoğunluğu nedeniyle sizi müşteri temsilcimize aktarıyorum, lütfen hatta bekleyin.",
            )
        elif mode == FailoverMode.GRACEFUL_DEGRADE:
            return FailoverAction(
                mode=FailoverMode.GRACEFUL_DEGRADE.value,
                reason=reason,
                details={
                    "reduced_ode_steps": 16,
                    "max_batch_size": 2,
                    "vram_occupancy_percent": snap.vram_occupancy_percent,
                },
                recommended_prompt="Hafifletilmiş inferans modu devrede.",
            )
        else:
            # CPU_CACHE (varsayılan)
            return FailoverAction(
                mode=FailoverMode.CPU_CACHE.value,
                reason=reason,
                details={
                    "cache_pool": "TelephonyAudioCachePool",
                    "sample_rate": 8000,
                    "vram_occupancy_percent": snap.vram_occupancy_percent,
                },
                recommended_prompt="Şu anda hafif ses motorumuz devrede, size kesintisiz yardımcı olmaya devam ediyorum.",
            )

    def reset_circuit_breaker(self) -> None:
        """Devre kesici durumunu admin müdahalesiyle manuel olarak CLOSED yapar."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.half_open_successes = 0
            self.trip_timestamp = 0.0
            self.last_trip_reason = ""
            self._sim_vram_percent = None
            self._sim_temp_c = None
            self._sim_latency_ms = None
            logger.info("GPU Devre Kesici manuel olarak sıfırlandı (CLOSED).")

    def force_state(self, state: CircuitState, reason: str = "Manuel Test Zorlaması") -> None:
        """Test amaçlı olarak durum makinesini zorla belirli bir duruma sokar."""
        with self._lock:
            self.state = state
            if state == CircuitState.OPEN:
                self.trip_timestamp = time.monotonic()
                self.total_trip_count += 1
                self.last_trip_reason = reason
            elif state == CircuitState.CLOSED:
                self.consecutive_failures = 0
                self.last_trip_reason = ""

    def simulate_telemetry_metrics(
        self,
        vram_percent: Optional[float] = None,
        temperature_c: Optional[float] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        """Test senaryoları için donanım değerlerini simüle eder."""
        with self._lock:
            self._sim_vram_percent = vram_percent
            self._sim_temp_c = temperature_c
            self._sim_latency_ms = latency_ms

    def configure(
        self,
        *,
        vram_threshold_percent: Optional[float] = None,
        temp_threshold_c: Optional[float] = None,
        latency_threshold_ms: Optional[float] = None,
        cooldown_seconds: Optional[float] = None,
        consecutive_failure_limit: Optional[int] = None,
        default_failover_mode: Optional[Union[str, FailoverMode]] = None,
    ) -> None:
        """Devre kesici eşiklerini dinamik olarak günceller."""
        with self._lock:
            if vram_threshold_percent is not None:
                self.config.vram_threshold_percent = vram_threshold_percent
            if temp_threshold_c is not None:
                self.config.temp_threshold_c = temp_threshold_c
            if latency_threshold_ms is not None:
                self.config.latency_threshold_ms = latency_threshold_ms
            if cooldown_seconds is not None:
                self.config.cooldown_seconds = cooldown_seconds
            if consecutive_failure_limit is not None:
                self.config.consecutive_failure_limit = consecutive_failure_limit
            if default_failover_mode is not None:
                self.config.default_failover_mode = (
                    FailoverMode(default_failover_mode)
                    if isinstance(default_failover_mode, str)
                    else default_failover_mode
                )

    def get_status(self) -> Dict[str, Any]:
        """Tüm devre kesici durumunu ve yapılandırmasını özetler."""
        snap = self.sample_telemetry()
        with self._lock:
            return {
                "circuit_state": self.state.value,
                "is_gpu_available": snap.gpu_available,
                "simulated": snap.simulated,
                "total_trip_count": self.total_trip_count,
                "consecutive_failures": self.consecutive_failures,
                "last_trip_reason": self.last_trip_reason,
                "config": asdict(self.config),
                "telemetry": snap.to_dict(),
            }


# Global Singleton Instance
gpu_health_circuit_breaker = GpuHealthCircuitBreaker()
