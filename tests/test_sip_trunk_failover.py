# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.

import base64
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.sip_trunk_failover import (
    SIPTrunk,
    SIPTrunkFailoverManager,
    TrunkStatus,
    build_sip_options_packet,
    parse_sip_response,
    sip_trunk_failover_manager,
)


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_manager() -> SIPTrunkFailoverManager:
    # Test için ENJEKTE edilen trunklar (üretim kodunda operatör/RTT uydurması yoktur)
    now = "2026-01-01T00:00:00+00:00"
    injected = [
        SIPTrunk(trunk_id="turk_telekom_trunk", name="Test Trunk A", host="sip.turktelekom.com.tr",
                 priority=1, weight=60, max_channels=30, status=TrunkStatus.HEALTHY,
                 rtt_ms=22.0, rtt_ema_ms=22.0, last_healthy_at=now),
        SIPTrunk(trunk_id="turkcell_superonline_trunk", name="Test Trunk B", host="sip.superonline.net",
                 priority=1, weight=30, max_channels=30, status=TrunkStatus.HEALTHY,
                 rtt_ms=18.0, rtt_ema_ms=18.0, last_healthy_at=now),
        SIPTrunk(trunk_id="vodafone_net_trunk", name="Test Trunk C", host="sip.vodafone.com.tr",
                 priority=2, weight=10, max_channels=20, status=TrunkStatus.HEALTHY,
                 rtt_ms=32.0, rtt_ema_ms=32.0, last_healthy_at=now),
    ]
    mgr = SIPTrunkFailoverManager(
        degraded_rtt_threshold_ms=150.0,
        down_rtt_threshold_ms=500.0,
        failure_threshold=2,
        recovery_success_target=2,
        trunks=injected,
    )
    return mgr


def test_default_trunk_is_configured_but_unverified(monkeypatch):
    # Üretim varsayılanı: yalnızca settings.ami_trunk, durum unknown, RTT null (uydurma operatör yok)
    monkeypatch.setattr(settings, "ami_trunk", "trunk-test")
    mgr = SIPTrunkFailoverManager()
    trunks = mgr.list_trunks()
    assert len(trunks) == 1
    t = trunks[0]
    assert t["trunk_id"] == "trunk-test"
    assert t["status"] == TrunkStatus.UNKNOWN.value
    assert t["rtt_ms"] is None
    assert t["last_healthy_at"] == ""
    assert "doğrulanmadı" in t["note"]
    # Host yok: yoklama yapılamaz, durum/RTT değişmez
    res = mgr.ping_trunk("trunk-test")
    assert res.success is False and res.rtt_ms is None
    assert mgr.get_trunk("trunk-test").status == TrunkStatus.UNKNOWN


def test_injected_trunks_loaded(test_manager: SIPTrunkFailoverManager):
    trunks = test_manager.list_trunks()
    assert len(trunks) == 3

    tt = test_manager.get_trunk("turk_telekom_trunk")
    assert tt is not None
    assert tt.priority == 1
    assert tt.weight == 60
    assert tt.status == TrunkStatus.HEALTHY

    turkcell = test_manager.get_trunk("turkcell_superonline_trunk")
    assert turkcell is not None
    assert turkcell.priority == 1
    assert turkcell.weight == 30

    vodafone = test_manager.get_trunk("vodafone_net_trunk")
    assert vodafone is not None
    assert vodafone.priority == 2
    assert vodafone.weight == 10


def test_build_and_parse_sip_options(test_manager: SIPTrunkFailoverManager):
    tt = test_manager.get_trunk("turk_telekom_trunk")
    assert tt is not None

    packet = build_sip_options_packet(tt, local_ip="192.168.1.10", local_port=5060)
    text = packet.decode("utf-8")
    assert "OPTIONS sip:sip.turktelekom.com.tr:5060 SIP/2.0" in text
    assert "Max-Forwards: 70" in text
    assert "User-Agent: FreyaTTS-Automotive/1.0" in text

    # Parse 200 OK
    resp_200 = b"SIP/2.0 200 OK\r\nVia: SIP/2.0/UDP 127.0.0.1:5060\r\nContent-Length: 0\r\n\r\n"
    code, msg = parse_sip_response(resp_200)
    assert code == 200
    assert msg == "OK"

    # Parse 401 Unauthorized
    resp_401 = b"SIP/2.0 401 Unauthorized\r\n\r\n"
    code401, msg401 = parse_sip_response(resp_401)
    assert code401 == 401
    assert msg401 == "Unauthorized"


