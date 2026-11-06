"""Telefoni uç noktaları: bildirimler, giden arama, AudioSocket, aktarım, WhatsApp, çağrı analitiği."""

import io
import json
import secrets
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    WebSocket,
    UploadFile,
    File,
    Form,
    Request,
)
from sqlalchemy import select
from backend.config import settings
from backend.security_utils import (
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    read_upload_capped,
)
from backend.db import (
    NotificationOutbox,
    OutboundCall,
    OperatorTransfer,
    CallAnalytics,
)
from backend.whatsapp_webhook import (
    process_inbound_text,
    process_inbound_voice,
    process_inbound_image,
    list_whatsapp_messages,
)
from backend.post_call_analytics import (
    evaluate_and_save_call_analytics,
    get_analytics_summary_stats,
)
from backend.transfer import (
    FALLBACK_AI_PROMPT,
    initiate_operator_transfer,
    accept_operator_transfer,
    decline_operator_transfer,
    handle_operator_dtmf,
    check_transfer_timeouts,
    list_transfers,
)
from backend.notifications import (
    dispatch_pending_notifications,
    retry_notification,
)
from backend.outbound import (
    initiate_outbound_call,
    complete_outbound_call,
    cancel_outbound_call,
    get_outbound_stats,
)
from backend.outbound_dialer import (
    campaign_dialer,
    detect_turkish_amd,
    AMDResult,
)
from backend.ami import (
    get_ami_client,
    is_real_ami,
)
from backend.audiosocket_server import (
    orchestrator,
    TwoStageBargeInController,
)
from backend.websocket_adapter import chan_ws_adapter
from backend import db as db_module
from backend.schemas import (
    AMDAnalyzeIn,
    AMDEvaluateCallIn,
    CallAnalyticsIn,
    CallOutcomeIn,
    CampaignDialIn,
    OutboundCallIn,
    SimulateBargeInIn,
    TransferAcceptIn,
    TransferDTMFIn,
    TransferDeclineIn,
    TransferInitiateIn,
    WhatsAppInboundIn,
)
from backend.deps import (
    auth,
    call_analytics_row,
    row,
)

router = APIRouter()


@router.get("/api/notifications", dependencies=[Depends(auth)])
def list_notifications(
    status: str | None = None,
    appointment_id: str | None = None,
    recipient_type: str | None = None,
):
    with db_module.Session() as db:
        query = select(NotificationOutbox).order_by(
            NotificationOutbox.created_at.desc()
        )
        if status:
            query = query.where(NotificationOutbox.status == status)
        if appointment_id:
            query = query.where(NotificationOutbox.appointment_id == appointment_id)
        if recipient_type:
            query = query.where(NotificationOutbox.recipient_type == recipient_type)
        items = db.scalars(query.limit(100)).all()
        return [row(n) for n in items]


@router.post("/api/notifications/dispatch", dependencies=[Depends(auth)])
def dispatch_notifications():
    with db_module.Session() as db:
        dispatched = dispatch_pending_notifications(db, limit=50)
        return {
            "dispatched_count": len(dispatched),
            "dispatched": [row(n) for n in dispatched],
        }


@router.post("/api/notifications/{id}/retry", dependencies=[Depends(auth)])
def retry_single_notification(id: str):
    with db_module.Session() as db:
        res = retry_notification(db, id)
        if not res:
            raise HTTPException(404, "Bildirim bulunamadı")
        return row(res)


@router.post("/api/outbound/call", dependencies=[Depends(auth)])
async def create_outbound_call(body: OutboundCallIn):
    with db_module.Session() as db:
        try:
            call_record = await initiate_outbound_call(
                db,
                appointment_id=body.appointment_id,
                phone=body.phone,
                call_type=body.call_type,
            )
            return row(call_record)
        except ValueError as e:
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))


