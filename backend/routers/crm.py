"""CRM uç noktaları: araç, muayene, tanılama, teklif, randevu, görüşme, kurumsal hesap, ruhsat, değerleme."""

import io
import json
import secrets
from dataclasses import asdict
from datetime import (
    datetime,
    timezone,
    timedelta,
)
from pathlib import Path
from uuid import UUID
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Response,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from backend.config import settings
from backend.security_utils import (
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    read_upload_capped,
    signed_pdf_path,
    verify_signed_link,
)
from backend.db import (
    Vehicle,
    Quote,
    Slot,
    Appointment,
    Conversation,
    Turn,
    book,
    cancel_appointment,
    CorporateAccount,
    CorporateLedger,
    record_payment,
    InspectionReport,
    NotificationOutbox,
    VehicleDiagnostic,
    RuhsatScan,
)
from backend.dynamic_valuation_calculator import (
    calculate_and_save_valuation,
    ESTIMATE_BASIS,
    calculate_dynamic_valuation,
    list_vehicle_valuations,
    parse_spoken_valuation_query,
)
from backend.vin_ruhsat_decoder import (
    decode_phonetic_spelling,
    decode_ruhsat_text,
    process_inbound_ruhsat_image,
)
from backend.queue_lift import PACKAGE_DEFINITIONS
from backend.notifications import (
    dispatch_pending_notifications,
    queue_inspection_delivery_notifications,
)
from backend.report_generator import generate_inspection_pdf
from backend.analytics import (
    get_analytics_overview,
    get_follow_up_conversations,
    resolve_conversation,
    reopen_conversation,
)
from backend.diagnostics import (
    DTC_REGISTRY,
    ingest_vehicle_telemetry,
    trigger_proactive_diagnostic_call,
    trigger_proactive_diagnostic_sms,
    resolve_diagnostic,
    PhoneMissingError,
)
from backend.technician_dictation import (
    parse_technician_dictation,
    apply_dictation_to_report,
)
from backend.vin import validate_vin
from backend.models import models
from backend.session import active
from backend import db as db_module
from backend.schemas import (
    BookingIn,
    ConversationResolveIn,
    CorporateAccountIn,
    CorporateAccountUpdateIn,
    DictationTextIn,
    InspectionReportIn,
    PaymentIn,
    PhoneticDecodeIn,
    ProactiveActionIn,
    QuoteIn,
    RuhsatApplyIn,
    RuhsatTextDecodeIn,
    SlotIn,
    SpokenValuationIn,
    TelemetryIngestIn,
    VehicleIn,
    VehicleUpdateIn,
    VehicleValuationIn,
)
from backend.deps import (
    auth,
    optional_security,
    row,
)

router = APIRouter()


@router.get("/api/vehicles/{id}", dependencies=[Depends(auth)])
def get_vehicle(id: str):
    with db_module.Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        return row(v)


@router.get("/api/inspections", dependencies=[Depends(auth)])
def list_inspections():
    with db_module.Session() as db:
        reports = db.scalars(
            select(InspectionReport).order_by(InspectionReport.inspected_at.desc())
        ).all()
        result = []
        for r in reports:
            v = db.get(Vehicle, r.vehicle_id)
            d = row(r)
            d["vehicle_plate"] = getattr(v, "plate", "") if v else ""
            d["vehicle_description"] = getattr(v, "description", "") if v else ""
            result.append(d)
        return result


@router.get("/api/inspections/{id}", dependencies=[Depends(auth)])
def get_inspection(id: str):
    with db_module.Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        d = row(report)
        d["vehicle"] = row(vehicle) if vehicle else None
        return d


@router.get("/api/analytics/overview", dependencies=[Depends(auth)])
def analytics_overview():
    with db_module.Session() as db:
        return {
            **get_analytics_overview(db),
            "data_source": "demo" if settings.demo_mode else "live",
        }


@router.get("/api/analytics/follow-ups", dependencies=[Depends(auth)])
def list_follow_ups(status: str = "all", limit: int = 50):
    with db_module.Session() as db:
        return get_follow_up_conversations(db, status_filter=status, limit=limit)


