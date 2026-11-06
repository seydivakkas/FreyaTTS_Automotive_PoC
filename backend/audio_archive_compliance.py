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

import hashlib
import hmac
import io
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import AudioArchive

logger = logging.getLogger("audio_archive_compliance")

DEFAULT_ARCHIVE_DIR = settings.data_dir / "audio_archives"
DEFAULT_RETENTION_YEARS = 2
DEFAULT_RETENTION_DAYS = 730


class ArchiveKeyMissingError(RuntimeError):
    """Arşiv HMAC anahtarı (AUDIO_ARCHIVE_MASTER_KEY) ayarlı değil; işlem güvenli şekilde reddedilir."""


class ArchiveCodec(str, Enum):
    OPUS = "opus"
    GSM_FR = "gsm_fr"
    RAW_WAV = "raw_wav"


@dataclass
class ArchiveResult:
    archive_id: str
    conversation_id: Optional[str]
    call_session_id: str
    caller_phone: str
    codec: str
    channels: int
    sample_rate: int
    duration_sec: float
    raw_size_bytes: int
    compressed_size_bytes: int
    compression_ratio_percent: float
    space_saved_bytes: int
    raw_sha256: str
    archive_sha256: str
    hmac_signature: str
    file_path: str
    retention_years: int
    created_at: str
    expires_at: str
    is_redacted: bool
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    archive_id: str
    is_valid: bool
    expected_sha256: str
    actual_sha256: str
    hmac_valid: bool
    file_exists: bool
    status: str
    checked_at: str
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_sha256(data: bytes) -> str:
    """Verilen bayt dizisinin SHA-256 özetini (hex) hesaplar."""
    return hashlib.sha256(data).hexdigest()


def compute_hmac_sha256(data_hash: str, key: str) -> str:
    """SHA-256 özetini kurumsal anahtar ile mühürleyerek tahrifat denetim imzası üretir."""
    if not key:
        raise ArchiveKeyMissingError("AUDIO_ARCHIVE_MASTER_KEY ayarlanmamış")
    return hmac.new(key.encode("utf-8"), data_hash.encode("utf-8"), hashlib.sha256).hexdigest()


def calculate_retention_expiry(
    created_at: Optional[Union[datetime, str]] = None,
    years: int = DEFAULT_RETENTION_YEARS,
) -> str:
    """Yasal saklama mevzuatına göre (varsayılan 2 yıl / 730 gün) imha tarihini hesaplar."""
    if created_at is None:
        base_dt = datetime.now(timezone.utc)
    elif isinstance(created_at, str):
        try:
            base_dt = datetime.fromisoformat(created_at)
        except Exception:
            base_dt = datetime.now(timezone.utc)
    else:
        base_dt = created_at

    expiry_dt = base_dt + timedelta(days=years * 365)
    return expiry_dt.isoformat()


def align_stereo_channels(
    caller_wave: np.ndarray,
    assistant_wave: np.ndarray,
) -> np.ndarray:
    """
    Gelen müşteri sesini sol kanala, asistan Leyla sesini sağ kanala senkronize eder.
    Kısa kalan kanalı sıfırlarla doldurarak (zero-padding) eşitler.
    Çıktı shape: (N, 2)
    """
    c_len = len(caller_wave)
    a_len = len(assistant_wave)
    max_len = max(c_len, a_len)

    if max_len == 0:
        return np.zeros((0, 2), dtype=np.float32)

    left = np.zeros(max_len, dtype=np.float32)
    right = np.zeros(max_len, dtype=np.float32)

    left[:c_len] = caller_wave
    right[:a_len] = assistant_wave

    return np.column_stack([left, right])