def test_wrr_trunk_selection_priority1(test_manager: SIPTrunkFailoverManager):
    counts = {"turk_telekom_trunk": 0, "turkcell_superonline_trunk": 0, "vodafone_net_trunk": 0}

    for _ in range(150):
        sel = test_manager.select_best_trunk(destination_phone="05321234567")
        assert sel.priority == 1
        assert sel.is_failover is False
        assert "PJSIP/05321234567@" in sel.dial_channel
        counts[sel.trunk_id] += 1

    # Priority 2 trunk should NOT be selected when Priority 1 is healthy
    assert counts["vodafone_net_trunk"] == 0
    # Türk Telekom (weight 60) should have more calls than Turkcell (weight 30)
    assert counts["turk_telekom_trunk"] > counts["turkcell_superonline_trunk"]


def test_automatic_subsecond_failover_to_priority2(test_manager: SIPTrunkFailoverManager):
    # Simulate both Priority 1 carriers being DOWN (e.g. regional fiber cut)
    test_manager.simulate_trunk_outage("turk_telekom_trunk", outage=True)
    test_manager.simulate_trunk_outage("turkcell_superonline_trunk", outage=True)

    # Simülasyon açıkça etiketlenir
    assert test_manager.get_trunk("turk_telekom_trunk").simulated is True
    assert "SIMULATED" in test_manager.get_trunk("turk_telekom_trunk").last_error

    # Next call selection must instantly fail over to Priority 2 (Vodafone)
    sel = test_manager.select_best_trunk(destination_phone="05429876543")
    assert sel.trunk_id == "vodafone_net_trunk"
    assert sel.priority == 2
    assert sel.is_failover is True
    assert "yedek hatta geçildi" in sel.failover_reason


def test_active_call_capacity_limit_and_spillover(test_manager: SIPTrunkFailoverManager):
    tt = test_manager.get_trunk("turk_telekom_trunk")
    assert tt is not None
    tt.max_channels = 2
    tt.active_calls = 2  # At max capacity

    # Türk Telekom is full, so call should route to Turkcell
    sel = test_manager.select_best_trunk(destination_phone="05301112233")
    assert sel.trunk_id == "turkcell_superonline_trunk"


def test_failover_reroute_on_originate_error(test_manager: SIPTrunkFailoverManager):
    sel = test_manager.failover_reroute(
        failed_trunk_id="turk_telekom_trunk",
        destination_phone="05335554433",
        error_reason="503 Service Unavailable",
    )
    assert sel.trunk_id != "turk_telekom_trunk"
    assert sel.is_failover is True


def test_ping_trunk_state_machine(test_manager: SIPTrunkFailoverManager):
    tt = test_manager.get_trunk("turk_telekom_trunk")
    assert tt is not None

    # 1. High latency probe triggers DEGRADED
    test_manager.mock_probe_func = lambda t: (True, 180.0, 200, "OK")
    # Repeat ping to update EMA above 150 ms
    test_manager.ping_trunk("turk_telekom_trunk")
    test_manager.ping_trunk("turk_telekom_trunk")
    test_manager.ping_trunk("turk_telekom_trunk")
    assert tt.status == TrunkStatus.DEGRADED

    # 2. Failure probes trigger DOWN
    test_manager.mock_probe_func = lambda t: (False, None, 408, "Timeout")
    test_manager.ping_trunk("turk_telekom_trunk")
    assert tt.consecutive_failures == 1
    test_manager.ping_trunk("turk_telekom_trunk")
    assert tt.status == TrunkStatus.DOWN

    # 3. Recovery probes trigger HEALTHY
    test_manager.mock_probe_func = lambda t: (True, 20.0, 200, "OK")
    test_manager.ping_trunk("turk_telekom_trunk")
    test_manager.ping_trunk("turk_telekom_trunk")
    assert tt.status == TrunkStatus.HEALTHY


