"""Operatör ve kalite (QA) uç noktaları."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Query,
    Response,
)
from backend.acoustic_evaluation import load_latest_report
from backend.db import Session
from backend.operator_inbox import today_view
from backend.qa_telemetry_operator import (
    realtime_turn_collector,
    operator_panel,
    abc_evaluator,
    m11_gate,
)
from backend.schemas import (
    OperatorRegisterCallIn,
    OperatorReleaseIn,
    OperatorTakeoverIn,
    OperatorWhisperIn,
    QAEvaluateVariantsIn,
)
from backend.deps import auth

router = APIRouter()


@router.get("/api/operator/today", dependencies=[Depends(auth)])
def operator_today(
    response: Response,
    period: Literal["all", "today", "carryover"] = "all",
    category: Literal["all", "transfer", "callback", "booking", "follow_up"] = "all",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    response.headers["Cache-Control"] = "no-store"
    with Session() as db:
        return today_view(db, now=datetime.now(timezone.utc), period=period, category=category, limit=limit, offset=offset)


# -----------------------------------------------------------------------------
# Ajan 7: Dağıtık Telemetri, Canlı Operatör Paneli ve Kalite Kapısı Endpoints
# -----------------------------------------------------------------------------

@router.post("/api/operator/register-call", dependencies=[Depends(auth)])
def operator_register_call(body: OperatorRegisterCallIn):
    sess = operator_panel.register_call(
        session_id=body.session_id,
        caller_id=body.caller_id,
        initial_turn_id=body.initial_turn_id,
        mos_score=body.mos_score,
        rtf=body.rtf,
    )
    return {"success": True, "session": sess.to_dict()}


@router.post("/api/operator/takeover", dependencies=[Depends(auth)])
def operator_takeover(body: OperatorTakeoverIn):
    res = operator_panel.takeover_call(
        session_id=body.session_id,
        operator_id=body.operator_id,
        reason=body.reason,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@router.post("/api/operator/whisper", dependencies=[Depends(auth)])
def operator_whisper(body: OperatorWhisperIn):
    res = operator_panel.whisper_to_agent(
        session_id=body.session_id,
        operator_id=body.operator_id,
        message=body.message,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@router.post("/api/operator/release", dependencies=[Depends(auth)])
def operator_release(body: OperatorReleaseIn):
    res = operator_panel.release_call(
        session_id=body.session_id,
        operator_id=body.operator_id,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@router.get("/api/operator/live-sessions", dependencies=[Depends(auth)])
def operator_live_sessions():
    return {"sessions": operator_panel.get_live_sessions()}


@router.post("/api/qa/evaluate-variants", dependencies=[Depends(auth)])
def qa_evaluate_variants(body: QAEvaluateVariantsIn):
    test_samples = body.samples
    if not test_samples:
        test_samples = [
            ("Bugün Peugeot 3008 için servis randevusu aldım.", "Bugün Pöjo üç bin sekiz için servis randevusu aldım."),
            ("Araç 1.6 PureTech 180 bg motora sahip.", "Araç bir nokta altı Pürtek yüz seksen beygir motora sahip."),
            ("Fiyat 1.250.000 TL olarak belirlendi.", "Fiyat bir milyon iki yüz elli bin Türk lirası olarak belirlendi."),
        ]
    return abc_evaluator.run_benchmark_suite(test_samples, acoustic_report=load_latest_report())


@router.get("/api/qa/telemetry/{turn_id}", dependencies=[Depends(auth)])
def qa_get_telemetry(turn_id: str):
    turn = realtime_turn_collector.get_turn(turn_id)
    if not turn:
        raise HTTPException(404, f"Turn telemetry not found for id: {turn_id}")
    return {
        "turn": turn.model_dump(),
        "opentelemetry_span": realtime_turn_collector.export_opentelemetry_span(turn_id),
    }


@router.get("/api/qa/m11-status", dependencies=[Depends(auth)])
def qa_m11_status(has_physical_pbx_trace: bool = False, has_hardware_trunk: bool = False):
    return m11_gate.evaluate_acceptance(
        has_physical_pbx_trace=has_physical_pbx_trace,
        has_hardware_trunk=has_hardware_trunk,
    )
