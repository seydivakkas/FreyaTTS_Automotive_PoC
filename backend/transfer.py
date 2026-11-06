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

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ami import AMIClientProtocol, get_ami_client
from backend.config import settings
from backend.db import Conversation, OperatorTransfer

logger = logging.getLogger("transfer")

# AI Geri Dönüş (Fallback) Cümlesi (Uzman meşgul olduğunda veya zaman aşımında)
FALLBACK_AI_PROMPT = (
    "Uzmanımız şu an diğer bir müşterimizle görüşmede olduğu için hatta bağlanamadı. "
    "İşlemlerinize benimle devam edebilirsiniz. Size nasıl yardımcı olabilirim?"
)

# Canlı Aktarım Bilgilendirme Anonsu (Müşteriye çalınır, playout drain ile bitmesi beklenir)
TRANSFER_ANNOUNCEMENT = (
    "Sizi yetkili ekspertiz danışmanımıza aktarıyorum. Lütfen hattan ayrılmayın."
)


def generate_screen_pop_headers(
    transfer_id: str,
    customer_name: str,
    vehicle_plate: str,
    summary: str,
    intent: str = "operator_transfer",
) -> Dict[str, str]:
    """SIP başlıkları için X-Freya-* alanlarını oluşturur."""
    return {
        "X-Freya-Transfer-ID": str(transfer_id),
        "X-Freya-Customer": str(customer_name or "Müşteri"),
        "X-Freya-Plate": str(vehicle_plate or "Belirtilmedi"),
        "X-Freya-Summary": str(summary or "Canlı destek aktarımı"),
        "X-Freya-Intent": str(intent or "operator_transfer"),
        "X-Freya-Timestamp": datetime.now(timezone.utc).isoformat(),
    }


def generate_whisper_text(
    customer_name: str = "",
    vehicle_plate: str = "",
    summary: str = "",
    intent: str = "operator_transfer",
) -> str:
    """
    Uzmana (dahili 6002) okunacak <= 10 saniyelik fısıltı özet metnini üretir.
    Ortalama Türkçe konuşma hızında 15-25 kelime ~ 7-10 saniye sürer.
    """
    cust = customer_name.strip() if customer_name else "Müşterimiz"
    plate = vehicle_plate.strip() if vehicle_plate else "araç"
    subj = summary.strip() if summary else "danışman görüşmesi"

    whisper = (
        f"{cust}, {plate} plakalı araç için hatta. Konu: {subj}. "
        f"Görüşmeyi almak için 1'i, meşgulseniz 2'yi tuşlayınız."
    )
    return whisper


