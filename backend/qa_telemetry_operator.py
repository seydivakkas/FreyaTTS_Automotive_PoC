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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import math
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from pydantic import BaseModel, Field

from backend.text import normalize

logger = logging.getLogger("qa_telemetry_operator")


# ============================================================================
# 1. RT-09: RealtimeMetrics & Sahte Sıfır Yasağı (Fake Zero Prohibition)
# ============================================================================

class RealtimeTurnMetrics(BaseModel):
    """
    Turn-Level ve Generation-Level Dağıtık Telemetri Sözleşmesi (RT-09).

    KESİN KURAL - Sahte Sıfır Yasağı (Fake Zero Prohibition):
    Henüz gerçekleşmemiş veya ölçülmemiş hiçbir gecikme metriğine 0 değeri atanamaz;
    şemada zorunlu olarak None (JSON null) kullanılmalıdır.
    """
    turn_id: str
    generation_id: str = Field(default_factory=lambda: f"gen_{int(time.time()*1000)}")
    session_id: str
    caller_id: Optional[str] = None
    created_at_iso: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Gecikme Metrikleri (Zorunlu Nullable - Sahte 0 Yasak)
    vad_speech_start_ms: Optional[float] = None
    vad_speech_end_ms: Optional[float] = None
    asr_first_token_ms: Optional[float] = None
    asr_final_text_ms: Optional[float] = None
    asr_latency_ms: Optional[float] = None
    llm_first_token_ms: Optional[float] = None
    llm_ttft_ms: Optional[float] = None
    llm_full_text_ms: Optional[float] = None
    llm_total_latency_ms: Optional[float] = None
    tts_first_chunk_ms: Optional[float] = None
    tts_ttfa_ms: Optional[float] = None
    tts_total_latency_ms: Optional[float] = None
    playback_start_ms: Optional[float] = None
    barge_in_triggered_ms: Optional[float] = None
    barge_in_stop_ms: Optional[float] = None
    codec_transcode_ms: Optional[float] = None
    total_turn_latency_ms: Optional[float] = None

    # Akustik ve Ağ Kalite Metrikleri
    mos_score: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    jitter_ms: Optional[float] = None
    f0_mean_hz: Optional[float] = None
    rtf: Optional[float] = None
    avg_rtf: Optional[float] = None
    generation_chunks: List[Dict[str, Any]] = Field(default_factory=list)

    # Durum ve Varyant Bilgisi
    status: str = "in_progress"  # in_progress, completed, interrupted, taken_over
    applied_variant: str = "variant_b"  # variant_a, variant_b, variant_c
    codec: str = "pcm_48k"  # pcm_48k, g711_alaw, g711_ulaw, g722

    def validate_no_fake_zeros(self) -> Tuple[bool, List[str]]:
        """
        Sahte Sıfır Yasağı Denetimi:
        Henüz tamamlanmamış veya ölçülmemiş alanların 0.0 değil None olduğunu teyit eder.
        """
        violations: List[str] = []
        latency_fields = [
            "vad_speech_start_ms", "vad_speech_end_ms", "asr_first_token_ms",
            "asr_final_text_ms", "asr_latency_ms", "llm_first_token_ms", "llm_ttft_ms",
            "llm_full_text_ms", "llm_total_latency_ms", "tts_first_chunk_ms", "tts_ttfa_ms",
            "tts_total_latency_ms", "playback_start_ms", "barge_in_triggered_ms",
            "barge_in_stop_ms", "codec_transcode_ms", "total_turn_latency_ms",
        ]
        for f in latency_fields:
            val = getattr(self, f)
            # Kesin kural: Ölçülmemiş gecikme 0.0 olamaz; None olmalıdır
            if val is not None and val == 0.0:
                violations.append(f"Sahte Sıfır İhlali: {f} değeri null yerine 0.0 olarak kaydedilmiş.")

        return (len(violations) == 0), violations

    def export_opentelemetry_span(self) -> Dict[str, Any]:
        """OpenTelemetry Distributed Tracing uyumlu Span sözlüğü üretir."""
        return {
            "name": "freya_telephony_turn",
            "context": {
                "trace_id": self.session_id.replace("-", "")[:32].zfill(32),
                "span_id": self.generation_id.replace("-", "")[:16].zfill(16),
            },
            "attributes": {
                "turn.id": self.turn_id,
                "turn.generation_id": self.generation_id,
                "turn.session_id": self.session_id,
                "session.id": self.session_id,
                "turn.caller_id": self.caller_id or "unknown",
                "turn.variant": self.applied_variant,
                "turn.codec": self.codec,
                "turn.status": self.status.upper(),
                "latency.vad_start_ms": self.vad_speech_start_ms,
                "latency.asr_final_ms": self.asr_final_text_ms or self.asr_latency_ms,
                "latency.llm_first_token_ms": self.llm_first_token_ms or self.llm_ttft_ms,
                "latency.tts_first_chunk_ms": self.tts_first_chunk_ms or self.tts_ttfa_ms,
                "latency.tts_ttfa_ms": self.tts_ttfa_ms or self.tts_first_chunk_ms,
                "latency.playback_start_ms": self.playback_start_ms,
                "latency.barge_in_stop_ms": self.barge_in_stop_ms,
                "latency.total_ms": self.total_turn_latency_ms,
                "quality.mos": self.mos_score,
                "quality.f0_mean_hz": self.f0_mean_hz,
            },
            "timestamp": self.created_at_iso,
        }