@router.get("/api/outbound/calls", dependencies=[Depends(auth)])
def list_outbound_calls(
    appointment_id: str | None = None,
    status: str | None = None,
):
    with db_module.Session() as db:
        query = select(OutboundCall).order_by(OutboundCall.created_at.desc())
        if appointment_id:
            query = query.where(OutboundCall.appointment_id == appointment_id)
        if status:
            query = query.where(OutboundCall.status == status)
        calls = db.scalars(query.limit(100)).all()
        return [row(c) for c in calls]


@router.post("/api/outbound/calls/{id}/cancel", dependencies=[Depends(auth)])
def cancel_call(id: str):
    with db_module.Session() as db:
        try:
            return row(cancel_outbound_call(db, id))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/outbound/calls/{id}/complete", dependencies=[Depends(auth)])
def complete_call(id: str, body: CallOutcomeIn):
    with db_module.Session() as db:
        try:
            return row(
                complete_outbound_call(
                    db, call_id=id, outcome=body.outcome, notes=body.notes
                )
            )
        except ValueError as e:
            raise HTTPException(422, str(e))


@router.get("/api/outbound/ami-status", dependencies=[Depends(auth)])
async def get_ami_status():
    ami = get_ami_client()
    real = is_real_ami()
    # Mock istemci ping'e "başarılı" der; gerçek bağlantı olmadığı için connected=False döner.
    is_up = (await ami.ping()) if real else False
    with db_module.Session() as db:
        stats = get_outbound_stats(db)
    return {
        "ami_host": settings.ami_host,
        "ami_port": settings.ami_port,
        "connected": is_up,
        "simulated": not real,
        "stats": stats,
    }


@router.post("/api/outbound/campaign-dial", dependencies=[Depends(auth)])
async def campaign_dial(body: CampaignDialIn):
    results = []
    errors = []
    with db_module.Session() as db:
        for app_id in body.appointment_ids:
            try:
                if body.dial_mode == "callfile":
                    call_rec, _ = campaign_dialer.originate_call_file(
                        db, appointment_id=app_id, call_type=body.call_type
                    )
                    results.append(row(call_rec))
                else:
                    call_rec = await campaign_dialer.originate_call_ami(
                        db, appointment_id=app_id, call_type=body.call_type
                    )
                    results.append(row(call_rec))
            except Exception as e:
                errors.append({"appointment_id": app_id, "error": str(e)})

    return {
        "mode": body.dial_mode,
        "total": len(body.appointment_ids),
        "successful_count": len(results),
        "failed_count": len(errors),
        "calls": results,
        "errors": errors,
    }


@router.post("/api/outbound/amd-analyze", dependencies=[Depends(auth)])
def amd_analyze(body: AMDAnalyzeIn):
    import base64
    try:
        raw_bytes = base64.b64decode(body.audio_base64)
    except Exception as e:
        raise HTTPException(400, f"Geçersiz Base64 verisi: {e}")

    result = detect_turkish_amd(raw_bytes, sample_rate=body.sample_rate)
    return result.to_dict()


@router.post("/api/outbound/amd-evaluate-call", dependencies=[Depends(auth)])
def amd_evaluate_call(body: AMDEvaluateCallIn):
    with db_module.Session() as db:
        try:
            amd_res = AMDResult(
                classification=body.classification,
                confidence=0.95,
                greeting_duration_sec=1.0,
                silence_duration_sec=0.5,
                beep_detected=(body.classification == "MACHINE"),
                reason=body.reason or f"Manüel/Olay bazlı {body.classification} ataması",
            )
            updated_call = campaign_dialer.process_amd_result(db, body.call_id, amd_res)
            return row(updated_call)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/outbound/retry-queue", dependencies=[Depends(auth)])
def get_retry_queue():
    with db_module.Session() as db:
        query = (
            select(OutboundCall)
            .where(OutboundCall.status == "retry_scheduled")
            .order_by(OutboundCall.created_at.asc())
        )
        scheduled_calls = db.scalars(query).all()
        return [row(c) for c in scheduled_calls]


