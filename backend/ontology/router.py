"""
FreyaTTS Automotive Cockpit — Ontology REST API Endpoints
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
"""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.deps import auth
from backend.ontology.grounding import (
    CERTIFIED_DIAGNOSTIC_FAULTS,
    CERTIFIED_VEHICLE_CATALOG,
    AutomotiveGroundingEngine,
)
from backend.ontology.introspector import DatabaseIntrospector
from backend.ontology.mcp_server import AutomotiveOntologyMCPAdapter
from backend.ontology.models import (
    DiagnosticFaultConcept,
    OntologySchemaGraph,
    OntologyValidationRequest,
    OntologyValidationResult,
    ServicePackageConcept,
    VehicleConcept,
)

router = APIRouter(prefix="/api/ontology", tags=["Automotive Ontology"], dependencies=[Depends(auth)])


@router.get("/schema", response_model=OntologySchemaGraph)
def get_ontology_schema() -> OntologySchemaGraph:
    """
    Veritabanı şemasını ve semantik iş kavramlarını graf yapısında döner (Discover adımı).
    """
    return DatabaseIntrospector.introspect_schema()


@router.get("/packages", response_model=List[ServicePackageConcept])
def get_certified_packages() -> List[ServicePackageConcept]:
    """
    Sertifikalı ekspertiz paketleri ve fiyatlandırma sözleşmesini döner (Single Source of Truth).
    """
    return AutomotiveGroundingEngine.get_service_packages()


@router.get("/diagnostics", response_model=List[DiagnosticFaultConcept])
def get_certified_diagnostics(
    query: str = Query(default="", description="Arıza kodu veya semptom filtresi")
) -> List[DiagnosticFaultConcept]:
    """
    Sertifikalı OBD-II arıza kodları ve ikaz lambası ontolojisini döner.
    """
    if query:
        return AutomotiveGroundingEngine.diagnose_symptom(query)
    return list(CERTIFIED_DIAGNOSTIC_FAULTS.values())


@router.get("/vehicles", response_model=List[VehicleConcept])
def get_certified_vehicles() -> List[VehicleConcept]:
    """
    Katalogdaki standart referans araç modellerini döner.
    """
    return CERTIFIED_VEHICLE_CATALOG


@router.post("/resolve-vehicle")
def resolve_vehicle(body: Dict[str, str]) -> Dict[str, Any]:
    """
    Doğal dille söylenmiş araç metnini sertifikalı araç ontolojisine eşler.
    """
    user_text = body.get("user_text", "")
    if not user_text:
        raise HTTPException(status_code=400, detail="'user_text' parametresi zorunludur.")
    res = AutomotiveGroundingEngine.resolve_vehicle(user_text)
    if res:
        return {"matched": True, "vehicle": res.model_dump()}
    return {"matched": False, "message": "Eşleşen standart araç modeli bulunamadı."}


@router.post("/validate-action", response_model=OntologyValidationResult)
def validate_action(req: OntologyValidationRequest) -> OntologyValidationResult:
    """
    Agent veya Supervisor tarafından planlanan veritabanı eylemini ontoloji kurallarıyla doğrular (Guardrail).
    """
    return AutomotiveGroundingEngine.validate_action(req)


@router.get("/mcp/tools")
def get_mcp_tools() -> Dict[str, Any]:
    """
    NVIDIA Auto-Ontology standardına uygun MCP araç şemalarını listeler.
    """
    return {"tools": AutomotiveOntologyMCPAdapter.get_tool_definitions()}


@router.post("/mcp/execute")
def execute_mcp_tool(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    MCP üzerinden gelen araç çağrısını güvenli bir şekilde yürütür.
    """
    tool_name = body.get("name")
    arguments = body.get("arguments", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="'name' alanı zorunludur.")
    try:
        result = AutomotiveOntologyMCPAdapter.execute_tool(tool_name, arguments)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