async def initiate_operator_transfer(
    db: Session,
    *,
    conversation_id: Optional[str] = None,
    caller_channel: str = "",
    customer_name: str = "",
    vehicle_plate: str = "",
    summary: str = "",
    intent: str = "operator_transfer",
    operator_extension: Optional[str] = None,
    ami_client: Optional[AMIClientProtocol] = None,
) -> OperatorTransfer:
    """
    Canlı operatöre aktarım sürecini başlatır (Warm Transfer & Screen-Pop).
    1. OperatorTransfer kaydı oluşturur (status: 'initiated').
    2. SIP başlıklarını X-Freya-* olarak derler ve caller_channel üzerine setvar ile yazar.
    3. Dahili 6002'yi arayarak sesli fısıltıyı (<=10 sn) iletir (status: 'whispering').
    """
    op_ext = operator_extension or settings.operator_extension
    transfer_id = f"trf-{uuid4().hex[:12]}"
    channel = caller_channel or f"PJSIP/caller-{transfer_id[:8]}"

    sip_headers = generate_screen_pop_headers(
        transfer_id=transfer_id,
        customer_name=customer_name,
        vehicle_plate=vehicle_plate,
        summary=summary,
        intent=intent,
    )
    whisper_text = generate_whisper_text(
        customer_name=customer_name,
        vehicle_plate=vehicle_plate,
        summary=summary,
        intent=intent,
    )

    transfer = OperatorTransfer(
        id=transfer_id,
        conversation_id=conversation_id,
        caller_channel=channel,
        operator_extension=op_ext,
        customer_name=customer_name or "",
        vehicle_plate=vehicle_plate or "",
        summary=summary or "",
        whisper_text=whisper_text,
        status="initiated",
        sip_headers_json=json.dumps(sip_headers, ensure_ascii=False),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)

    client = ami_client or get_ami_client()

    try:
        # SIP Başlıklarını ve Screen-Pop değişkenlerini Asterisk kanalına yaz
        for key, value in sip_headers.items():
            var_name = key.replace("-", "_")
            await client.setvar(channel, var_name, value)
            # Standart Asterisk SIP header kanalı ekleme
            await client.setvar(channel, f"SIPADDHEADER_{var_name}", f"{key}: {value}")

        # Operatör dahilisini arayarak fısıltı çağrısı başlat (Warm Transfer Whisper)
        orig_vars = {
            "TRANSFER_ID": transfer.id,
            "CALLER_CHANNEL": channel,
            "CUSTOMER_NAME": customer_name,
            "VEHICLE_PLATE": vehicle_plate,
            "WHISPER_TEXT": whisper_text,
            "OPERATOR_EXTEN": op_ext,
        }
        await client.originate(
            channel=f"Local/{op_ext}@{settings.operator_context}",
            context=settings.operator_context,
            exten=op_ext,
            callerid=f"Freya AI Transfer <{op_ext}>",
            variables=orig_vars,
            timeout_ms=settings.operator_whisper_timeout_sec * 1000,
        )
        transfer.status = "whispering"
        db.commit()
        db.refresh(transfer)
    except Exception as e:
        logger.warning("AMI üzerinden operatör fısıltısı başlatılamadı: %s", e)
        # AMI yoksa bile (ör. mock/test modu) transfer kaydı initiated/whispering kalabilir

    return transfer


async def accept_operator_transfer(
    db: Session,
    transfer_id: str,
    *,
    operator_channel: Optional[str] = None,
    ami_client: Optional[AMIClientProtocol] = None,
) -> OperatorTransfer:
    """
    Operatör aktarımı kabul ettiğinde çağrıyı köprüler (Bridge / Redirect).
    Uzman 1 tuşladığında veya Web Screen-Pop üzerinden 'Kabul Et' butonuna bastığında çağrılır.
    """
    transfer = db.get(OperatorTransfer, transfer_id)
    if not transfer:
        raise ValueError(f"Transfer kaydı bulunamadı: {transfer_id}")

    if transfer.status in ("accepted", "declined", "timeout", "failed"):
        return transfer

    client = ami_client or get_ami_client()

    try:
        if operator_channel:
            # İki canlı kanalı doğrudan köprüle (AMI Bridge)
            await client.bridge(transfer.caller_channel, operator_channel, tone=True)
        else:
            # Müşteri kanalını operatör dahili uzantısına yönlendir (AMI Redirect)
            await client.redirect(
                channel=transfer.caller_channel,
                context=settings.operator_context,
                exten=transfer.operator_extension,
                priority=1,
            )
    except Exception as e:
        logger.error("Çağrı köprüleme hatası: %s", e)

    now_iso = datetime.now(timezone.utc).isoformat()
    transfer.status = "accepted"
    transfer.completed_at = now_iso

    try:
        created_dt = datetime.fromisoformat(transfer.created_at)
        completed_dt = datetime.fromisoformat(now_iso)
        transfer.duration_seconds = max(0.0, (completed_dt - created_dt).total_seconds())
    except Exception:
        transfer.duration_seconds = 0.0

    # İlgili conversation kaydını güncelle
    if transfer.conversation_id:
        conv = db.get(Conversation, transfer.conversation_id)
        if conv:
            conv.status = "transferred"
            notes = conv.operator_notes or ""
            note_line = f"[{now_iso}] Uzman ({transfer.operator_extension}) çağrıyı kabul etti ve hatta bağlandı."
            conv.operator_notes = f"{notes}\n{note_line}".strip()

    db.commit()
    db.refresh(transfer)
    return transfer


