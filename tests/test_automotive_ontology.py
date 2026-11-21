"""
Tests for FreyaTTS Automotive Auto-Ontology Module
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.ontology.introspector import DatabaseIntrospector
from backend.ontology.grounding import AutomotiveGroundingEngine, CERTIFIED_SERVICE_PACKAGES
from backend.ontology.models import OntologyValidationRequest
from backend.ontology.mcp_server import AutomotiveOntologyMCPAdapter
from backend.config import settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    import base64
    pwd = settings.admin_password or "safak1"
    token = base64.b64encode(f"admin:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_introspect_schema():
    graph = DatabaseIntrospector.introspect_schema()
    assert graph.table_count >= 15
    assert graph.concept_count >= 3
    assert len(graph.nodes) >= 18
    assert len(graph.edges) >= 5

    # Check physical tables
    table_names = [n.name for n in graph.nodes if n.type == "table"]
    assert "vehicles" in table_names
    assert "appointments" in table_names
    assert "inspection_reports" in table_names

    # Check concepts
    concept_names = [n.id for n in graph.nodes if n.type == "concept"]
    assert "concept:service_packages" in concept_names
    assert "concept:diagnostic_faults" in concept_names
    assert "concept:vehicle_catalog" in concept_names


def test_service_packages_single_source_of_truth():
    packages = AutomotiveGroundingEngine.get_service_packages()
    assert len(packages) >= 4
    
    # Check pricing integrity
    pkg_p01 = AutomotiveGroundingEngine.get_package_by_id("P01_TEMEL")
    assert pkg_p01 is not None
    assert pkg_p01.price_tl == 950

    pkg_p02 = AutomotiveGroundingEngine.get_package_by_id("P02_STANDART")
    assert pkg_p02 is not None
    assert pkg_p02.price_tl == 1450

    pkg_p03 = AutomotiveGroundingEngine.get_package_by_id("P03_FULL")
    assert pkg_p03 is not None
    assert pkg_p03.price_tl == 1950

    pkg_p04 = AutomotiveGroundingEngine.get_package_by_id("P04_VIP")
    assert pkg_p04 is not None
    assert pkg_p04.price_tl == 2600

    # Test fuzzy name lookup
    assert AutomotiveGroundingEngine.get_package_by_name("kaporta muayenesi").package_id == "P01_TEMEL"
    assert AutomotiveGroundingEngine.get_package_by_name("tam kapsamlı dyno").package_id == "P03_FULL"
    assert AutomotiveGroundingEngine.get_package_by_name("vip yol testi").package_id == "P04_VIP"


def test_vehicle_concept_resolution():
    # Exact and alias matching
    res1 = AutomotiveGroundingEngine.resolve_vehicle("2019 model Volkswagen Passat dizel")
    assert res1 is not None
    assert res1.normalized_name == "Volkswagen Passat"

    res2 = AutomotiveGroundingEngine.resolve_vehicle("golf 7 1.4 tsi aracım var")
    assert res2 is not None
    assert res2.normalized_name == "Volkswagen Golf"

    res3 = AutomotiveGroundingEngine.resolve_vehicle("megan 4 sedan")
    assert res3 is not None
    assert res3.normalized_name == "Renault Megane"

    res4 = AutomotiveGroundingEngine.resolve_vehicle("bilinmeyen uzay aracı")
    assert res4 is None


def test_diagnostic_fault_ontology():
    # Direct code match
    faults_p0300 = AutomotiveGroundingEngine.diagnose_symptom("P0300")
    assert len(faults_p0300) == 1
    assert faults_p0300[0].obd_code == "P0300"
    assert faults_p0300[0].severity.value == "high"
    assert faults_p0300[0].recommended_package_id == "P03_FULL"

    # Symptom match
    faults_airbag = AutomotiveGroundingEngine.diagnose_symptom("airbag lambası")
    assert any(f.obd_code == "B0001" for f in faults_airbag)

    faults_turbo = AutomotiveGroundingEngine.diagnose_symptom("çekiş düşüklüğü turbo")
    assert any(f.obd_code == "P0299" for f in faults_turbo)


def test_action_validation_guardrails():
    # 1. Valid booking request
    valid_req = OntologyValidationRequest(
        action_type="create_booking",
        payload={
            "customer_name": "Ahmet Yılmaz",
            "customer_phone": "05321234567",
            "vehicle_text": "Volkswagen Passat",
            "package_name": "Tam Kapsamlı",
            "slot_id": "slot-2026-11-14-1000",
        },
    )
    res_valid = AutomotiveGroundingEngine.validate_action(valid_req)
    assert res_valid.valid is True
    assert res_valid.certified_payload["price_tl"] == 1950
    assert res_valid.certified_payload["package_id"] == "P03_FULL"
    assert res_valid.certified_payload["vehicle_model"] == "Volkswagen Passat"

    # 2. Invalid booking request (missing phone, short name)
    invalid_req = OntologyValidationRequest(
        action_type="create_booking",
        payload={
            "customer_name": "A",
            "customer_phone": "123",
            "vehicle_text": "Passat",
        },
    )
    res_invalid = AutomotiveGroundingEngine.validate_action(invalid_req)
    assert res_invalid.valid is False
    assert len(res_invalid.errors) >= 2

    # 3. Reschedule without new slot (fails atomic reschedule rule)
    resched_req = OntologyValidationRequest(
        action_type="reschedule_booking",
        payload={"appointment_id": 42, "customer_phone": "05321234567"},
    )
    res_resched = AutomotiveGroundingEngine.validate_action(resched_req)
    assert res_resched.valid is False
    assert any("Atomik Erteleme" in e for e in res_resched.errors)


def test_mcp_adapter_tools():
    tools = AutomotiveOntologyMCPAdapter.get_tool_definitions()
    assert len(tools) == 5
    tool_names = [t["name"] for t in tools]
    assert "ontology_get_schema_summary" in tool_names
    assert "ontology_get_service_packages" in tool_names
    assert "ontology_resolve_vehicle" in tool_names
    assert "ontology_diagnose_fault" in tool_names
    assert "ontology_validate_action" in tool_names

    # Test MCP tool execution
    res_schema = AutomotiveOntologyMCPAdapter.execute_tool("ontology_get_schema_summary", {})
    assert res_schema["table_count"] >= 15

    res_pkgs = AutomotiveOntologyMCPAdapter.execute_tool("ontology_get_service_packages", {})
    assert len(res_pkgs["packages"]) >= 4

    res_veh = AutomotiveOntologyMCPAdapter.execute_tool("ontology_resolve_vehicle", {"user_text": "egea multijet"})
    assert res_veh["found"] is True
    assert res_veh["vehicle"]["normalized_name"] == "Fiat Egea"


def test_ontology_rest_endpoints(client, auth_headers):
    # Schema endpoint
    resp_schema = client.get("/api/ontology/schema", headers=auth_headers)
    assert resp_schema.status_code == 200
    data_schema = resp_schema.json()
    assert data_schema["table_count"] >= 15
    assert len(data_schema["nodes"]) >= 18

    # Packages endpoint
    resp_pkgs = client.get("/api/ontology/packages", headers=auth_headers)
    assert resp_pkgs.status_code == 200
    pkgs = resp_pkgs.json()
    assert len(pkgs) >= 4
    assert any(p["package_id"] == "P03_FULL" for p in pkgs)

    # Diagnostics endpoint
    resp_diag = client.get("/api/ontology/diagnostics?query=P0300", headers=auth_headers)
    assert resp_diag.status_code == 200
    diag = resp_diag.json()
    assert len(diag) == 1
    assert diag[0]["obd_code"] == "P0300"

    # Resolve vehicle endpoint
    resp_veh = client.post("/api/ontology/resolve-vehicle", json={"user_text": "honda civic vtec"}, headers=auth_headers)
    assert resp_veh.status_code == 200
    assert resp_veh.json()["matched"] is True
    assert resp_veh.json()["vehicle"]["normalized_name"] == "Honda Civic"

    # Validate action endpoint
    resp_val = client.post(
        "/api/ontology/validate-action",
        json={
            "action_type": "create_booking",
            "payload": {
                "customer_name": "Mehmet Kaya",
                "customer_phone": "05559876543",
                "vehicle_text": "Toyota Corolla",
                "package_name": "Standart",
                "slot_id": "slot-1",
            },
        },
        headers=auth_headers,
    )
    assert resp_val.status_code == 200
    val_data = resp_val.json()
    assert val_data["valid"] is True
    assert val_data["certified_payload"]["price_tl"] == 1450