def test_maintenance_drain_mode(test_manager: SIPTrunkFailoverManager):
    test_manager.set_trunk_maintenance("turk_telekom_trunk", maintenance=True)
    tt = test_manager.get_trunk("turk_telekom_trunk")
    assert tt is not None
    assert tt.status == TrunkStatus.MAINTENANCE

    # In maintenance mode, Türk Telekom must not be selected
    for _ in range(10):
        sel = test_manager.select_best_trunk(destination_phone="05320000000")
        assert sel.trunk_id != "turk_telekom_trunk"


def test_rest_api_sip_trunk_endpoints(client: TestClient, auth_headers: dict):
    # 1. List trunks endpoint
    list_resp = client.get("/api/sip-trunks", headers=auth_headers)
    assert list_resp.status_code == 200
    trunks = list_resp.json()
    # Varsayılan: yalnızca yapılandırılmış trunk, doğrulanmamış (uydurma operatör yok)
    assert any(t["trunk_id"] == settings.ami_trunk and t["status"] == "unknown" and t["rtt_ms"] is None
               for t in trunks)

    # Test için ek trunklar (gerçek konfigürasyon uç noktası ile)
    for tid, prio in (("turk_telekom_trunk", 1), ("vodafone_net_trunk", 2)):
        r = client.post(
            "/api/sip-trunks/configure",
            headers=auth_headers,
            json={"trunk_id": tid, "name": tid, "host": "sip.example.invalid", "port": 5060, "transport": "UDP",
                  "priority": prio, "weight": 10, "max_channels": 10},
        )
        assert r.status_code == 200

    # 2. Ping endpoint (varsayılan trunk'ın host'u yok: yoklama yapılamaz, RTT null; ağa çıkılmaz)
    ping_resp = client.get(f"/api/sip-trunks/{settings.ami_trunk}/ping", headers=auth_headers)
    assert ping_resp.status_code == 200
    ping_data = ping_resp.json()
    assert ping_data["trunk_id"] == settings.ami_trunk
    assert ping_data["rtt_ms"] is None

    # 3. Select endpoint
    sel_resp = client.post(
        "/api/sip-trunks/select",
        headers=auth_headers,
        json={"destination_phone": "05329998877"},
    )
    assert sel_resp.status_code == 200
    sel_data = sel_resp.json()
    assert "PJSIP/05329998877@" in sel_data["dial_channel"]
    assert sel_data["priority"] in (1, 2)

    # 4. Outage simulation endpoint
    outage_resp = client.post(
        "/api/sip-trunks/simulate-outage",
        headers=auth_headers,
        json={"trunk_id": "turk_telekom_trunk", "outage": True},
    )
    assert outage_resp.status_code == 200
    assert outage_resp.json()["trunk"]["status"] == TrunkStatus.DOWN.value
    assert outage_resp.json()["trunk"]["simulated"] is True

    # Reset outage
    client.post(
        "/api/sip-trunks/simulate-outage",
        headers=auth_headers,
        json={"trunk_id": "turk_telekom_trunk", "outage": False},
    )

    # 5. Maintenance endpoint
    maint_resp = client.post(
        "/api/sip-trunks/maintenance",
        headers=auth_headers,
        json={"trunk_id": "vodafone_net_trunk", "maintenance": True},
    )
    assert maint_resp.status_code == 200
    assert maint_resp.json()["trunk"]["status"] == TrunkStatus.MAINTENANCE.value

    # Reset maintenance
    client.post(
        "/api/sip-trunks/maintenance",
        headers=auth_headers,
        json={"trunk_id": "vodafone_net_trunk", "maintenance": False},
    )

    # 6. Configure endpoint
    conf_resp = client.post(
        "/api/sip-trunks/configure",
        headers=auth_headers,
        json={
            "trunk_id": "custom_telco_trunk",
            "name": "Özel Sanal Santral Trunk",
            "host": "sip.customtelco.net",
            "port": 5060,
            "transport": "UDP",
            "priority": 1,
            "weight": 40,
            "max_channels": 50,
        },
    )
    assert conf_resp.status_code == 200
    assert conf_resp.json()["trunk"]["trunk_id"] == "custom_telco_trunk"

