"""Güvenlik yardımcıları: imzalı müşteri bağlantıları ve sınırlı gövde okuma."""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, UploadFile

from backend.config import settings

# İmzalı bağlantıların varsayılan geçerlilik süresi: 7 gün.
LINK_TTL_SEC = 7 * 24 * 3600

# Yükleme sınırları (bayt).
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _link_signature(resource_id: str, exp: int) -> str:
    key = settings.link_signing_key.encode("utf-8")
    return hmac.new(key, f"{resource_id}:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()


def signed_pdf_path(report_id: str, ttl_sec: int = LINK_TTL_SEC) -> str:
    """Rapor PDF'i için imzalı göreli URL üretir. Anahtar boşsa imzalı erişim kapalıdır."""
    if not settings.link_signing_key:
        raise HTTPException(503, "LINK_SIGNING_KEY ayarlanmalı")
    exp = int(time.time()) + ttl_sec
    sig = _link_signature(report_id, exp)
    return f"/api/inspections/{report_id}/pdf?exp={exp}&sig={sig}"


def verify_signed_link(resource_id: str, exp: str | None, sig: str | None) -> bool:
    """İmza geçerli ve süre dolmamışsa True. Boş anahtarda her zaman False."""
    if not settings.link_signing_key or not exp or not sig:
        return False
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_int < int(time.time()):
        return False
    return hmac.compare_digest(_link_signature(resource_id, exp_int), sig)


async def read_upload_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Yüklemeyi parça parça okur; sınır aşılırsa tamamını belleğe almadan 413 döner."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413, f"Dosya boyutu {max_bytes // (1024 * 1024)} MB sınırını aşamaz"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def b64_max_chars(max_bytes: int) -> int:
    """Verilen ham bayt sınırına karşılık gelen en fazla base64 karakter sayısı."""
    return ((max_bytes + 2) // 3) * 4
