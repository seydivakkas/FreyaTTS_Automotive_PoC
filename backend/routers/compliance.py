# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Uyumluluk uç noktaları: KVKK ve ses arşivi."""

import io
import json
import soundfile as sf
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import Optional
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Query,
    Response,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse
from backend.security_utils import (
    MAX_AUDIO_BYTES,
    read_upload_capped,
)
from backend.config import settings
from backend.db import AudioArchive, KVKKErasureRequest
from backend.audio_archive_compliance import (
    ArchiveKeyMissingError,
    audio_archive_engine,
)
from backend.redaction_kvkk_guard import (
    default_kvkk_guard,
    is_valid_luhn,
    is_valid_tckn,
    mask_credit_card,
    mask_tckn,
    redact_audio,
    redact_text,
)
from backend.kvkk_compliance import (
    audit_transcript_retention,
    create_erasure_request,
    execute_erasure,
    generate_certificate_text,
    purge_expired_transcripts,
)
from backend import db as db_module
from backend.schemas import (
    ArchiveCallIn,
    ArchivePurgeIn,
    CardValidateIn,
    KVKKErasureRequestIn,
    KVKKErasureExecuteIn,
    KVKKRedactIn,
    TCKNValidateIn,
    TranscriptRetentionPurgeIn,
)
from backend.deps import auth

router = APIRouter()


@router.post("/api/kvkk/redact-text", dependencies=[Depends(auth)])
def kvkk_redact_text_endpoint(body: KVKKRedactIn):
    cats = set(body.categories) if body.categories else None
    res = redact_text(
        body.text,
        categories=cats,
        mask_char=body.mask_char,
        validate_strict=body.validate_strict,
    )
    return {
        "original_text": res.original_text,
        "redacted_text": res.redacted_text,
        "entities": res.entities,
        "redaction_count": res.redaction_count,
    }


@router.post("/api/kvkk/validate-tckn", dependencies=[Depends(auth)])
def kvkk_validate_tckn_endpoint(body: TCKNValidateIn):
    valid = is_valid_tckn(body.tckn)
    masked = mask_tckn(body.tckn)
    return {
        "tckn": body.tckn,
        "is_valid": valid,
        "masked": masked,
    }


@router.post("/api/kvkk/validate-card", dependencies=[Depends(auth)])
def kvkk_validate_card_endpoint(body: CardValidateIn):
    valid = is_valid_luhn(body.card_number)
    masked = mask_credit_card(body.card_number)
    return {
        "card_number": body.card_number,
        "is_valid": valid,
        "masked": masked,
    }


@router.get("/api/kvkk/policy", dependencies=[Depends(auth)])
def kvkk_get_policy_endpoint():
    return {
        "enabled_categories": list(default_kvkk_guard.enabled_categories),
        "mask_char": default_kvkk_guard.mask_char,
        "validate_strict": default_kvkk_guard.validate_strict,
        "beep_freq_hz": default_kvkk_guard.beep_freq_hz,
        "supported_pii": [
            "tckn",
            "credit_card",
            "cvv",
            "expiry",
            "phone",
            "email",
            "iban",
            "spoken_numbers",
        ],
    }


@router.post("/api/kvkk/redact-audio", dependencies=[Depends(auth)])
async def kvkk_redact_audio_endpoint(
    file: UploadFile = File(...),
    ranges_json: str = Form("[]"),
    mode: str = Form("beep"),
):
    content = await read_upload_capped(file, MAX_AUDIO_BYTES)
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    try:
        ranges_data = json.loads(ranges_json)
    except Exception:
        ranges_data = []

    time_ranges = []
    for item in ranges_data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            time_ranges.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict) and "start_sec" in item and "end_sec" in item:
            time_ranges.append((float(item["start_sec"]), float(item["end_sec"])))

    audio_arr, sr = sf.read(io.BytesIO(content), dtype="float32")
    if audio_arr.ndim > 1:
        audio_arr = audio_arr.mean(axis=1)

    redacted = redact_audio(audio_arr, sr, time_ranges, mode=mode)
    out_buf = io.BytesIO()
    sf.write(out_buf, redacted, sr, format="WAV", subtype="PCM_16")
    out_buf.seek(0)

    return Response(content=out_buf.read(), media_type="audio/wav")