class RealtimeTurnMetricsCollector:
    """
    Çoklu Çağrı Turn-Level & Generation-Level Telemetri Toplayıcısı.
    """

    def __init__(self, max_history: int = 1000):
        self._lock = threading.Lock()
        self.metrics_history: collections.deque[RealtimeTurnMetrics] = collections.deque(maxlen=max_history)
        self.active_turns: Dict[str, RealtimeTurnMetrics] = {}

    def start_turn(
        self,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        generation_id: Optional[str] = None,
        caller_id: Optional[str] = None,
        applied_variant: str = "variant_b",
        codec: str = "pcm_48k",
        **kwargs,
    ) -> RealtimeTurnMetrics:
        """Yeni bir konuşma sırası (turn) için telemetri kaydı başlatır."""
        turn_idx = len(self.metrics_history) + len(self.active_turns) + 1

        # Eğer ilk argüman turn_id olarak verilmişse
        if session_id and session_id.startswith("turn_") and not turn_id:
            turn_id = session_id
            session_id = None

        t_id = turn_id or kwargs.get("turn_id") or f"turn_{int(time.time()*1000)}_{turn_idx:04d}"
        g_id = generation_id or kwargs.get("generation_id") or f"gen_{int(time.time()*1000)}_{turn_idx:04d}"
        s_id = session_id or kwargs.get("session_id") or f"sess_{int(time.time()*1000)}_{turn_idx:04d}"

        record = RealtimeTurnMetrics(
            turn_id=t_id,
            generation_id=g_id,
            session_id=s_id,
            caller_id=caller_id,
            applied_variant=applied_variant,
            codec=codec,
        )

        with self._lock:
            self.active_turns[t_id] = record
        return record

    def record_latency(self, turn_id: str, metric_name: str, duration_ms: float) -> bool:
        """
        Gecikme metriğini kaydeder.
        Sahte sıfır kuralı: duration_ms <= 0 ise kaydedilmez.
        """
        if duration_ms <= 0:
            return False

        with self._lock:
            turn = self.active_turns.get(turn_id)
            if not turn:
                return False

            if hasattr(turn, metric_name):
                setattr(turn, metric_name, round(float(duration_ms), 2))
                return True
        return False

    def record_generation(
        self,
        turn_id: str,
        chunk_index: int,
        generation_ms: float,
        audio_duration_sec: float,
        rtf: float,
        tokens_count: int,
    ) -> bool:
        """Generation chunk metriklerini kaydeder ve ortalama RTF günceller."""
        with self._lock:
            turn = self.active_turns.get(turn_id)
            if not turn:
                return False
            chunk_data = {
                "chunk_index": chunk_index,
                "generation_ms": round(float(generation_ms), 2),
                "audio_duration_sec": round(float(audio_duration_sec), 3),
                "rtf": round(float(rtf), 3),
                "tokens_count": tokens_count,
            }
            turn.generation_chunks.append(chunk_data)
            all_rtfs = [c["rtf"] for c in turn.generation_chunks]
            turn.avg_rtf = round(float(np.mean(all_rtfs)), 3)
            return True

    def finish_turn(
        self,
        turn_id: str,
        total_latency_ms: Optional[float] = None,
        status: str = "completed",
        mos_score: Optional[float] = None,
        f0_mean_hz: Optional[float] = None,
    ) -> Optional[RealtimeTurnMetrics]:
        """Konuşma sırasını tamamlar ve geçmişe aktarır."""
        with self._lock:
            turn = self.active_turns.pop(turn_id, None)
            if not turn:
                return None

            turn.status = status
            if total_latency_ms is not None:
                turn.total_turn_latency_ms = round(float(total_latency_ms), 2)
            if mos_score is not None:
                turn.mos_score = round(float(mos_score), 2)
            if f0_mean_hz is not None:
                turn.f0_mean_hz = round(float(f0_mean_hz), 1)

            # Toplam latans hesabı (vad_speech_end -> playback_start)
            if turn.total_turn_latency_ms is None and turn.playback_start_ms is not None and turn.vad_speech_end_ms is not None:
                turn.total_turn_latency_ms = round(turn.playback_start_ms - turn.vad_speech_end_ms, 2)

            self.metrics_history.append(turn)
            return turn

    def get_turn(self, turn_id: str) -> Optional[RealtimeTurnMetrics]:
        """turn_id ile aktif veya geçmiş telemetriyi döner."""
        with self._lock:
            if turn_id in self.active_turns:
                return self.active_turns[turn_id]
            for t in reversed(self.metrics_history):
                if t.turn_id == turn_id:
                    return t
        return None

    def export_opentelemetry_span(self, turn_id: str) -> Optional[Dict[str, Any]]:
        """turn_id için OpenTelemetry Trace Span döner."""
        turn = self.get_turn(turn_id)
        if not turn:
            return None
        return turn.export_opentelemetry_span()

    def get_recent_metrics(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Son kayıtları döner."""
        with self._lock:
            turns = list(self.metrics_history)[-limit:]
        return [t.model_dump() for t in turns]


# ============================================================================
# 2. RT-10 & HLS-07: Operatör Canlı Devralma Paneli (Live Takeover Panel)
# ============================================================================

class OperatorCallState(str, Enum):
    AI_HANDLING = "AI_HANDLING"        # Yapay zekâ görüşmeyi yönetiyor
    TAKEN_OVER = "TAKEN_OVER"          # İnsan operatör devraldı (AI susturuldu)
    WHISPERING = "WHISPERING"          # Operatör asistana fısıldıyor (müşteri duymaz)
    RELEASED = "RELEASED"              # Operatör AI'a geri devretti
    TERMINATED = "TERMINATED"          # Görüşme sonlandırıldı


@dataclass
class OperatorSessionView:
    session_id: str
    caller_id: str
    state: OperatorCallState
    operator_id: Optional[str]
    takeover_reason: Optional[str]
    started_at_iso: str
    current_turn_id: Optional[str]
    # Ölçülmemişse None: sahte varsayılan (4.3 / 0.18) gösterilmez.
    mos_score: Optional[float]
    packet_loss_pct: float
    rtf: Optional[float]
    whisper_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "caller_id": self.caller_id,
            "state": self.state.value,
            "operator_id": self.operator_id,
            "takeover_reason": self.takeover_reason,
            "started_at_iso": self.started_at_iso,
            "current_turn_id": self.current_turn_id,
            "mos_score": self.mos_score,
            "packet_loss_pct": self.packet_loss_pct,
            "rtf": self.rtf,
            "whisper_notes": self.whisper_notes,
        }


class OperatorRealtimePanel:
    """
    Canlı Operatör Devralma (Takeover) ve Koçluk Paneli (RT-10, HLS-07).
    - Canlı çağrıları listeler ve SLA durumunu gösterir.
    - Tek tuşla yapay zekayı susturup çağrıyı operatöre aktarır (takeover_call).
    - Müşterinin duymadığı fısıltı koçluğu modunu yönetir (whisper_to_agent).
    - Görüşmeyi yapay zekaya geri teslim eder (release_call).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.sessions: Dict[str, OperatorSessionView] = {}

    def register_call(
        self,
        session_id: str,
        caller_id: str,
        initial_turn_id: Optional[str] = None,
        mos_score: Optional[float] = None,
        rtf: Optional[float] = None,
    ) -> OperatorSessionView:
        """Yeni aktif çağrıyı operatör paneline kaydeder."""
        session = OperatorSessionView(
            session_id=session_id,
            caller_id=caller_id,
            state=OperatorCallState.AI_HANDLING,
            operator_id=None,
            takeover_reason=None,
            started_at_iso=datetime.now(timezone.utc).isoformat(),
            current_turn_id=initial_turn_id,
            mos_score=mos_score,
            packet_loss_pct=0.1,
            rtf=rtf,
        )
        with self._lock:
            self.sessions[session_id] = session
        return session

    def takeover_call(
        self,
        session_id: str,
        operator_id: str,
        reason: str = "customer_request",
    ) -> Dict[str, Any]:
        """
        Operatör tek tuşla müdahale eder:
        1. AI derhal susturulur (Beş Kesim Barge-In tetiklenir).
        2. Ses köprüsü operatöre yönlendirilir.
        """
        with self._lock:
            sess = self.sessions.get(session_id)
            if not sess:
                return {"success": False, "error": f"Çağrı bulunamadı: {session_id}"}

            sess.state = OperatorCallState.TAKEN_OVER
            sess.operator_id = operator_id
            sess.takeover_reason = reason
            logger.info(f"[Takeover] Çağrı {session_id} operatör {operator_id} tarafından devralındı ({reason})")

            return {
                "success": True,
                "session_id": session_id,
                "state": sess.state.value,
                "operator_id": operator_id,
                "action": "ai_muted_operator_bridged",
            }

    def whisper_to_agent(
        self,
        session_id: str,
        operator_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """Operatör AI asistana fısıldar; müşteri bu sesi duymaz."""
        with self._lock:
            sess = self.sessions.get(session_id)
            if not sess:
                return {"success": False, "error": f"Çağrı bulunamadı: {session_id}"}

            sess.whisper_notes.append(f"[{operator_id}]: {message}")
            if sess.state != OperatorCallState.TAKEN_OVER:
                sess.state = OperatorCallState.WHISPERING

            return {
                "success": True,
                "session_id": session_id,
                "whisper_delivered": True,
                "notes_count": len(sess.whisper_notes),
            }

    def release_call(self, session_id: str, operator_id: str) -> Dict[str, Any]:
        """Operatör çağrıyı tekrar yapay zekâya devreder."""
        with self._lock:
            sess = self.sessions.get(session_id)
            if not sess:
                return {"success": False, "error": f"Çağrı bulunamadı: {session_id}"}

            sess.state = OperatorCallState.AI_HANDLING
            sess.operator_id = None
            logger.info(f"[Release] Çağrı {session_id} operatör tarafından tekrar AI'a devredildi")

            return {
                "success": True,
                "session_id": session_id,
                "state": sess.state.value,
                "action": "ai_resumed",
            }

    def terminate_call(self, session_id: str) -> None:
        """Görüşme sonlandığında panelden kaldırır veya durumunu günceller."""
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id].state = OperatorCallState.TERMINATED

    def get_live_sessions(self) -> List[Dict[str, Any]]:
        """Aktif çağrı listesini döner."""
        with self._lock:
            return [s.to_dict() for s in self.sessions.values() if s.state != OperatorCallState.TERMINATED]


# ============================================================================
# 3. HLS-08: Üçlü Varyant Değerlendirmesi (A/B/C Testi & Kalite Kapısı 5)
# ============================================================================

class VariantType(str, Enum):
    VARIANT_A = "variant_a"  # Orijinal FreyaTTS-small (LEYLA_SEED = 9, varsayılan normalizasyon)
    VARIANT_B = "variant_b"  # FreyaTTS-small + Ajan 1 & Ajan 2 (Sözlük + Normalizer + Prozodi)
    VARIANT_C = "variant_c"  # Varyant B + Ajan 6 (Cross-Attention LoRA uyarlanmış model)


class CodecType(str, Enum):
    PCM_48K = "pcm_48k"          # 48 kHz yerel stüdyo WAV kalitesi
    G711_ALAW = "g711_alaw"      # 8 kHz PSTN A-law telefon sıkıştırması
    G711_ULAW = "g711_ulaw"      # 8 kHz PSTN μ-law telefon sıkıştırması
    G722 = "g722"                # 16 kHz geniş bant VoIP


class ABCTripleVariantEvaluator:
    """
    Üçlü Varyant A/B/C Kalite Değerlendirme Motoru (HLS-08).

    Bu sınıf ses üretmez. Metin normalizasyonunun WER/CER değerini ölçer: Varyant A ham
    metni, Varyant B normalizer çıktısını beklenen okunuşla karşılaştırır. Gerçek ses
    ölçümü scripts/acoustic_benchmark.py ile üretilir ve rapor olarak Varyant B'ye işlenir.
    Rapor yoksa ses metrikleri None kalır. Varyant C için LoRA adaptörü bulunmadığından
    hiçbir değer üretilmez. Kalite Kapısı 5, ölçülmemiş kriter varken PASS veremez.
    """

    CRITICAL_AUTOMOTIVE_KEYWORDS = [
        "peugeot", "renault", "volkswagen", "tsi", "tdi", "ecoboost", "puretech",
        "suv", "c-suv", "wltp", "bmw", "mercedes", "togg", "dacia", "cupra",
    ]

    def __init__(self, target_f0_hz: float = 220.0, f0_tolerance_hz: float = 2.3):
        self.target_f0_hz = target_f0_hz
        self.f0_tolerance_hz = f0_tolerance_hz

    @staticmethod
    def compute_levenshtein_distance(seq1: List[str], seq2: List[str]) -> int:
        """Deterministik ve ultra-hızlı 2B Levenshtein düzenleme mesafesi."""
        n, m = len(seq1), len(seq2)
        if n == 0:
            return m
        if m == 0:
            return n

        dp = list(range(m + 1))
        for i in range(1, n + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, m + 1):
                temp = dp[j]
                cost = 0 if seq1[i - 1] == seq2[j - 1] else 1
                dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
                prev = temp
        return dp[m]

    def compute_wer_cer(self, reference: str, hypothesis: str) -> Dict[str, float]:
        """Kelime (WER) ve Karakter (CER) Hata Oranlarını hesaplar."""
        ref_words = reference.strip().lower().split()
        hyp_words = hypothesis.strip().lower().split()

        ref_chars = list(reference.strip().lower().replace(" ", ""))
        hyp_chars = list(hypothesis.strip().lower().replace(" ", ""))

        w_dist = self.compute_levenshtein_distance(ref_words, hyp_words)
        w_len = max(1, len(ref_words))
        wer = round(min(1.0, w_dist / w_len), 4)

        c_dist = self.compute_levenshtein_distance(ref_chars, hyp_chars)
        c_len = max(1, len(ref_chars))
        cer = round(min(1.0, c_dist / c_len), 4)

        return {"wer": wer, "cer": cer, "word_errors": w_dist, "char_errors": c_dist}

    def compute_itu_mos(self, codec: CodecType, rtf: float, packet_loss_pct: float = 0.0) -> float:
        """ITU-T G.107 standardına göre codec ve performansa dayalı MOS skoru."""
        base_r = {
            CodecType.PCM_48K: 94.0,
            CodecType.G722: 92.0,
            CodecType.G711_ALAW: 85.0,
            CodecType.G711_ULAW: 85.0,
        }.get(codec, 85.0)

        # Paket kaybı ve yüksek RTF cezası
        r = base_r - (packet_loss_pct * 7.5)
        if rtf > 0.5:
            r -= (rtf - 0.5) * 15.0

        r = max(0.0, min(100.0, r))
        mos = 1.0 + (0.035 * r) + (r * (r - 60.0) * (100.0 - r) * 7.0e-6)
        return round(float(np.clip(mos, 1.0, 4.5)), 2)

    def evaluate_sentence(
        self,
        raw_text: str,
        expected_spoken: str,
        variant: VariantType = VariantType.VARIANT_B,
    ) -> Dict[str, Any]:
        """Tek cümlenin metin normalizasyonunu ölçer; ses ölçümü yapılmaz, değer uydurulmaz."""
        if variant == VariantType.VARIANT_A:
            hypothesis = raw_text.lower()
        elif variant == VariantType.VARIANT_B:
            # Canlı sentezin kullandığı normalizer ölçülür; okunamayan metin tam hatadır.
            try:
                hypothesis = normalize(raw_text)["normalized"]
            except ValueError:
                hypothesis = ""
        else:
            # LoRA adaptörü metni değil sesi etkiler ve eğitilmiş adaptör yoktur.
            hypothesis = None

        errs = self.compute_wer_cer(expected_spoken, hypothesis) if hypothesis is not None else None

        return {
            "variant": variant.value,
            "raw_text": raw_text,
            "expected_spoken": expected_spoken,
            "hypothesis": hypothesis,
            "wer": errs["wer"] if errs else None,
            "cer": errs["cer"] if errs else None,
            "measured": errs is not None,
        }

    def evaluate_quality_gate(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Eşiği aşan ölçüm FAIL, ölçülmemiş kriter HOLD; yalnızca tümü geçerse PASS."""
        checks = {
            "automotive_accuracy_pct": lambda v: v >= 95.0,
            "avg_wer_pct": lambda v: v <= 30.0,
            "avg_cer_pct": lambda v: v <= 25.0,
            "speaker_embedding_abx": lambda v: v >= 0.80,
            "max_f0_drift_hz": lambda v: v <= self.f0_tolerance_hz,
        }
        missing = [name for name in checks if metrics.get(name) is None]
        failed = [
            name for name, passes in checks.items()
            if metrics.get(name) is not None and not passes(metrics[name])
        ]
        status = "FAIL" if failed else ("HOLD" if missing else "PASS")
        return {"status": status, "failed": failed, "missing": missing}

    def run_benchmark_suite(
        self,
        test_samples: List[Tuple[str, str]],
        acoustic_report: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Test cümlelerini değerlendirir; özet yalnızca ölçümlerden oluşur."""
        summary: Dict[str, Any] = {}
        for variant in VariantType:
            results = [
                result
                for raw, expected in test_samples
                if (result := self.evaluate_sentence(raw, expected, variant=variant))["measured"]
            ]
            summary[variant.value] = {
                "sample_count": len(results),
                "avg_wer_pct": round(float(np.mean([r["wer"] for r in results])) * 100.0, 2) if results else None,
                "avg_cer_pct": round(float(np.mean([r["cer"] for r in results])) * 100.0, 2) if results else None,
                "avg_mos": None,
                "speaker_embedding_abx": None,
                "automotive_accuracy_pct": None,
                "max_f0_drift_hz": None,
            }

        variant_b = summary[VariantType.VARIANT_B.value]
        variant_b["text_wer_pct"] = variant_b["avg_wer_pct"]
        variant_b["text_cer_pct"] = variant_b["avg_cer_pct"]
        acoustic_summary = None
        if acoustic_report:
            channel = acoustic_report["channels"][acoustic_report["gate_channel"]]
            variant_b.update(
                sample_count=channel["sample_count"],
                avg_wer_pct=channel["avg_wer_pct"],
                avg_cer_pct=channel["avg_cer_pct"],
                automotive_accuracy_pct=channel["automotive_accuracy_pct"],
                max_f0_drift_hz=acoustic_report["f0"]["max_drift_from_baseline_hz"],
            )
            acoustic_summary = {
                "measured_at": acoustic_report["measured_at"],
                "channel": acoustic_report["gate_channel"],
                "sample_count": acoustic_report["sample_count"],
                "failed_synthesis": acoustic_report["failed_synthesis"],
                "rtf_avg": acoustic_report["tts"]["rtf_avg"],
                "f0_median_hz": acoustic_report["f0"]["median_hz"],
                "has_f0_baseline": acoustic_report["f0"]["baseline_measured_at"] is not None,
                "terms_missed": channel["terms_missed"],
                "stt_model": acoustic_report["provenance"].get("stt_model"),
            }

        gate = self.evaluate_quality_gate(variant_b)

        return {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_scope": "audio_roundtrip" if acoustic_report else "text_normalization_only",
            "acoustic_report": acoustic_summary,
            "total_sentences": len(test_samples),
            "variant_summaries": summary,
            "quality_gate_5_status": gate["status"],
            "quality_gate_failed": gate["failed"],
            "quality_gate_missing": gate["missing"],
            "quality_gate_criteria": {
                "min_automotive_accuracy_pct": 95.0,
                "max_wer_pct": 30.0,
                "max_cer_pct": 25.0,
                "min_abx_similarity": 0.80,
                "max_f0_drift_hz": self.f0_tolerance_hz,
            },
        }


# ============================================================================
# 4. M11: Fiziksel Telekomünikasyon Kabul Denetimi (HOLD Gating)
# ============================================================================

class M11HardwareAcceptanceGate:
    """
    M11 Fiziksel Donanım ve Telekomünikasyon Kabul Güvenlik Kalkanı:
    Simülasyon ortamında fiziksel donanım testi yapılmış gibi sahte PASS verilmesini önler;
    gerçek fiziksel SIP trunk/PBX kanıtı olmadan durumu katı biçimde HOLD olarak işaretler.
    """

    @staticmethod
    def evaluate_acceptance(
        has_physical_pbx_trace: bool = False,
        has_hardware_trunk: bool = False,
        evidence_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        M11 Kabul Denetimi:
        Fiziksel kanıtlar mevcut değilse sistem fail-closed olarak HOLD döner.
        """
        evidence = evidence_files or []
        is_physical = has_physical_pbx_trace and has_hardware_trunk and len(evidence) > 0

        if not is_physical:
            return {
                "overall_status": "HOLD",
                "physical_acceptance_verified": False,
                "environment": "ENVIRONMENT_SIMULATED",
                "reason": "M11 fiziksel PBX trace veya fiziksel SIP trunk donanım kanıtı doğrulanmadı (HOLD zorunludur).",
                "required_for_pass": [
                    "Fiziksel Asterisk ARI / chan_websocket pcap kaydı",
                    "Fiziksel SIP trunk çağrı sonlandırma kanıtı",
                    "Doğrulanmış telekomünikasyon hash imzası",
                ],
            }

        return {
            "overall_status": "PASS",
            "physical_acceptance_verified": True,
            "environment": "ENVIRONMENT_PHYSICAL_HARDWARE",
            "evidence_count": len(evidence),
            "reason": "M11 fiziksel donanım ve çağrı kabul kriterleri sağlandı.",
        }


# Tekil örnekler
realtime_turn_collector = RealtimeTurnMetricsCollector()
operator_panel = OperatorRealtimePanel()
abc_evaluator = ABCTripleVariantEvaluator()
m11_gate = M11HardwareAcceptanceGate()

__all__ = [
    "RealtimeTurnMetrics",
    "RealtimeTurnMetricsCollector",
    "OperatorCallState",
    "OperatorSessionView",
    "OperatorRealtimePanel",
    "VariantType",
    "CodecType",
    "ABCTripleVariantEvaluator",
    "M11HardwareAcceptanceGate",
    "realtime_turn_collector",
    "operator_panel",
    "abc_evaluator",
    "m11_gate",
]
