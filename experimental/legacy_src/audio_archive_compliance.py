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

from backend.audio_archive_compliance import (
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_MASTER_KEY,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_RETENTION_YEARS,
    ArchiveCodec,
    ArchiveResult,
    AudioArchiveComplianceEngine,
    VerificationResult,
    align_stereo_channels,
    audio_archive_engine,
    calculate_retention_expiry,
    compute_hmac_sha256,
    compute_sha256,
)

__all__ = [
    "DEFAULT_ARCHIVE_DIR",
    "DEFAULT_MASTER_KEY",
    "DEFAULT_RETENTION_DAYS",
    "DEFAULT_RETENTION_YEARS",
    "ArchiveCodec",
    "ArchiveResult",
    "AudioArchiveComplianceEngine",
    "VerificationResult",
    "align_stereo_channels",
    "audio_archive_engine",
    "calculate_retention_expiry",
    "compute_hmac_sha256",
    "compute_sha256",
]