@router.post("/api/outbound/retry-process", dependencies=[Depends(auth)])
async def trigger_retry_process(limit: int = 10):
    with db_module.Session() as db:
        retried = await campaign_dialer.process_retry_queue(db, limit=limit)
        return {
            "processed": len(retried),
            "retried_calls": [row(c) for c in retried],
        }


@router.get("/api/outbound/campaign-stats", dependencies=[Depends(auth)])
def get_campaign_stats():
    return campaign_dialer.get_metrics()


# ============================================================================
# AUDIOSOCKET TCP 9092 & ÇİFT KADEMELİ BARGE-IN ENDPOINTS
# ============================================================================

@router.get("/api/audiosocket/stats", dependencies=[Depends(auth)])
def get_audiosocket_stats_endpoint():
    """Asterisk app_audiosocket TCP 9092 orkestratör metriklerini döndürür."""
    return orchestrator.get_metrics()


@router.post("/api/audiosocket/simulate-bargein", dependencies=[Depends(auth)])
def simulate_barge_in_endpoint(body: SimulateBargeInIn):
    """Çift kademeli barge-in (Stage 1 soft pause, Stage 2 rollback vs commit) simülasyonu."""
    ctrl = TwoStageBargeInController()
    ctrl.stage1_soft_pause()
    decision = ctrl.stage2_evaluate(body.text)
    is_backchannel = decision == "rollback"
    return {
        "input_text": body.text,
        "decision": decision,
        "is_backchannel": is_backchannel,
        "action": "resume_playback" if is_backchannel else "flush_and_cancel_queue",
        "explanation": (
            "Dinleme teyidi (backchannel) algılandı; ses çalmaya devam eder, LLM kuyruğu korunur."
            if is_backchannel
            else "Kullanıcı müdahalesi algılandı; aktif ses ve LLM kuyruğu iptal edilir (hard flush)."
        ),
        "stats": ctrl.get_stats(),
    }


# ============================================================================
# CHAN_WEBSOCKET ASTERISK 20.18+ WS 8088 & FLUSH_MEDIA ENDPOINTS
# ============================================================================

@router.websocket("/ws/asterisk")
async def asterisk_chan_websocket_endpoint(ws: WebSocket):
    """Asterisk 20.18+ chan_websocket WebSocket bağlantı uç noktası."""
    await chan_ws_adapter.handle_fastapi_websocket(ws)


@router.get("/api/chan-websocket/stats", dependencies=[Depends(auth)])
def get_chan_websocket_stats_endpoint():
    """Asterisk chan_websocket WS 8088 adaptör metriklerini döndürür."""
    return chan_ws_adapter.get_metrics()


@router.post("/api/chan-websocket/flush", dependencies=[Depends(auth)])
async def trigger_chan_websocket_flush_endpoint():
    """Tüm aktif chan_websocket oturumlarına anında FLUSH_MEDIA komutu gönderir."""
    flushed_count = await chan_ws_adapter.flush_all_active_sessions()
    return {
        "status": "flushed",
        "flushed_sessions_count": flushed_count,
        "active_sessions": len(chan_ws_adapter.active_sessions),
    }


@router.get("/api/transfers", dependencies=[Depends(auth)])
def get_transfers_endpoint(status: str | None = None, limit: int = 50):
    with db_module.Session() as db:
        check_transfer_timeouts(db)
        items = list_transfers(db, status=status, limit=limit)
        result = []
        for t in items:
            r = row(t)
            try:
                r["sip_headers"] = json.loads(t.sip_headers_json)
            except Exception:
                r["sip_headers"] = {}
            result.append(r)
        return result


@router.get("/api/transfers/{id}", dependencies=[Depends(auth)])
def get_transfer_detail_endpoint(id: str):
    with db_module.Session() as db:
        check_transfer_timeouts(db)
        t = db.get(OperatorTransfer, id)
        if not t:
            raise HTTPException(404, "Aktarım kaydı bulunamadı")
        r = row(t)
        try:
            r["sip_headers"] = json.loads(t.sip_headers_json)
        except Exception:
            r["sip_headers"] = {}
        return r