class AudioArchiveComplianceEngine:
    """
    Yasal Saklama, GSM-FR / OPUS Sıkıştırma ve SHA-256 / HMAC Bütünlük Denetçisi.
    - 8 kHz ham telefon kayıtlarını OPUS (16 kbps) veya GSM-FR (GSM 6.10) ile sıkıştırır (%85-93 tasarruf).
    - Her arşiv için ham ses ve sıkıştırılmış sesin SHA-256 özetini ve HMAC mührünü çıkarır.
    - 2 yıllık (730 gün) yasal saklama mevzuatını denetler, süresi dolan kayıtları tasfiye eder.
    - Mono ve Çift Kanallı Stereo (Sol: Müşteri, Sağ: Leyla) arşivlemeyi destekler.
    """

    def __init__(
        self,
        archive_dir: Optional[Union[str, Path]] = None,
        master_key: Optional[str] = None,
        default_codec: str = "opus",
    ):
        self.archive_dir = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._master_key = master_key
        self.default_codec = default_codec

    @property
    def master_key(self) -> str:
        """Açıkça verilen anahtar, yoksa ayardaki anahtar; ikisi de boşsa hata verir."""
        key = self._master_key if self._master_key is not None else settings.audio_archive_master_key
        if not key:
            raise ArchiveKeyMissingError("AUDIO_ARCHIVE_MASTER_KEY ayarlanmamış")
        return key

    def compress_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = 8000,
        codec: str = "opus",
    ) -> Tuple[bytes, str]:
        """
        Ham numpy dalga formunu (mono veya stereo) hedef formata sıkıştırır.
        Döndürür: (compressed_bytes, file_extension)
        """
        c = codec.lower().strip()
        buf = io.BytesIO()

        if c == "opus":
            # OGG container içinde 16 kbps ses optimizasyonlu OPUS
            # soundfile OGG / OPUS mono veya stereo kabul eder
            sf.write(buf, audio, sample_rate, format="OGG", subtype="OPUS")
            ext = ".ogg"
        elif c in ("gsm", "gsm_fr", "gsm610"):
            # GSM 6.10 Full-Rate: Sadece Mono ve 8000 Hz desteklenir
            mono_audio = audio[:, 0] if audio.ndim > 1 else audio
            sf.write(buf, mono_audio, 8000, format="WAV", subtype="GSM610")
            ext = ".gsm.wav"
        else:
            # Fallback standart PCM_16 WAV
            sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
            ext = ".wav"

        compressed_data = buf.getvalue()
        return compressed_data, ext

    def decompress_audio(
        self,
        compressed_bytes: bytes,
    ) -> Tuple[np.ndarray, int]:
        """Sıkıştırılmış arşiv baytlarını okuyarak (waveform, sample_rate) döner."""
        buf = io.BytesIO(compressed_bytes)
        data, sr = sf.read(buf)
        return data.astype(np.float32), sr

    def archive_call_session(
        self,
        *,
        audio: Optional[Union[np.ndarray, bytes]] = None,
        sample_rate: int = 8000,
        conversation_id: Optional[str] = None,
        call_session_id: str = "",
        caller_phone: str = "",
        codec: Optional[str] = None,
        is_redacted: bool = False,
        retention_years: int = DEFAULT_RETENTION_YEARS,
        db: Optional[Session] = None,
        caller_channel: Optional[np.ndarray] = None,
        assistant_channel: Optional[np.ndarray] = None,
    ) -> ArchiveResult:
        """
        Bir çağrının sesini sıkıştırır, SHA-256 ve HMAC mührünü oluşturur,
        fiziksel diske ve SQLite veritabanına yasal saklama uyumlu olarak kaydeder.
        """
        master_key = self.master_key  # Anahtar yoksa dosya yazılmadan önce hata verir.
        active_codec = codec or self.default_codec
        now_dt = datetime.now(timezone.utc)
        created_at_str = now_dt.isoformat()
        expires_at_str = calculate_retention_expiry(now_dt, years=retention_years)
        archive_id = f"arch-{uuid.uuid4().hex[:12]}"

        # 1. Ses dalga formunu hazırla
        if caller_channel is not None and assistant_channel is not None:
            # İki kanallı senkronize stereo arşiv
            waveform = align_stereo_channels(caller_channel, assistant_channel)
            channels = 2
        elif audio is not None:
            if isinstance(audio, bytes):
                # Ham S16LE PCM baytları
                arr = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
                waveform = arr
                channels = 1
            else:
                waveform = audio.astype(np.float32)
                channels = waveform.shape[1] if waveform.ndim > 1 else 1
        else:
            raise ValueError("Arşivlenecek ses verisi (audio veya kanallar) belirtilmelidir.")

        # 2. Ham ses boyutu ve SHA-256
        # Ham S16LE eşdeğer bayt boyutu: samples * channels * 2
        total_samples = len(waveform)
        raw_size_bytes = total_samples * channels * 2
        raw_bytes_representation = np.clip(waveform * 32767.0, -32768, 32767).astype(np.int16).tobytes()
        raw_sha256 = compute_sha256(raw_bytes_representation)
        duration_sec = round(float(total_samples) / float(sample_rate), 3) if sample_rate > 0 else 0.0

        # 3. Sıkıştırma (OPUS / GSM-FR)
        compressed_bytes, ext = self.compress_audio(waveform, sample_rate=sample_rate, codec=active_codec)
        compressed_size_bytes = len(compressed_bytes)

        # Sıkıştırma tasarruf oranı
        if raw_size_bytes > 0:
            compression_ratio_pct = round(
                (1.0 - (compressed_size_bytes / raw_size_bytes)) * 100.0, 2
            )
            space_saved_bytes = max(0, raw_size_bytes - compressed_size_bytes)
        else:
            compression_ratio_pct = 0.0
            space_saved_bytes = 0

        # 4. Kriptografik Özet ve HMAC Mührü
        archive_sha256 = compute_sha256(compressed_bytes)
        hmac_sig = compute_hmac_sha256(archive_sha256, master_key)

        # 5. Dosyayı Yıl-Ay alt dizinine kaydet (Partitioning)
        month_dir = self.archive_dir / now_dt.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{archive_id}_{now_dt.strftime('%Y%m%d_%H%M%S')}{ext}"
        target_path = month_dir / filename
        target_path.write_bytes(compressed_bytes)

        # 6. Veritabanına kaydet
        if db is not None:
            archive_record = AudioArchive(
                id=archive_id,
                conversation_id=conversation_id,
                call_session_id=call_session_id or f"sess-{archive_id}",
                caller_phone=caller_phone,
                codec=active_codec,
                channels=channels,
                sample_rate=sample_rate,
                duration_sec=duration_sec,
                raw_size_bytes=raw_size_bytes,
                compressed_size_bytes=compressed_size_bytes,
                compression_ratio_percent=compression_ratio_pct,
                sha256_hash=archive_sha256,
                raw_sha256_hash=raw_sha256,
                hmac_signature=hmac_sig,
                file_path=str(target_path).replace("\\", "/"),
                retention_years=retention_years,
                expires_at=expires_at_str,
                is_redacted=is_redacted,
                status="active",
                created_at=created_at_str,
            )
            db.add(archive_record)
            db.commit()

        logger.info(
            "Ses Arşivi Oluşturuldu: %s | Codec: %s | Orijinal: %d B -> Sıkıştırılmış: %d B (Tasarruf: %%%.1f) | SHA256: %s",
            archive_id,
            active_codec,
            raw_size_bytes,
            compressed_size_bytes,
            compression_ratio_pct,
            archive_sha256[:12],
        )

        return ArchiveResult(
            archive_id=archive_id,
            conversation_id=conversation_id,
            call_session_id=call_session_id,
            caller_phone=caller_phone,
            codec=active_codec,
            channels=channels,
            sample_rate=sample_rate,
            duration_sec=duration_sec,
            raw_size_bytes=raw_size_bytes,
            compressed_size_bytes=compressed_size_bytes,
            compression_ratio_percent=compression_ratio_pct,
            space_saved_bytes=space_saved_bytes,
            raw_sha256=raw_sha256,
            archive_sha256=archive_sha256,
            hmac_signature=hmac_sig,
            file_path=str(target_path).replace("\\", "/"),
            retention_years=retention_years,
            created_at=created_at_str,
            expires_at=expires_at_str,
            is_redacted=is_redacted,
            status="active",
        )

    def verify_archive_integrity(
        self,
        archive_id: str,
        db: Optional[Session] = None,
        file_path: Optional[Union[str, Path]] = None,
        expected_sha256: Optional[str] = None,
        expected_hmac: Optional[str] = None,
    ) -> VerificationResult:
        """
        Fiziksel dosyanın SHA-256 ve HMAC mührünü yeniden hesaplayarak tahrifat denetimi yapar.
        Eğer dosya baytları değiştirilmişse veya imza uyuşmuyorsa 'tampered' uyarısı verir.
        """
        master_key = self.master_key  # Anahtar yoksa doğrulama asla başarılı dönmez.
        checked_at = datetime.now(timezone.utc).isoformat()
        target_path: Optional[Path] = None
        exp_sha = expected_sha256
        exp_hmac = expected_hmac
        db_record: Optional[AudioArchive] = None

        if db is not None:
            db_record = db.get(AudioArchive, archive_id)
            if db_record:
                target_path = Path(db_record.file_path)
                exp_sha = db_record.sha256_hash
                exp_hmac = db_record.hmac_signature

        if target_path is None and file_path:
            target_path = Path(file_path)

        if target_path is None or not target_path.exists():
            return VerificationResult(
                archive_id=archive_id,
                is_valid=False,
                expected_sha256=exp_sha or "",
                actual_sha256="",
                hmac_valid=False,
                file_exists=False,
                status="missing",
                checked_at=checked_at,
                details="Arşiv dosyası disk üzerinde bulunamadı.",
            )

        # Dosyayı oku ve SHA-256 hesapla
        file_bytes = target_path.read_bytes()
        actual_sha = compute_sha256(file_bytes)
        calculated_hmac = compute_hmac_sha256(actual_sha, master_key)

        # Beklenen özet veya imza yoksa doğrulama başarılı sayılmaz (fail closed).
        sha_matches = bool(exp_sha) and hmac.compare_digest(actual_sha, exp_sha)
        hmac_matches = bool(exp_hmac) and hmac.compare_digest(calculated_hmac, exp_hmac)
        is_valid = sha_matches and hmac_matches

        if is_valid:
            status = "verified"
            details = "Kriptografik bütünlük doğrulandı (SHA-256 ve HMAC geçerli)."
        elif not exp_sha or not exp_hmac:
            status = "unverifiable"
            details = "Beklenen SHA-256 veya HMAC kaydı yok; bütünlük doğrulanamadı."
        else:
            status = "tampered"
            details = f"Tahrifat tespit edildi! Beklenen SHA: {exp_sha}, Mevcut: {actual_sha}"

        if db_record is not None and db is not None and status != "unverifiable":
            db_record.status = status
            db.commit()

        return VerificationResult(
            archive_id=archive_id,
            is_valid=is_valid,
            expected_sha256=exp_sha or "",
            actual_sha256=actual_sha,
            hmac_valid=hmac_matches,
            file_exists=True,
            status=status,
            checked_at=checked_at,
            details=details,
        )

    def audit_retention_compliance(
        self,
        db: Session,
        target_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Veritabanındaki tüm ses arşivlerinin 2 yıllık yasal saklama durumunu denetler.
        Süresi dolan, dolmak üzere olan ve aktif arşivleri kategorize eder.
        """
        now_dt = target_date or datetime.now(timezone.utc)
        thirty_days_later = (now_dt + timedelta(days=30)).isoformat()
        now_iso = now_dt.isoformat()

        records = list(db.scalars(select(AudioArchive)).all())

        total_count = len(records)
        active_count = 0
        expiring_soon_count = 0
        expired_count = 0
        purged_count = 0

        total_raw_bytes = 0
        total_compressed_bytes = 0

        expired_list = []
        expiring_soon_list = []

        for r in records:
            total_raw_bytes += r.raw_size_bytes
            total_compressed_bytes += r.compressed_size_bytes

            if r.status == "purged":
                purged_count += 1
                continue

            exp = r.expires_at or ""
            if exp and exp <= now_iso:
                expired_count += 1
                expired_list.append(
                    {"id": r.id, "file_path": r.file_path, "expires_at": exp, "duration_sec": r.duration_sec}
                )
            elif exp and exp <= thirty_days_later:
                expiring_soon_count += 1
                expiring_soon_list.append(
                    {"id": r.id, "file_path": r.file_path, "expires_at": exp, "duration_sec": r.duration_sec}
                )
            else:
                active_count += 1

        total_saved_bytes = max(0, total_raw_bytes - total_compressed_bytes)
        overall_ratio = (
            round((total_saved_bytes / total_raw_bytes) * 100.0, 2)
            if total_raw_bytes > 0
            else 0.0
        )

        return {
            "audited_at": now_iso,
            "total_records": total_count,
            "active_count": active_count,
            "expiring_soon_count": expiring_soon_count,
            "expired_count": expired_count,
            "purged_count": purged_count,
            "total_raw_megabytes": round(total_raw_bytes / (1024 * 1024), 2),
            "total_compressed_megabytes": round(total_compressed_bytes / (1024 * 1024), 2),
            "total_saved_megabytes": round(total_saved_bytes / (1024 * 1024), 2),
            "overall_space_saved_percent": overall_ratio,
            "expired_archives": expired_list,
            "expiring_soon_archives": expiring_soon_list,
        }

    def purge_expired_archives(
        self,
        db: Session,
        dry_run: bool = True,
        target_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        2 yıllık yasal saklama süresi dolan kayıtları tasfiye eder.
        dry_run=False ise fiziksel dosyayı diskten siler ve veritabanı kaydını
        'purged' statüsüne geçirerek kriptografik tombstone (SHA-256 izi) bırakır.
        """
        real_now = datetime.now(timezone.utc)
        now_dt = target_date or real_now
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        # Gelecek tarih yasal saklama süresini atlatabilir; gerçek zamana indirilir.
        if now_dt > real_now:
            now_dt = real_now
        now_iso = now_dt.isoformat()

        stmt = select(AudioArchive).where(
            AudioArchive.expires_at <= now_iso,
            AudioArchive.status != "purged",
        )
        candidates = list(db.scalars(stmt).all())

        purged_ids: List[str] = []
        failed_ids: List[str] = []
        freed_bytes = 0

        for r in candidates:
            if not dry_run:
                # Fiziksel dosyayı sil; yalnızca silindiyse veya zaten yoksa purged işaretle
                try:
                    p = Path(r.file_path)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    logger.warning("Tasfiye edilecek dosya silinemedi: %s (%s)", r.file_path, e)
                    failed_ids.append(r.id)
                    continue

                # Durumu güncelle (kriptografik iz kalır)
                r.status = "purged"

            freed_bytes += r.compressed_size_bytes
            purged_ids.append(r.id)

        if not dry_run and candidates:
            db.commit()

        return {
            "dry_run": dry_run,
            "purged_count": len(purged_ids),
            "purged_archive_ids": purged_ids,
            "failed_archive_ids": failed_ids,
            "freed_megabytes": round(freed_bytes / (1024 * 1024), 3),
            "executed_at": now_iso,
        }


# Global Singleton Instance
audio_archive_engine = AudioArchiveComplianceEngine()