@router.post("/api/archive/call-session", dependencies=[Depends(auth)])
def archive_call_endpoint(payload: ArchiveCallIn):
    import base64

    try:
        raw_pcm = base64.b64decode(payload.audio_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")
    if len(raw_pcm) == 0:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    with db_module.Session() as db:
        try:
            res = audio_archive_engine.archive_call_session(
                audio=raw_pcm,
                sample_rate=payload.sample_rate,
                conversation_id=payload.conversation_id,
                call_session_id=payload.call_session_id,
                caller_phone=payload.caller_phone,
                codec=payload.codec,
                is_redacted=payload.is_redacted,
                retention_years=payload.retention_years,
                db=db,
            )
        except ArchiveKeyMissingError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return res.to_dict()


@router.get("/api/archive/retention-audit", dependencies=[Depends(auth)])
def retention_audit_endpoint():
    with db_module.Session() as db:
        return audio_archive_engine.audit_retention_compliance(db=db)


@router.post("/api/archive/retention-purge", dependencies=[Depends(auth)])
def retention_purge_endpoint(payload: ArchivePurgeIn):
    target_dt = None
    if payload.target_date:
        try:
            target_dt = datetime.fromisoformat(payload.target_date)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid target_date format: {e}")
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
        # Gelecek tarih yasal saklama süresini atlatır; reddedilir.
        if target_dt > datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="target_date gelecekte olamaz")

    with db_module.Session() as db:
        return audio_archive_engine.purge_expired_archives(
            db=db,
            dry_run=payload.dry_run,
            target_date=target_dt,
        )


@router.get("/api/archive/{archive_id}/verify", dependencies=[Depends(auth)])
def verify_archive_endpoint(archive_id: str):
    with db_module.Session() as db:
        try:
            res = audio_archive_engine.verify_archive_integrity(archive_id=archive_id, db=db)
        except ArchiveKeyMissingError as e:
            raise HTTPException(status_code=503, detail=str(e))
        if res.status == "missing":
            raise HTTPException(status_code=404, detail="Archive not found on disk or DB")
        return res.to_dict()


@router.get("/api/archive/{archive_id}/download", dependencies=[Depends(auth)])
def download_archive_endpoint(archive_id: str):
    with db_module.Session() as db:
        record = db.get(AudioArchive, archive_id)
        if not record:
            raise HTTPException(status_code=404, detail="Archive record not found")
        path = Path(record.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Archive file missing from storage")
        media_type = "audio/ogg" if record.codec == "opus" else "audio/wav"
        return FileResponse(
            path=str(path),
            media_type=media_type,
            filename=path.name,
            headers={
                "X-Freya-SHA256": record.sha256_hash,
                "X-Freya-HMAC": record.hmac_signature,
                "X-Freya-Codec": record.codec,
                "X-Freya-Retention-Expires": record.expires_at or "",
            },
        )


# =========================================================================
# KVKK TRANSKRİPT SAKLAMA SÜRESİ VE SİLME TALEBİ UÇ NOKTALARI
# =========================================================================


@router.get("/api/kvkk/transcript-retention-audit", dependencies=[Depends(auth)])
def kvkk_transcript_retention_audit_endpoint(retention_days: Optional[int] = None):
    """Transkript saklama süresi durumunu denetler ve özetler."""
    with db_module.Session() as db:
        return audit_transcript_retention(db=db, retention_days=retention_days)


@router.post("/api/kvkk/transcript-retention-purge", dependencies=[Depends(auth)])
def kvkk_transcript_retention_purge_endpoint(payload: TranscriptRetentionPurgeIn):
    """Süresi dolmuş konuşma transkriptlerini anonimleştirir/imha eder."""
    if not payload.dry_run and not settings.kvkk_erasure_enabled:
        raise HTTPException(403, "KVKK silme işlemleri kapalı.")
    target_dt = None
    if payload.target_date:
        try:
            target_dt = datetime.fromisoformat(payload.target_date)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Geçersiz target_date formatı: {e}")
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=timezone.utc)
        if target_dt > datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="target_date gelecekte bir tarih olamaz")

    with db_module.Session() as db:
        return purge_expired_transcripts(
            db=db,
            dry_run=payload.dry_run,
            retention_days=payload.retention_days,
            target_date=target_dt,
        )