@router.post("/api/transfers/initiate", dependencies=[Depends(auth)])
async def initiate_transfer_endpoint(body: TransferInitiateIn):
    with db_module.Session() as db:
        try:
            t = await initiate_operator_transfer(
                db,
                conversation_id=body.conversation_id,
                caller_channel=body.caller_channel,
                customer_name=body.customer_name,
                vehicle_plate=body.vehicle_plate,
                summary=body.summary,
                intent=body.intent,
                operator_extension=body.operator_extension,
            )
            r = row(t)
            try:
                r["sip_headers"] = json.loads(t.sip_headers_json)
            except Exception:
                r["sip_headers"] = {}
            return r
        except ValueError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, str(e))


@router.post("/api/transfers/{id}/accept", dependencies=[Depends(auth)])
async def accept_transfer_endpoint(id: str, body: TransferAcceptIn = None):
    op_ch = body.operator_channel if body else None
    with db_module.Session() as db:
        try:
            t = await accept_operator_transfer(db, id, operator_channel=op_ch)
            return row(t)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/transfers/{id}/decline", dependencies=[Depends(auth)])
async def decline_transfer_endpoint(id: str, body: TransferDeclineIn = None):
    reason = body.reason if body else "declined"
    with db_module.Session() as db:
        try:
            t = await decline_operator_transfer(db, id, reason=reason)
            r = row(t)
            r["fallback_prompt"] = FALLBACK_AI_PROMPT
            return r
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/transfers/{id}/dtmf", dependencies=[Depends(auth)])
async def transfer_dtmf_endpoint(id: str, body: TransferDTMFIn):
    with db_module.Session() as db:
        try:
            res = await handle_operator_dtmf(
                db, id, body.digit, operator_channel=body.operator_channel
            )
            return res
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/whatsapp/messages", dependencies=[Depends(auth)])
def get_whatsapp_messages_endpoint(limit: int = 50):
    with db_module.Session() as db:
        msgs = list_whatsapp_messages(db, limit=limit)
        return [row(m) for m in msgs]


@router.post("/api/whatsapp/inbound", dependencies=[Depends(auth)])
def whatsapp_inbound_endpoint(body: WhatsAppInboundIn):
    sender = body.sender_phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")
    with db_module.Session() as db:
        res = process_inbound_text(
            db,
            from_phone=sender,
            text=body.text,
            customer_name=body.customer_name or "",
            message_sid=body.message_sid or "",
        )
        return res


@router.post("/api/whatsapp/inbound-voice", dependencies=[Depends(auth)])
async def whatsapp_inbound_voice_endpoint(
    file: UploadFile = File(None),
    audio_file: UploadFile = File(None),
    from_phone: str = Form(None),
    phone: str = Form(None),
    customer_name: str | None = Form(None),
):
    upload = file or audio_file
    if not upload:
        raise HTTPException(400, "Ses dosyası boş veya eksik")
    sender = from_phone or phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")

    content = await read_upload_capped(upload, MAX_AUDIO_BYTES)
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    import soundfile as sf
    from backend.audio import resample

    try:
        audio_data, sr = sf.read(io.BytesIO(content), dtype="float32")
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
        if sr != 16000:
            audio_data = resample(audio_data, sr, 16000)
    except Exception:
        audio_data = io.BytesIO(content)

    with db_module.Session() as db:
        res = await process_inbound_voice(
            db,
            from_phone=sender,
            audio_data=audio_data,
            customer_name=customer_name or "",
        )
        return res


