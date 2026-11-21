"""
FreyaTTS Automotive Cockpit — Automotive Ontology Data Models
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR

NVIDIA Auto-Ontology mimarisinden esinlenilmiş semantik kavram, ilişki ve
iş kuralı veri sözleşmeleri.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OntologyNodeType(str, Enum):
    TABLE = "table"
    CONCEPT = "concept"
    METRIC = "metric"
    RULE = "rule"


class RelationType(str, Enum):
    FOREIGN_KEY = "foreign_key"
    OWNS = "owns"
    HAS_FAULT = "has_fault"
    REQUIRES_PACKAGE = "requires_package"
    ASSIGNED_TO = "assigned_to"
    DEFINES_PRICE = "defines_price"
    VALIDATES_WITH = "validates_with"
    CONSTRAINED_BY = "constrained_by"


class OntologyNode(BaseModel):
    id: str
    name: str
    type: OntologyNodeType
    domain: str = "automotive"
    description: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    is_certified: bool = True


class OntologyEdge(BaseModel):
    source: str
    target: str
    relation: RelationType
    description: str = ""
    is_required: bool = False


class OntologySchemaGraph(BaseModel):
    version: str = "1.0.0"
    generated_at: str
    database_type: str = "sqlite"
    table_count: int
    concept_count: int
    nodes: List[OntologyNode]
    edges: List[OntologyEdge]


class VehicleConcept(BaseModel):
    brand: str
    model: str
    submodel: Optional[str] = None
    engine_type: str = "Benzin/Dizel"
    year_range: str = "2010–2025"
    segment: str = "C"
    normalized_name: str
    aliases: List[str] = Field(default_factory=list)


class ServicePackageConcept(BaseModel):
    package_id: str
    name: str
    price_tl: int
    duration_min: int
    description: str
    included_checks: List[str]
    recommended_for: List[str]


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DiagnosticFaultConcept(BaseModel):
    obd_code: str
    system: str
    warning_light: str
    severity: DiagnosticSeverity
    description: str
    common_symptoms: List[str]
    suggested_action: str
    recommended_package_id: str


class OntologyValidationRequest(BaseModel):
    action_type: str  # e.g., "create_booking", "reschedule_booking", "quote_price", "diagnose_fault"
    payload: Dict[str, Any]
    strict_mode: bool = True


class OntologyValidationResult(BaseModel):
    valid: bool
    action_type: str
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    certified_payload: Dict[str, Any] = Field(default_factory=dict)
    policy_reference: str = "Freya-Auto-Ontology-v1"

