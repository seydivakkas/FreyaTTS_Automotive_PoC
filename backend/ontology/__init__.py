"""
FreyaTTS Automotive Cockpit — Automotive Auto-Ontology Module
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
"""

from backend.ontology.grounding import (
    CERTIFIED_DIAGNOSTIC_FAULTS,
    CERTIFIED_SERVICE_PACKAGES,
    CERTIFIED_VEHICLE_CATALOG,
    AutomotiveGroundingEngine,
)
from backend.ontology.introspector import DatabaseIntrospector
from backend.ontology.mcp_server import AutomotiveOntologyMCPAdapter
from backend.ontology.models import (
    DiagnosticFaultConcept,
    OntologyEdge,
    OntologyNode,
    OntologyNodeType,
    OntologySchemaGraph,
    OntologyValidationRequest,
    OntologyValidationResult,
    RelationType,
    ServicePackageConcept,
    VehicleConcept,
)

__all__ = [
    "CERTIFIED_SERVICE_PACKAGES",
    "CERTIFIED_DIAGNOSTIC_FAULTS",
    "CERTIFIED_VEHICLE_CATALOG",
    "AutomotiveGroundingEngine",
    "DatabaseIntrospector",
    "AutomotiveOntologyMCPAdapter",
    "OntologyNode",
    "OntologyEdge",
    "OntologyNodeType",
    "RelationType",
    "OntologySchemaGraph",
    "VehicleConcept",
    "ServicePackageConcept",
    "DiagnosticFaultConcept",
    "OntologyValidationRequest",
    "OntologyValidationResult",
]