@router.post("/api/webhooks/whatsapp")
async def whatsapp_webhook_endpoint(request: Request):
    """
    Twilio / WhatsApp Cloud API webhook alıcısı.
    Form-urlencoded (Twilio) veya JSON (WhatsApp Cloud) kabul eder.
    Paylaşılan gizli anahtar (X-Webhook-Token) gövde işlenmeden önce doğrulanır.
    """
    if not settings.whatsapp_webhook_token:
        raise HTTPException(503, "WHATSAPP_WEBHOOK_TOKEN ayarlanmalı")
    supplied = request.headers.get("x-webhook-token", "")
    if not secrets.compare_digest(
        supplied.encode(), settings.whatsapp_webhook_token.encode()
    ):
        raise HTTPException(401, "Geçersiz webhook anahtarı")

    content_type = request.headers.get("content-type", "")
    from_phone = ""
    text_content = ""
    message_sid = ""

    if "application/json" in content_type:
        try:
            data = await request.json()
            entries = data.get("entry", [])
            if entries:
                changes = entries[0].get("changes", [])
                if changes:
                    val = changes[0].get("value", {})
                    messages = val.get("messages", [])
                    if messages:
                        m = messages[0]
                        from_phone = m.get("from", "")
                        message_sid = m.get("id", "")
                        if m.get("type") == "text":
                            text_content = m.get("text", {}).get("body", "")
            if not from_phone and "from_phone" in data:
                from_phone = data.get("from_phone", "")
                text_content = data.get("text", "")
                message_sid = data.get("message_sid", "")
        except Exception:
            raise HTTPException(400, "Geçersiz JSON yükü")
    else:
        form_data = await request.form()
        from_phone = str(form_data.get("From", "")).replace("whatsapp:", "")
        text_content = str(form_data.get("Body", ""))
        message_sid = str(form_data.get("MessageSid", ""))

    if not from_phone or not text_content:
        raise HTTPException(422, "Telefon ve mesaj metni gereklidir")

    with db_module.Session() as db:
        res = process_inbound_text(
            db,
            from_phone=from_phone,
            text=text_content,
            message_sid=message_sid,
        )
        return res


@router.post("/api/whatsapp/inbound-image", dependencies=[Depends(auth)])
async def whatsapp_inbound_image_endpoint(
    file: UploadFile = File(None),
    image_file: UploadFile = File(None),
    from_phone: str = Form(None),
    phone: str = Form(None),
    customer_name: str | None = Form(None),
):
    upload = file or image_file
    if not upload:
        raise HTTPException(400, "Görsel dosyası boş veya eksik")
    sender = from_phone or phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")

    content = await read_upload_capped(upload, MAX_IMAGE_BYTES)
    if not content:
        raise HTTPException(400, "Görsel içeriği boş")

    with db_module.Session() as db:
        res = process_inbound_image(
            db,
            from_phone=sender,
            image_bytes=content,
            customer_name=customer_name or "",
            filename=upload.filename or "ruhsat.jpg",
        )
        return res


@router.post("/api/analytics/evaluate-call", dependencies=[Depends(auth)])
def evaluate_call_endpoint(body: CallAnalyticsIn):
    with db_module.Session() as db:
        try:
            record = evaluate_and_save_call_analytics(
                db,
                conversation_id=body.conversation_id,
                appointment_id=body.appointment_id,
                caller_phone=body.caller_phone or "",
                caller_name=body.caller_name or "",
                duration_sec=body.duration_sec,
                transcript_override=body.transcript,
            )
            return call_analytics_row(record)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/analytics/calls", dependencies=[Depends(auth)])
def get_analytics_calls_endpoint(limit: int = 50, lead_tier: str | None = None):
    with db_module.Session() as db:
        stmt = select(CallAnalytics).order_by(CallAnalytics.created_at.desc())
        if lead_tier:
            stmt = stmt.where(CallAnalytics.lead_tier == lead_tier.upper())
        records = db.scalars(stmt.limit(limit)).all()
        return [call_analytics_row(r) for r in records]


@router.get("/api/analytics/call-stats", dependencies=[Depends(auth)])
def get_analytics_call_stats_endpoint():
    with db_module.Session() as db:
        return get_analytics_summary_stats(db)