async def decline_operator_transfer(
    db: Session,
    transfer_id: str,
    *,
    reason: str = "declined",
    operator_channel: Optional[str] = None,
    ami_client: Optional[AMIClientProtocol] = None,
) -> OperatorTransfer:
    """
    Operatör çağrıyı reddettiğinde veya meşgul olduğunda çalışır.
    Uzman 2 tuşladığında, Web Screen-Pop'ta reddedildiğinde veya 15 sn timeout durumunda.
    Müşteri tekrar Leyla AI'ya geri döner.
    """
    transfer = db.get(OperatorTransfer, transfer_id)
    if not transfer:
        raise ValueError(f"Transfer kaydı bulunamadı: {transfer_id}")

    if transfer.status in ("accepted", "declined", "timeout", "failed"):
        return transfer

    client = ami_client or get_ami_client()

    if operator_channel:
        try:
            await client.hangup(operator_channel)
        except Exception:
            pass

    now_iso = datetime.now(timezone.utc).isoformat()
    transfer.status = "timeout" if reason == "timeout" else "declined"
    transfer.completed_at = now_iso

    try:
        created_dt = datetime.fromisoformat(transfer.created_at)
        completed_dt = datetime.fromisoformat(now_iso)
        transfer.duration_seconds = max(0.0, (completed_dt - created_dt).total_seconds())
    except Exception:
        transfer.duration_seconds = 0.0

    if transfer.conversation_id:
        conv = db.get(Conversation, transfer.conversation_id)
        if conv:
            notes = conv.operator_notes or ""
            note_line = f"[{now_iso}] Uzman aktarımı {transfer.status} oldu. Çağrı AI'ya iade edildi."
            conv.operator_notes = f"{notes}\n{note_line}".strip()

    db.commit()
    db.refresh(transfer)
    return transfer


async def handle_operator_dtmf(
    db: Session,
    transfer_id: str,
    digit: str,
    *,
    operator_channel: Optional[str] = None,
    ami_client: Optional[AMIClientProtocol] = None,
) -> Dict[str, Any]:
    """
    Uzmanın fısıltı esnasında tuşladığı DTMF rakamını işler:
    - 1: Kabul et (Bridge)
    - 2: Reddet / Meşgul (Decline / Fallback AI)
    """
    d = str(digit).strip()
    if d == "1":
        tr = await accept_operator_transfer(
            db, transfer_id, operator_channel=operator_channel, ami_client=ami_client
        )
        return {"action": "accepted", "status": tr.status, "transfer_id": tr.id}
    elif d == "2":
        tr = await decline_operator_transfer(
            db,
            transfer_id,
            reason="declined",
            operator_channel=operator_channel,
            ami_client=ami_client,
        )
        return {
            "action": "declined",
            "status": tr.status,
            "transfer_id": tr.id,
            "fallback_prompt": FALLBACK_AI_PROMPT,
        }
    return {"action": "ignored", "digit": d, "transfer_id": transfer_id}


def check_transfer_timeouts(
    db: Session,
    timeout_sec: Optional[int] = None,
) -> List[OperatorTransfer]:
    """
    Zaman aşımına uğramış (ör. 15 saniyedir yanıt vermeyen) fısıltı çağrılarını bulup 'timeout' olarak işaretler.
    """
    limit = timeout_sec or settings.operator_whisper_timeout_sec
    now = datetime.now(timezone.utc)
    pending_transfers = (
        db.scalars(
            select(OperatorTransfer).where(
                OperatorTransfer.status.in_(["initiated", "whispering"])
            )
        )
        .all()
    )

    timed_out = []
    for tr in pending_transfers:
        if tr.id.startswith("demo_"):
            continue
        try:
            created = datetime.fromisoformat(tr.created_at)
            if (now - created).total_seconds() >= limit:
                tr.status = "timeout"
                tr.completed_at = now.isoformat()
                tr.duration_seconds = (now - created).total_seconds()
                timed_out.append(tr)
        except Exception:
            pass

    if timed_out:
        db.commit()
    return timed_out


def list_transfers(
    db: Session,
    *,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[OperatorTransfer]:
    """Aktarım geçmişini ve aktif kuyruğu listeler."""
    stmt = select(OperatorTransfer).order_by(OperatorTransfer.created_at.desc())
    if status:
        stmt = stmt.where(OperatorTransfer.status == status)
    if limit > 0:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())

