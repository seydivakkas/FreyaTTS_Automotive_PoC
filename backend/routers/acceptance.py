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

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend import db as db_module
from backend.acceptance_protocol import (
    ACCEPTANCE_SCENARIOS,
    finish_and_verify_run,
    get_prerequisites_status,
    list_runs,
    load_run,
    mask_acceptance_report,
    prepare_poc_acceptance_fixtures,
    start_acceptance_run,
)
from backend.automotive_terminology import (
    canonicalize_asr_text,
    match_catalog_vehicle,
    run_terminology_verification_suite,
)
from backend.db import Vehicle
from backend.deps import auth
from backend.text import normalize
from backend.turkish_plate import TurkishPlateParser, extract_plate

router = APIRouter()


class AcceptancePrepareIn(BaseModel):
    reset_existing: bool = False


class AcceptanceStartIn(BaseModel):
    scenario_id: Literal[
        "run_1_plate_correction",
        "run_2_early_confirm_abort",
        "run_3_natural_idempotency",
    ]
    speaker_label: str = Field(default="", max_length=80)
    environment: Literal["quiet_room", "in_car_noise", "telephony_pbx", "virtual_mic"] = "quiet_room"
    notes: str = Field(default="", max_length=400)
    channel: Literal["web_mic", "asterisk", "text_input"] = "web_mic"


class TerminologyTestIn(BaseModel):
    asr_text: str = Field(default="", max_length=1000)
    tts_text: str = Field(default="", max_length=1000)
    base_plate: Optional[str] = Field(default=None, max_length=24)


@router.get("/api/acceptance/prerequisites", dependencies=[Depends(auth)])
def acceptance_prerequisites():
    with db_module.Session() as db:
        return get_prerequisites_status(db)


@router.post("/api/acceptance/prepare-fixtures", dependencies=[Depends(auth)])
def acceptance_prepare_fixtures(body: AcceptancePrepareIn):
    with db_module.Session() as db:
        return prepare_poc_acceptance_fixtures(db, reset_existing=body.reset_existing)


@router.get("/api/acceptance/scenarios", dependencies=[Depends(auth)])
def acceptance_scenarios():
    return {"scenarios": list(ACCEPTANCE_SCENARIOS.values())}


@router.get("/api/acceptance/runs", dependencies=[Depends(auth)])
def acceptance_list_runs(limit: int = Query(30, ge=1, le=100)):
    return {"runs": list_runs(limit=limit)}


@router.post("/api/acceptance/runs/start", dependencies=[Depends(auth)])
def acceptance_start_run(body: AcceptanceStartIn):
    with db_module.Session() as db:
        try:
            return start_acceptance_run(
                db,
                scenario_id=body.scenario_id,
                speaker_label=body.speaker_label,
                environment=body.environment,
                notes=body.notes,
                channel=body.channel,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.post("/api/acceptance/runs/{run_id}/verify", dependencies=[Depends(auth)])
def acceptance_verify_run(run_id: str):
    with db_module.Session() as db:
        try:
            return finish_and_verify_run(db, run_id)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.get("/api/acceptance/runs/{run_id}", dependencies=[Depends(auth)])
def acceptance_get_run(run_id: str, masked: bool = Query(False)):
    report = load_run(run_id)
    if report is None:
        raise HTTPException(404, f"Kabul koşusu bulunamadı: {run_id}")
    return mask_acceptance_report(report) if masked else report


@router.get("/api/acceptance/terminology/audit", dependencies=[Depends(auth)])
def acceptance_terminology_audit():
    with db_module.Session() as db:
        return run_terminology_verification_suite(db=db)


@router.post("/api/acceptance/terminology/test", dependencies=[Depends(auth)])
def acceptance_terminology_test(body: TerminologyTestIn):
    asr_res = None
    tts_res = None

    if body.asr_text.strip():
        canon = canonicalize_asr_text(body.asr_text)
        with db_module.Session() as db:
            vehicles = db.scalars(select(Vehicle)).all()
            cat_match = match_catalog_vehicle(vehicles, body.asr_text)
        plate_parsed = (
            extract_plate(canon["canonical_text"] or body.asr_text)
            or extract_plate(body.asr_text)
        )
        plate_corr = None
        if body.base_plate:
            c = TurkishPlateParser.correct_plate(body.base_plate, body.asr_text)
            if c and c.is_correction:
                plate_corr = {
                    "plate": c.plate,
                    "correction_target": c.correction_target,
                }
        asr_res = {
            **canon,
            "plate_parsed": plate_parsed,
            "plate_correction": plate_corr,
            "catalog_match": (
                {
                    "id": cat_match["matched_vehicle"].id,
                    "description": cat_match["matched_vehicle"].description,
                }
                if cat_match["matched_vehicle"]
                else None
            ),
            "brand_only_detected": cat_match["brand_only_detected"],
        }

    if body.tts_text.strip():
        try:
            norm = normalize(body.tts_text)
            tts_res = {"ok": True, "normalized": norm["normalized"], "warnings": norm.get("warnings", [])}
        except ValueError as e:
            tts_res = {"ok": False, "error": str(e)}

    return {"inbound_asr": asr_res, "outbound_tts": tts_res}
