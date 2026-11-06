"""Ortak bağımlılıklar: kimlik doğrulama, satır dönüştürücüler, yardımcılar."""

import secrets
from fastapi import (
    HTTPException,
    Depends,
)
from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
)
from backend.config import settings
from backend.security_utils import (
    MAX_AUDIO_BYTES,
    b64_max_chars,
)


security = HTTPBasic()
optional_security = HTTPBasic(auto_error=False)
# Base64 ses alanları için üst sınır (25 MB ham ses).
AUDIO_B64_MAX = b64_max_chars(MAX_AUDIO_BYTES)


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not settings.admin_password:
        raise HTTPException(503, "ADMIN_PASSWORD ayarlanmalı")
    if not (
        secrets.compare_digest(credentials.username.encode(), b"admin")
        and secrets.compare_digest(
            credentials.password.encode(), settings.admin_password.encode()
        )
    ):
        raise HTTPException(
            401, "Geçersiz giriş", headers={"WWW-Authenticate": "Basic"}
        )


def row(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def call_analytics_row(obj):
    """csat_score sütunu anahtar kelime tahminidir: API'de tahmin olarak etiketlenir."""
    d = row(obj)
    d["estimated_sentiment_score"] = d.pop("csat_score", None)
    d["csat_is_estimate"] = True
    return d
