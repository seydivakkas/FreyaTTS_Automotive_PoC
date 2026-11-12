import json
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.db import IntentTrainingCandidate, Session, SupervisorTrace
from backend.deps import auth
from backend.qa_telemetry_operator import m11_gate
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import CATALOGUE_VERSION
from backend.supervisor.quality import ReviewInput, apply_review
from backend.supervisor.views import conversation_view, queue_view

router = APIRouter(prefix="/api/supervisor", dependencies=[Depends(auth)])


@router.get("/fqici-queue")
def fqici_queue(response: Response, limit: int = Query(25, ge=1, le=100)):
    response.headers["Cache-Control"] = "no-store"
    with Session() as db:
        return {**queue_view(db, limit), "physical_sip_status": m11_gate.evaluate_acceptance()["overall_status"]}


@router.get("/conversations/{conversation_id}/detail")
def conversation_detail(conversation_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with Session() as db:
        result = conversation_view(db, str(conversation_id))
    if result is None:
        raise HTTPException(404, "Görüşme bulunamadı")
    return result


def read_report(kind: str) -> dict | None:
    path = settings.data_dir / "supervisor" / "evaluations" / kind / "manifest.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["catalogue_version"] != CATALOGUE_VERSION or report["kind"] != kind:
            return None
        return report
    except (OSError, ValueError, TypeError, KeyError):
        return None


def regression_status() -> dict:
    path = settings.data_dir / "supervisor" / "regression.xml"
    try:
        root = ElementTree.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        counts = {
            key: sum(int(suite.get(key, 0)) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        if counts["tests"] <= counts["skipped"]:
            return {"status": "NOT RUN"}
        return {"status": "FAIL" if counts["failures"] or counts["errors"] else "PASS", **counts}
    except (OSError, ValueError, ElementTree.ParseError):
        return {"status": "NOT RUN"}


@router.get("/quality")
def quality(
    queue: Literal["all", "pending"] = "all",
    limit: int = Query(50, ge=1, le=200),
    conversation_id: UUID | None = None,
):
    traces = []
    store = "READY"
    try:
        with Session() as db:
            statement = select(SupervisorTrace).order_by(SupervisorTrace.created_at.desc()).limit(limit)
            if queue == "pending":
                statement = statement.where(SupervisorTrace.review_status.in_(["PENDING", "NEEDS_MORE_EVIDENCE"]))
            if conversation_id is not None:
                statement = statement.where(SupervisorTrace.conversation_id == str(conversation_id))
            for row in db.scalars(statement):
                traces.append({
                    "trace_id": row.id, "conversation_id": row.conversation_id, "created_at": row.created_at,
                    "review_status": row.review_status,
                    "review_labels": json.loads(row.review_labels) if row.review_labels else None,
                    **json.loads(row.payload),
                })
    except SQLAlchemyError:
        store = "UNAVAILABLE"
    baseline = read_report("baseline")
    challenger = read_report("xgboost")
    comparable = baseline is not None and challenger is not None and all(
        baseline.get(key) is not None and baseline[key] == challenger.get(key)
        for key in ("dataset_sha256", "seed", "label_index")
    )
    return {
        "catalogue_version": CATALOGUE_VERSION, "mode": settings.supervisor_mode, "trace_store": store,
        "catalogue": [item.model_dump(mode="json") for item in CATALOGUE.values()],
        "traces": traces,
        "registry": {
            "approval_configured": bool(settings.supervisor_model_path and settings.supervisor_model_sha256),
            "fallback_enabled": settings.supervisor_llm_fallback,
        },
        "evaluation": {"baseline": baseline, "xgboost": challenger, "comparable": comparable},
        "software_regression": regression_status(),
        "physical_regression": "NOT RUN",
    }


@router.post("/review/{trace_id}")
def review(trace_id: UUID, data: dict):
    try:
        body = ReviewInput.model_validate(data)
        status = apply_review(trace_id, body)
    except ValidationError as exc:
        raise HTTPException(422, "İnceleme biçimi, izin veya anonimleştirme koşulu geçersiz") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Karar kaydı bulunamadı") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Supervisor kalite deposu hazır değil") from exc
    return {"review_status": status}


@router.get("/dataset")
def export_dataset():
    try:
        with Session() as db:
            examples = list(db.scalars(select(IntentTrainingCandidate.example).order_by(
                IntentTrainingCandidate.group_id, IntentTrainingCandidate.trace_id,
            )))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Supervisor kalite deposu hazır değil") from exc
    return StreamingResponse(
        (example + "\n" for example in examples), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="intent-reviewed.jsonl"'},
    )
