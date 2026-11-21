"""
FreyaTTS Automotive Cockpit — Model Context Protocol (MCP) Adapter
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR

NVIDIA Auto-Ontology "Expose" adımı:
Otomotiv ontolojisini ve veri tabanı denetim kurallarını MCP uyumlu
araçlar (Tools) olarak sunar.
"""

from __future__ import annotations

from typing import Any, Dict, List
from backend.ontology.grounding import AutomotiveGroundingEngine
from backend.ontology.introspector import DatabaseIntrospector
from backend.ontology.models import OntologyValidationRequest


class AutomotiveOntologyMCPAdapter:
    """
    MCP (Model Context Protocol) standart araç tanımları ve yürütücüsü.
    """

    @classmethod
    def get_tool_definitions(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "ontology_get_schema_summary",
                "description": "Veritabanındaki fiziksel tabloları, semantik kavramları ve aralarındaki ilişkileri listeler.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "ontology_get_service_packages",
                "description": "Ekspertiz paketlerinin resmi ve sertifikalı tek gerçek kaynak fiyat, süre ve kapsamlarını döner.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "ontology_resolve_vehicle",
                "description": "Kullanıcının doğal dilde söylediği araç marka/modelini sertifikalı otomotiv ontolojisiyle eşler.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_text": {
                            "type": "string",
                            "description": "Kullanıcının sesli söylediği araç ifadesi (örn: 'golf 7 1.4 tsi', 'megan 4').",
                        }
                    },
                    "required": ["user_text"],
                },
            },
            {
                "name": "ontology_diagnose_fault",
                "description": "Araç göstergesindeki ikaz lambası veya mekanik arıza belirtisinden standart OBD-II kodunu ve önerilen paketi bulur.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symptom_or_code": {
                            "type": "string",
                            "description": "Arıza belirtisi veya OBD kodu (örn: 'motor arıza lambası sarı yanıyor', 'P0300', 'hava yastığı').",
                        }
                    },
                    "required": ["symptom_or_code"],
                },
            },
            {
                "name": "ontology_validate_action",
                "description": "AI ajanının veritabanında gerçekleştirmek istediği randevu veya fiyatlama işlemini ontoloji kurallarıyla doğrular.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "description": "İşlem tipi: 'create_booking', 'reschedule_booking', 'quote_price'.",
                        },
                        "payload": {
                            "type": "object",
                            "description": "İşlem parametreleri (customer_name, customer_phone, vehicle_model, slot_id vb.).",
                        },
                    },
                    "required": ["action_type", "payload"],
                },
            },
        ]

    @classmethod
    def execute_tool(cls, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gelen MCP araç çağrısını deterministik olarak icra eder.
        """
        if tool_name == "ontology_get_schema_summary":
            graph = DatabaseIntrospector.introspect_schema()
            return {
                "version": graph.version,
                "table_count": graph.table_count,
                "concept_count": graph.concept_count,
                "tables": [n.name for n in graph.nodes if n.type == "table"],
                "relationships_count": len(graph.edges),
            }

        elif tool_name == "ontology_get_service_packages":
            pkgs = AutomotiveGroundingEngine.get_service_packages()
            return {"packages": [p.model_dump() for p in pkgs]}

        elif tool_name == "ontology_resolve_vehicle":
            text = arguments.get("user_text", "")
            resolved = AutomotiveGroundingEngine.resolve_vehicle(text)
            if resolved:
                return {"found": True, "vehicle": resolved.model_dump()}
            return {"found": False, "message": f"'{text}' ifadesi standart katalogla eşleştirilemedi."}

        elif tool_name == "ontology_diagnose_fault":
            symptom = arguments.get("symptom_or_code", "")
            faults = AutomotiveGroundingEngine.diagnose_symptom(symptom)
            return {"count": len(faults), "matches": [f.model_dump() for f in faults]}

        elif tool_name == "ontology_validate_action":
            action_type = arguments.get("action_type", "")
            payload = arguments.get("payload", {})
            req = OntologyValidationRequest(action_type=action_type, payload=payload)
            res = AutomotiveGroundingEngine.validate_action(req)
            return res.model_dump()

        else:
            raise ValueError(f"Bilinmeyen MCP aracı: {tool_name}")