@router.post("/api/analytics/conversations/{id}/resolve", dependencies=[Depends(auth)])
def resolve_conv(id: str, body: ConversationResolveIn):
    with db_module.Session() as db:
        try:
            c = resolve_conversation(db, id, operator_notes=body.notes)
            return row(c)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/analytics/conversations/{id}/reopen", dependencies=[Depends(auth)])
def reopen_conv(id: str):
    with db_module.Session() as db:
        try:
            c = reopen_conversation(db, id)
            return row(c)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/diagnostics/dtc-registry", dependencies=[Depends(auth)])
def get_dtc_registry():
    return DTC_REGISTRY


@router.get("/api/diagnostics", dependencies=[Depends(auth)])
def list_all_diagnostics(is_resolved: bool | None = None):
    with db_module.Session() as db:
        query = select(VehicleDiagnostic).order_by(VehicleDiagnostic.created_at.desc())
        if is_resolved is not None:
            query = query.where(VehicleDiagnostic.is_resolved == is_resolved)
        records = db.scalars(query).all()
        result = []
        for r in records:
            v = db.get(Vehicle, r.vehicle_id)
            d = row(r)
            d["vehicle_plate"] = getattr(v, "plate", "") if v else ""
            d["vehicle_description"] = getattr(v, "description", "") if v else ""
            result.append(d)
        return result


@router.get("/api/vehicles/{id}/diagnostics", dependencies=[Depends(auth)])
def list_vehicle_diagnostics(id: str):
    with db_module.Session() as db:
        if not db.get(Vehicle, id):
            raise HTTPException(404, "Araç bulunamadı")
        records = db.scalars(
            select(VehicleDiagnostic)
            .where(VehicleDiagnostic.vehicle_id == id)
            .order_by(VehicleDiagnostic.created_at.desc())
        ).all()
        return [row(r) for r in records]