@router.post("/api/kvkk/erasure-requests", dependencies=[Depends(auth)])
def kvkk_create_erasure_request_endpoint(payload: KVKKErasureRequestIn):
    """KVKK Madde 11 uyarınca yeni bir veri silme (unutulma) talebi kaydeder."""
    if not settings.kvkk_erasure_enabled:
        raise HTTPException(403, "KVKK silme işlemleri kapalı.")
    with db_module.Session() as db:
        req = create_erasure_request(db=db, payload=payload, requester="admin")
        impact = json.loads(req.impact_summary_json) if req.impact_summary_json else {}
        return {
            "id": req.id,
            "identifier_type": req.identifier_type,
            "identifier_value": req.identifier_value,
            "requester_name": req.requester_name,
            "reason": req.reason,
            "status": req.status,
            "notes": req.notes,
            "created_at": req.created_at,
            "impact_summary": impact,
        }


@router.get("/api/kvkk/erasure-requests", dependencies=[Depends(auth)])
def kvkk_list_erasure_requests_endpoint(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Kayıtlı KVKK veri silme taleplerini listeler."""
    with db_module.Session() as db:
        q = db.query(KVKKErasureRequest)
        if status:
            q = q.filter(KVKKErasureRequest.status == status)
        items = q.order_by(KVKKErasureRequest.created_at.desc()).limit(limit).all()

        results = []
        for it in items:
            try:
                impact = json.loads(it.impact_summary_json)
            except Exception:
                impact = {}
            results.append(
                {
                    "id": it.id,
                    "identifier_type": it.identifier_type,
                    "identifier_value": it.identifier_value,
                    "requester_name": it.requester_name,
                    "reason": it.reason,
                    "status": it.status,
                    "certificate_sha256": it.certificate_sha256,
                    "notes": it.notes,
                    "created_at": it.created_at,
                    "executed_at": it.executed_at,
                    "executed_by": it.executed_by,
                    "impact_summary": impact,
                }
            )
        return results


@router.get("/api/kvkk/erasure-requests/{request_id}", dependencies=[Depends(auth)])
def kvkk_get_erasure_request_endpoint(request_id: str):
    """Tek bir silme talebinin detayını ve etki özetini döner."""
    with db_module.Session() as db:
        req = db.get(KVKKErasureRequest, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Silme talebi bulunamadı")
        try:
            impact = json.loads(req.impact_summary_json)
        except Exception:
            impact = {}
        return {
            "id": req.id,
            "identifier_type": req.identifier_type,
            "identifier_value": req.identifier_value,
            "requester_name": req.requester_name,
            "reason": req.reason,
            "status": req.status,
            "certificate_sha256": req.certificate_sha256,
            "notes": req.notes,
            "created_at": req.created_at,
            "executed_at": req.executed_at,
            "executed_by": req.executed_by,
            "impact_summary": impact,
        }


@router.post("/api/kvkk/erasure-requests/{request_id}/execute", dependencies=[Depends(auth)])
def kvkk_execute_erasure_request_endpoint(request_id: str, payload: KVKKErasureExecuteIn):
    """KVKK veri silme talebini icra eder: kayıtları anonimleştirir/siler ve SHA-256 özeti üretir."""
    if not settings.kvkk_erasure_enabled:
        raise HTTPException(403, "KVKK silme işlemleri kapalı.")
    with db_module.Session() as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        req = db.get(KVKKErasureRequest, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Silme talebi bulunamadı")
        if req.status == "executed":
            raise HTTPException(
                status_code=409,
                detail=f"Bu talep zaten {req.executed_at} tarihinde icra edilmiştir. (İmha SHA-256: {req.certificate_sha256})",
            )
        try:
            return execute_erasure(db=db, request=req, executed_by="admin",
                                   confirmed_record_count=payload.confirmed_record_count)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "Ses dosyası silinemedi. Silme işlemi kaydedilmedi.") from exc


@router.get("/api/kvkk/erasure-requests/{request_id}/certificate", dependencies=[Depends(auth)])
def kvkk_get_certificate_endpoint(request_id: str, format: str = "json"):
    """İcra edilmiş bir silme talebinin uygulama işlem kaydını döner."""
    with db_module.Session() as db:
        req = db.get(KVKKErasureRequest, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Silme talebi bulunamadı")
        if req.status != "executed":
            raise HTTPException(
                status_code=400,
                detail="Bu talep henüz icra edilmediği için imha tutanağı oluşturulmamıştır.",
            )
        cert_text = generate_certificate_text(req)
        if format == "text":
            return Response(content=cert_text, media_type="text/plain; charset=utf-8")
        return {
            "request_id": req.id,
            "identifier_type": req.identifier_type,
            "executed_at": req.executed_at,
            "executed_by": req.executed_by,
            "certificate_sha256": req.certificate_sha256,
            "certificate_text": cert_text,
        }