@router.post("/api/vehicles/{id}/diagnostics", dependencies=[Depends(auth)])
def add_vehicle_telemetry(id: str, body: TelemetryIngestIn):
    with db_module.Session() as db:
        try:
            created = ingest_vehicle_telemetry(
                db,
                vehicle_id=id,
                current_km=body.current_km,
                dtc_codes=body.dtc_codes,
                source=body.source,
                owner_name=body.owner_name,
                owner_phone=body.owner_phone,
            )
            return [row(d) for d in created]
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/diagnostics/{id}/call", dependencies=[Depends(auth)])
async def call_diagnostic_owner(id: str, body: ProactiveActionIn):
    with db_module.Session() as db:
        try:
            call_obj = await trigger_proactive_diagnostic_call(
                db, diagnostic_id=id, phone=body.phone
            )
            return row(call_obj)
        except PhoneMissingError as e:
            raise HTTPException(422, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/diagnostics/{id}/sms", dependencies=[Depends(auth)])
def sms_diagnostic_owner(id: str, body: ProactiveActionIn):
    with db_module.Session() as db:
        try:
            notif = trigger_proactive_diagnostic_sms(
                db, diagnostic_id=id, phone=body.phone
            )
            dispatched = dispatch_pending_notifications(db)
            return {
                "notification": row(notif),
                "dispatched_count": len(dispatched),
            }
        except PhoneMissingError as e:
            raise HTTPException(422, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/diagnostics/{id}/resolve", dependencies=[Depends(auth)])
def resolve_diag(id: str):
    with db_module.Session() as db:
        try:
            diag = resolve_diagnostic(db, id)
            return row(diag)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/packages", dependencies=[Depends(auth)])
def list_packages():
    return list(PACKAGE_DEFINITIONS.values())


@router.post("/api/ruhsat/decode-image", dependencies=[Depends(auth)])
async def ruhsat_decode_image_endpoint(
    file: UploadFile = File(None),
    from_phone: str = Form(""),
    appointment_id: str | None = Form(None),
):
    if not file:
        raise HTTPException(400, "Ruhsat görsel dosyası gereklidir")
    content = await read_upload_capped(file, MAX_IMAGE_BYTES)
    if not content:
        raise HTTPException(400, "Dosya içeriği boş")

    with db_module.Session() as db:
        scan_record, parsed = process_inbound_ruhsat_image(
            db,
            from_phone=from_phone,
            image_bytes=content,
            appointment_id=appointment_id,
            filename=file.filename or "",
        )
        res = row(scan_record)
        res["parsed"] = parsed
        return res


@router.post("/api/ruhsat/decode-text", dependencies=[Depends(auth)])
def ruhsat_decode_text_endpoint(body: RuhsatTextDecodeIn):
    parsed = decode_ruhsat_text(body.ocr_text)
    return parsed


@router.post("/api/ruhsat/decode-phonetic", dependencies=[Depends(auth)])
def ruhsat_decode_phonetic_endpoint(body: PhoneticDecodeIn):
    return decode_phonetic_spelling(body.spoken_text)


@router.post("/api/ruhsat/apply-to-crm", dependencies=[Depends(auth)])
def ruhsat_apply_crm_endpoint(body: RuhsatApplyIn):
    with db_module.Session() as db:
        vehicle = None
        norm_plate = body.plate.replace(" ", "").upper()
        vehicles = db.scalars(select(Vehicle)).all()
        for v in vehicles:
            if v.plate and v.plate.replace(" ", "").upper() == norm_plate:
                vehicle = v
                break

        if not vehicle:
            desc = body.brand_model or f"Araç {body.plate}"
            vehicle = Vehicle(plate=body.plate, description=desc, vin=body.vin or "")
            db.add(vehicle)
            db.flush()
        else:
            if body.vin and not vehicle.vin:
                vehicle.vin = body.vin
            if body.brand_model and "Araç" in vehicle.description:
                vehicle.description = body.brand_model

        if body.appointment_id:
            app = db.get(Appointment, body.appointment_id)
            if app:
                app.vehicle_id = vehicle.id

        if body.scan_id:
            scan = db.get(RuhsatScan, body.scan_id)
            if scan:
                scan.vehicle_id = vehicle.id
                if body.appointment_id:
                    scan.appointment_id = body.appointment_id

        db.commit()
        models.invalidate_hotwords()
        return {
            "status": "applied",
            "vehicle_id": vehicle.id,
            "plate": vehicle.plate,
            "vin": vehicle.vin,
            "description": vehicle.description,
        }


@router.get("/api/ruhsat/scans", dependencies=[Depends(auth)])
def get_ruhsat_scans_endpoint(limit: int = 50):
    with db_module.Session() as db:
        scans = db.scalars(
            select(RuhsatScan).order_by(RuhsatScan.created_at.desc()).limit(limit)
        ).all()
        return [row(s) for s in scans]


@router.post("/api/valuation/calculate", dependencies=[Depends(auth)])
def valuation_calculate_endpoint(body: VehicleValuationIn):
    val = calculate_dynamic_valuation(
        brand=body.brand,
        model=body.model,
        model_year=body.model_year,
        mileage_km=body.mileage_km,
        body_panels=body.body_panels,
        tramer_amount_tl=body.tramer_amount_tl,
        is_heavy_damage=body.is_heavy_damage,
        plate=body.plate or "",
    )
    return asdict(val)


@router.post("/api/valuation/save", dependencies=[Depends(auth)])
def valuation_save_endpoint(body: VehicleValuationIn):
    with db_module.Session() as db:
        record = calculate_and_save_valuation(
            db,
            brand=body.brand,
            model=body.model,
            model_year=body.model_year,
            mileage_km=body.mileage_km,
            body_panels=body.body_panels,
            tramer_amount_tl=body.tramer_amount_tl,
            is_heavy_damage=body.is_heavy_damage,
            plate=body.plate or "",
            conversation_id=body.conversation_id,
            appointment_id=body.appointment_id,
        )
        return {**row(record), "estimate_basis": ESTIMATE_BASIS}


@router.post("/api/valuation/parse-spoken", dependencies=[Depends(auth)])
def valuation_parse_spoken_endpoint(body: SpokenValuationIn):
    parsed = parse_spoken_valuation_query(body.query_text)
    if parsed.get("missing_fields"):
        # Eksik bilgi varsa varsayılan araç uydurulmaz; değerleme hesaplanmaz
        raise HTTPException(
            422,
            detail={
                "message": "Değerleme için eksik bilgi var",
                "missing_fields": parsed["missing_fields"],
                "parsed_query": parsed,
            },
        )
    val = calculate_dynamic_valuation(
        brand=parsed["brand"],
        model=parsed["model"],
        model_year=parsed["model_year"],
        mileage_km=parsed["mileage_km"],
        body_panels=parsed.get("body_panels", {}),
        tramer_amount_tl=parsed.get("tramer_amount_tl", 0.0),
        is_heavy_damage=parsed.get("is_heavy_damage", False),
        plate=body.plate or "",
    )
    res = asdict(val)
    res["parsed_query"] = parsed
    return res


@router.get("/api/valuation/valuations", dependencies=[Depends(auth)])
def valuation_list_endpoint(limit: int = 50):
    with db_module.Session() as db:
        records = list_vehicle_valuations(db, limit=limit)
        return [row(r) for r in records]


@router.post("/api/corporate-accounts", dependencies=[Depends(auth)])
def create_corporate_account(body: CorporateAccountIn):
    with db_module.Session() as db:
        acc = CorporateAccount(**body.model_dump())
        db.add(acc)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(
                409, "Bu vergi numarası ile kayıtlı bir hesap zaten var"
            )
        return row(acc)


@router.get("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def get_corporate_account(id: str):
    with db_module.Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        return row(acc)


@router.put("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def update_corporate_account(id: str, body: CorporateAccountUpdateIn):
    with db_module.Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        for field, val in body.model_dump(exclude_unset=True).items():
            setattr(acc, field, val)
        db.commit()
        return row(acc)


@router.delete("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def delete_corporate_account(id: str):
    with db_module.Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        has_appointments = db.scalars(
            select(Appointment).where(Appointment.corporate_account_id == id)
        ).first()
        if has_appointments:
            raise HTTPException(
                409, "Bağlı randevusu olan kurumsal cari hesap silinemez"
            )
        db.delete(acc)
        db.commit()
        return {"deleted": True, "id": id}


@router.get("/api/corporate-accounts/{id}/ledger", dependencies=[Depends(auth)])
def get_corporate_ledger(id: str):
    with db_module.Session() as db:
        if not db.get(CorporateAccount, id):
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        entries = db.scalars(
            select(CorporateLedger)
            .where(CorporateLedger.account_id == id)
            .order_by(CorporateLedger.created_at)
        ).all()
        return [row(e) for e in entries]


@router.post("/api/corporate-accounts/{id}/payments", dependencies=[Depends(auth)])
def add_corporate_payment(id: str, body: PaymentIn):
    with db_module.Session() as db:
        try:
            ledger_entry = record_payment(
                db,
                account_id=id,
                amount_kurus=body.amount_kurus,
                description=body.description,
            )
            return row(ledger_entry)
        except ValueError as e:
            raise HTTPException(422, str(e))


@router.post("/api/vehicles", dependencies=[Depends(auth)])
def vehicle(body: VehicleIn):
    if body.vin:
        try:
            body.vin = validate_vin(body.vin)
        except ValueError as e:
            raise HTTPException(422, str(e))
    with db_module.Session() as db:
        x = Vehicle(**body.model_dump())
        db.add(x)
        db.commit()
        models.invalidate_hotwords()
        return row(x)


@router.put("/api/vehicles/{id}", dependencies=[Depends(auth)])
def update_vehicle(id: str, body: VehicleUpdateIn):
    with db_module.Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        if body.description is not None:
            v.description = body.description
        if body.plate is not None:
            v.plate = body.plate
        if body.vin is not None:
            try:
                v.vin = validate_vin(body.vin) if body.vin else ""
            except ValueError as e:
                raise HTTPException(422, str(e))
        db.commit()
        models.invalidate_hotwords()
        return row(v)


@router.delete("/api/vehicles/{id}", dependencies=[Depends(auth)])
def delete_vehicle(id: str):
    with db_module.Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        has_appointments = db.scalars(
            select(Appointment).where(Appointment.vehicle_id == id)
        ).first()
        if has_appointments:
            raise HTTPException(409, "Bağlı randevusu bulunan araç silinemez")
        quote = db.scalars(select(Quote).where(Quote.vehicle_id == id)).first()
        if quote:
            db.delete(quote)
        db.delete(v)
        db.commit()
        models.invalidate_hotwords()
        return {"deleted": True, "id": id}


@router.get("/api/vehicles/by-vin/{vin}", dependencies=[Depends(auth)])
def get_vehicle_by_vin(vin: str):
    try:
        clean_vin = validate_vin(vin)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with db_module.Session() as db:
        v = db.scalars(select(Vehicle).where(Vehicle.vin == clean_vin)).first()
        if not v:
            raise HTTPException(404, "Bu şase numarasına ait araç bulunamadı")
        inspections = db.scalars(
            select(InspectionReport)
            .where(InspectionReport.vehicle_id == v.id)
            .order_by(InspectionReport.inspected_at.desc())
        ).all()
        return {
            "vehicle": row(v),
            "inspections": [row(i) for i in inspections],
            "inspection_count": len(inspections),
        }


@router.get("/api/vehicles/{id}/inspections", dependencies=[Depends(auth)])
def get_vehicle_inspections(id: str):
    with db_module.Session() as db:
        if not db.get(Vehicle, id):
            raise HTTPException(404, "Araç bulunamadı")
        reports = db.scalars(
            select(InspectionReport)
            .where(InspectionReport.vehicle_id == id)
            .order_by(InspectionReport.inspected_at.desc())
        ).all()
        return [row(r) for r in reports]


@router.post("/api/vehicles/{id}/inspections", dependencies=[Depends(auth)])
def add_vehicle_inspection(id: str, body: InspectionReportIn):
    with db_module.Session() as db:
        vehicle = db.get(Vehicle, id)
        if not vehicle:
            raise HTTPException(404, "Araç bulunamadı")
        appointment = None
        if body.appointment_id:
            appointment = db.get(Appointment, body.appointment_id)

        report = InspectionReport(
            vehicle_id=id,
            appointment_id=body.appointment_id,
            technician_name=body.technician_name,
            summary=body.summary,
            mileage_km=body.mileage_km,
            score=body.score,
            findings_json=json.dumps(body.findings, ensure_ascii=False),
            photos_json=json.dumps(body.photos, ensure_ascii=False),
        )
        db.add(report)
        db.flush()

        pdf_dir = settings.data_dir / "inspections" / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_dir / f"{report.id}.pdf"
        try:
            generate_inspection_pdf(report, vehicle, appointment, output_path=pdf_file)
            report.pdf_path = str(pdf_file)
        except Exception:
            report.pdf_path = None

        db.commit()
        return row(report)


@router.get("/api/inspections/{id}/pdf")
def get_inspection_pdf(
    id: str,
    exp: str | None = None,
    sig: str | None = None,
    credentials: HTTPBasicCredentials | None = Depends(optional_security),
):
    # Basic auth VEYA geçerli (süresi dolmamış) imzalı bağlantı gerekir.
    if not verify_signed_link(id, exp, sig):
        if credentials is None:
            raise HTTPException(
                401, "Kimlik doğrulama veya imzalı bağlantı gerekli",
                headers={"WWW-Authenticate": "Basic"},
            )
        auth(credentials)
    with db_module.Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        if not vehicle:
            raise HTTPException(404, "İlişkili araç bulunamadı")
        appointment = (
            db.get(Appointment, report.appointment_id)
            if report.appointment_id
            else None
        )

        pdf_bytes = None
        if report.pdf_path and Path(report.pdf_path).is_file():
            try:
                pdf_bytes = Path(report.pdf_path).read_bytes()
            except Exception:
                pdf_bytes = None

        if not pdf_bytes:
            pdf_bytes = generate_inspection_pdf(report, vehicle, appointment)

        filename = f"ekspertiz_{vehicle.plate or id[:8]}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )


@router.get("/api/inspections/{id}/signed-link", dependencies=[Depends(auth)])
def get_inspection_signed_link(id: str):
    with db_module.Session() as db:
        if not db.get(InspectionReport, id):
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
    return {"url": signed_pdf_path(id)}


@router.post("/api/inspections/{id}/send-link", dependencies=[Depends(auth)])
def send_inspection_link(id: str):
    with db_module.Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        if not vehicle:
            raise HTTPException(404, "İlişkili araç bulunamadı")
        appointment = (
            db.get(Appointment, report.appointment_id)
            if report.appointment_id
            else None
        )

        queued = queue_inspection_delivery_notifications(
            db,
            report=report,
            vehicle=vehicle,
            appointment=appointment,
        )
        db.commit()

        dispatched = dispatch_pending_notifications(db)
        # Teslim durumu yalnızca bu rapora ait bildirimlerin gerçek sonucundan çıkar.
        mine = db.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key.in_(
                    (f"notif-insp-cust-{id}", f"notif-insp-corp-{id}")
                )
            )
        ).all()
        statuses = {n.status for n in mine}
        if "sent" in statuses:
            delivery = "delivered"
            report.delivered_at = datetime.now(timezone.utc).isoformat()
            db.commit()
        elif "simulated" in statuses:
            # Bildirim sağlayıcısı yok (mock): mesaj gönderilmedi, "delivered" denmez.
            delivery = "simulated"
        else:
            delivery = "queued"
        return {
            "status": delivery,
            "delivered_at": report.delivered_at,
            "url": signed_pdf_path(report.id),
            "notifications_queued": len(queued),
            "notifications_dispatched": len(dispatched),
        }


@router.post("/api/inspections/photos", dependencies=[Depends(auth)])
async def upload_inspection_photo(
    file: UploadFile = File(...),
    caption: str = Form(""),
    category: str = Form("Genel"),
):
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            400,
            f"Desteklenmeyen görsel formatı ({ext}). İzin verilenler: {', '.join(sorted(allowed))}",
        )

    photos_dir = settings.data_dir / "inspections" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{secrets.token_hex(8)}{ext}"
    out_file = photos_dir / fname

    # Sınır, dosyanın tamamı belleğe alınmadan parça parça denetlenir (413).
    content = await read_upload_capped(file, MAX_IMAGE_BYTES)

    out_file.write_bytes(content)
    return {
        "url": f"/api/inspections/photos/{fname}",
        "filename": fname,
        "caption": caption or (file.filename or "Fotoğraf"),
        "category": category or "Genel",
    }


@router.get("/api/inspections/photos/{filename}")
def get_inspection_photo(filename: str):
    clean_name = Path(filename).name
    photo_file = settings.data_dir / "inspections" / "photos" / clean_name
    if not photo_file.is_file():
        raise HTTPException(404, "Fotoğraf bulunamadı")
    return FileResponse(str(photo_file))


@router.post("/api/technician/dictate-text", dependencies=[Depends(auth)])
def technician_dictate_text(body: DictationTextIn):
    result = parse_technician_dictation(body.text)
    report_dict = None
    with db_module.Session() as db:
        if body.report_id:
            try:
                rep = apply_dictation_to_report(
                    db,
                    report_id=body.report_id,
                    findings=result["findings"],
                    summary=result["generated_summary"],
                    score=result["calculated_score"],
                )
                report_dict = row(rep)
            except ValueError as e:
                raise HTTPException(404, str(e))
        elif body.vehicle_id:
            vehicle = db.get(Vehicle, body.vehicle_id)
            if not vehicle:
                raise HTTPException(404, "Araç bulunamadı")
            if result["calculated_score"] is None:
                raise HTTPException(422, "Dikte metninde değerlendirilebilir bulgu yok; rapor oluşturulmadı")
            rep = InspectionReport(
                vehicle_id=body.vehicle_id,
                technician_name=body.technician_name or "Uzman Teknisyen",
                summary=result["generated_summary"],
                score=result["calculated_score"],
                findings_json=json.dumps(result["findings"], ensure_ascii=False),
            )
            db.add(rep)
            db.flush()
            pdf_dir = settings.data_dir / "inspections" / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_file = pdf_dir / f"{rep.id}.pdf"
            try:
                generate_inspection_pdf(rep, vehicle, output_path=pdf_file)
                rep.pdf_path = str(pdf_file)
            except Exception:
                rep.pdf_path = None
            db.commit()
            report_dict = row(rep)

    return {
        **result,
        "report": report_dict,
    }


@router.post("/api/technician/dictate-audio", dependencies=[Depends(auth)])
async def technician_dictate_audio(
    file: UploadFile = File(...),
    report_id: str | None = Form(None),
    vehicle_id: str | None = Form(None),
    technician_name: str | None = Form("Uzman Teknisyen"),
):
    content = await read_upload_capped(file, MAX_AUDIO_BYTES)
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    transcribed_text = ""
    try:
        import io
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

        if models.stt:
            transcribed_text = await models.transcribe(audio_data)
        else:
            transcribed_text = ""
    except Exception as e:
        logger.warning(f"Ses transkripsiyonu hatası: {e}")
        transcribed_text = ""

    result = parse_technician_dictation(transcribed_text)
    report_dict = None
    with db_module.Session() as db:
        if report_id:
            try:
                rep = apply_dictation_to_report(
                    db,
                    report_id=report_id,
                    findings=result["findings"],
                    summary=result["generated_summary"],
                    score=result["calculated_score"],
                )
                report_dict = row(rep)
            except ValueError as e:
                raise HTTPException(404, str(e))
        elif vehicle_id:
            vehicle = db.get(Vehicle, vehicle_id)
            if not vehicle:
                raise HTTPException(404, "Araç bulunamadı")
            if result["calculated_score"] is None:
                raise HTTPException(422, "Dikte metninde değerlendirilebilir bulgu yok; rapor oluşturulmadı")
            rep = InspectionReport(
                vehicle_id=vehicle_id,
                technician_name=technician_name or "Uzman Teknisyen",
                summary=result["generated_summary"],
                score=result["calculated_score"],
                findings_json=json.dumps(result["findings"], ensure_ascii=False),
            )
            db.add(rep)
            db.flush()
            pdf_dir = settings.data_dir / "inspections" / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_file = pdf_dir / f"{rep.id}.pdf"
            try:
                generate_inspection_pdf(rep, vehicle, output_path=pdf_file)
                rep.pdf_path = str(pdf_file)
            except Exception:
                rep.pdf_path = None
            db.commit()
            report_dict = row(rep)

    return {
        "transcribed_text": transcribed_text,
        **result,
        "report": report_dict,
    }


@router.post("/api/quotes", dependencies=[Depends(auth)])
def quote(body: QuoteIn):
    with db_module.Session() as db:
        if not db.get(Vehicle, body.vehicle_id):
            raise HTTPException(404, "Araç bulunamadı")
        x = db.scalars(select(Quote).where(Quote.vehicle_id == body.vehicle_id)).first()
        if x:
            x.amount_kurus = body.amount_kurus
        else:
            x = Quote(**body.model_dump())
            db.add(x)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Fiyat eşzamanlı güncellendi; tekrar deneyin")
        return row(x)


@router.post("/api/slots", dependencies=[Depends(auth)])
def slot(body: SlotIn):
    now_utc = datetime.now(timezone.utc)
    slot_start = body.starts_at.astimezone(timezone.utc)
    if slot_start <= now_utc:
        raise HTTPException(422, "Gelecek tarih gerekli")
    slot_end = slot_start + timedelta(minutes=body.duration_minutes)
    with db_module.Session() as db:
        existing_slots = db.scalars(select(Slot)).all()
        for s in existing_slots:
            try:
                s_start = datetime.fromisoformat(s.starts_at)
                if s_start.tzinfo is None:
                    s_start = s_start.replace(tzinfo=timezone.utc)
                s_dur = getattr(s, "duration_minutes", 30) or 30
                s_end = s_start + timedelta(minutes=s_dur)
                if slot_start < s_end and slot_end > s_start:
                    raise HTTPException(
                        409, "Bu zaman aralığında çakışan bir randevu saati mevcut"
                    )
            except (ValueError, TypeError):
                continue
        x = Slot(
            starts_at=slot_start.isoformat(),
            duration_minutes=body.duration_minutes,
        )
        db.add(x)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Saat zaten var")
        return row(x)


@router.post("/api/appointments", dependencies=[Depends(auth)])
def appointment(body: BookingIn):
    with db_module.Session() as db:
        try:
            return row(book(db, **body.model_dump()))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except IntegrityError:
            raise HTTPException(409, "Saat dolu")


@router.post("/api/appointments/{id}/cancel", dependencies=[Depends(auth)])
def cancel(id: UUID):
    id = str(id)
    with db_module.Session() as db:
        x = db.get(Appointment, id)
        if not x:
            raise HTTPException(404)
        cancel_appointment(db, x)
        return row(x)


@router.get("/api/conversations/{id}", dependencies=[Depends(auth)])
def detail(id: UUID):
    id = str(id)
    with db_module.Session() as db:
        if not db.get(Conversation, id):
            raise HTTPException(404)
        return [
            row(t)
            for t in db.scalars(
                select(Turn).where(Turn.conversation_id == id).order_by(Turn.created_at)
            ).all()
        ]


@router.delete("/api/conversations/{id}", dependencies=[Depends(auth)])
def delete(id: UUID):
    id = str(id)
    # "Aktif görüşme" = en az bir oturum var (locked() yalnızca kapasite dolunca True olur).
    if active.active_count > 0:
        raise HTTPException(409, "Aktif görüşme sırasında silinemez")
    with db_module.Session() as db:
        x = db.get(Conversation, id)
        if x:
            db.delete(x)
            db.commit()
    (settings.data_dir / "recordings" / f"{id}.wav").unlink(missing_ok=True)
    return {"deleted": True}


@router.get("/api/conversations/{id}/export", dependencies=[Depends(auth)])
def export_conversation(id: UUID, format: str = "json"):
    id_str = str(id)
    with db_module.Session() as db:
        c = db.get(Conversation, id_str)
        if not c:
            raise HTTPException(404, "Görüşme bulunamadı")
        turns = db.scalars(
            select(Turn).where(Turn.conversation_id == id_str).order_by(Turn.created_at)
        ).all()
        turn_data = []
        for t in turns:
            try:
                metrics_dict = json.loads(t.metrics) if t.metrics else {}
            except Exception:
                metrics_dict = {}
            turn_data.append(
                {
                    "id": t.id,
                    "role": t.role,
                    "text": t.text,
                    "metrics": metrics_dict,
                    "created_at": t.created_at,
                }
            )
        if format.lower() == "csv":
            import csv

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "conversation_id",
                    "turn_id",
                    "created_at",
                    "role",
                    "text",
                    "metrics_json",
                ]
            )
            for td in turn_data:
                writer.writerow(
                    [
                        id_str,
                        td["id"],
                        td["created_at"],
                        td["role"],
                        td["text"],
                        json.dumps(td["metrics"], ensure_ascii=False),
                    ]
                )
            return Response(
                content=output.getvalue().encode("utf-8-sig"),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="conversation_{id_str}.csv"'
                },
            )
        else:
            export_payload = {
                "conversation": row(c),
                "turns": turn_data,
                "turn_count": len(turn_data),
            }
            return Response(
                content=json.dumps(export_payload, ensure_ascii=False, indent=2),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="conversation_{id_str}.json"'
                },
            )
