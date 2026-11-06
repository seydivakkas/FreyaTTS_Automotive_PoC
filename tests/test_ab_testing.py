"""Tests for A/B Testing and Fine-Tuning Infrastructure (Özellik 15).

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import (
    Base,
    Conversation,
    ABExperiment,
    ABAssignment,
)
from backend import main
from backend.ab_testing import (
    PROMPT_TEMPLATES,
    GREETING_TEMPLATES,
    TTS_SEED_PRESETS,
    get_prompt_template_text,
    get_greeting_text,
    seed_default_experiment,
    get_all_experiments,
    get_experiment_by_id,
    create_experiment,
    set_experiment_status,
    assign_conversation_variant,
    record_assignment_metrics,
    _compute_z_test,
    get_experiment_report,
)
from backend.dialogue import Dialogue


@pytest.fixture
def ab_test_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "ab_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr("backend.session.Session", sm)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    client = TestClient(main.app)
    yield client, sm, tmp_path
    client.close()
    engine.dispose()


def test_templates_and_presets_catalog():
    # Verify prompt templates
    assert "standard" in PROMPT_TEMPLATES
    assert "friendly" in PROMPT_TEMPLATES
    assert "concise" in PROMPT_TEMPLATES
    assert "expert" in PROMPT_TEMPLATES
    assert len(PROMPT_TEMPLATES) >= 4

    # Verify greeting templates
    assert "standard" in GREETING_TEMPLATES
    assert "friendly" in GREETING_TEMPLATES
    assert "concise" in GREETING_TEMPLATES
    assert "promotional" in GREETING_TEMPLATES

    # Verify TTS seed presets
    assert 9 in TTS_SEED_PRESETS
    assert 42 in TTS_SEED_PRESETS
    assert 77 in TTS_SEED_PRESETS
    assert 123 in TTS_SEED_PRESETS

    # Test helpers fallback
    assert "Türkçe ekspertiz" in get_prompt_template_text("standard")
    assert "nezaketle" in get_prompt_template_text("friendly")
    assert get_prompt_template_text("unknown_id") == PROMPT_TEMPLATES["standard"]["prompt"]
    assert "Merhaba" in get_greeting_text("standard")
    assert "İyi günler" in get_greeting_text("friendly")
    assert get_greeting_text("unknown_id") == GREETING_TEMPLATES["standard"]["text"]


def test_experiment_crud_and_status(ab_test_setup):
    client, SessionLocal, tmp_path = ab_test_setup

    with SessionLocal() as db:
        # Seeding
        exp = seed_default_experiment(db)
        assert exp.id is not None
        assert exp.status == "active"

        # List all
        all_exps = get_all_experiments(db)
        assert len(all_exps) == 1
        assert all_exps[0]["name"] == "Karşılama & Prompt Optimizasyonu (A/B Test)"

        # Validation: experiment name required
        with pytest.raises(ValueError, match="Deney adı boş olamaz"):
            create_experiment(db, name="", variants=[{"name": "A"}, {"name": "B"}])

        # Validation: at least 2 variants required
        with pytest.raises(ValueError, match="en az 2 varyant"):
            create_experiment(db, name="Geçersiz", variants=[{"name": "A"}])

        # Create custom experiment
        new_exp = create_experiment(
            db,
            name="TTS Ses Karakteri Testi",
            description="Leyla Seed 9 vs Seed 77",
            experiment_type="tts_seed",
            variants=[
                {"id": "ctrl_9", "name": "Kontrol Seed 9", "weight": 50, "tts_seed": 9},
                {"id": "test_77", "name": "Varyant Seed 77", "weight": 50, "tts_seed": 77},
            ],
        )
        assert new_exp["id"] is not None
        assert new_exp["variants_count"] == 2

        # Status toggle
        updated = set_experiment_status(db, new_exp["id"], "paused")
        assert updated["status"] == "paused"

        with pytest.raises(ValueError, match="Geçersiz deney durumu"):
            set_experiment_status(db, new_exp["id"], "invalid_status")


def test_conversation_variant_assignment_and_metrics(ab_test_setup):
    client, SessionLocal, tmp_path = ab_test_setup

    with SessionLocal() as db:
        seed_default_experiment(db)

        # Create 2 conversations
        c1 = Conversation(channel="web")
        c2 = Conversation(channel="telephony")
        db.add_all([c1, c2])
        db.commit()

        cfg1 = assign_conversation_variant(db, c1.id)
        assert cfg1["experiment_id"] is not None
        assert cfg1["variant_id"] in ("control", "variant_b")
        assert cfg1["tts_seed"] in (9, 42)

        # Ensure idempotency for same conversation
        cfg1_again = assign_conversation_variant(db, c1.id)
        assert cfg1_again["variant_id"] == cfg1["variant_id"]

        cfg2 = assign_conversation_variant(db, c2.id)
        assert cfg2["variant_id"] in ("control", "variant_b")

        # Record completion metrics
        record_assignment_metrics(
            db,
            c1.id,
            confirmed=True,
            duration_seconds=45.2,
            turns_count=4,
            first_audio_ms=310.5,
            tts_total_ms=1200.0,
        )

        record_assignment_metrics(
            db,
            c2.id,
            confirmed=False,
            duration_seconds=18.0,
            turns_count=2,
            first_audio_ms=290.0,
        )

        assigns = db.scalars(select(ABAssignment)).all()
        assert len(assigns) == 2
        a1 = next(a for a in assigns if a.conversation_id == c1.id)
        assert a1.outcome == "converted"
        assert a1.duration_seconds == 45.2
        assert a1.turns_count == 4
        assert a1.first_audio_ms == 310.5

        a2 = next(a for a in assigns if a.conversation_id == c2.id)
        assert a2.outcome == "abandoned"


def test_statistical_z_test_and_report_generation(ab_test_setup):
    client, SessionLocal, tmp_path = ab_test_setup

    # Unit math test for two-proportion z-test
    # Example: Control (10/50 = 20%), Variant (25/50 = 50%) -> strong lift & significant
    z_score, p_value = _compute_z_test(c_ctrl=10, n_ctrl=50, c_var=25, n_var=50)
    assert z_score > 3.0
    assert p_value < 0.01

    # Identical proportions -> z=0, p=1
    z_zero, p_one = _compute_z_test(10, 50, 10, 50)
    assert z_zero == 0.0
    assert p_one == 1.0

    with SessionLocal() as db:
        exp = seed_default_experiment(db)

        # Populate synthetic test dataset across Control and Variant B
        # 10 control sessions: 4 converted, 6 abandoned
        for i in range(10):
            conv = Conversation(channel="test")
            db.add(conv)
            db.flush()
            db.add(
                ABAssignment(
                    conversation_id=conv.id,
                    experiment_id=exp.id,
                    variant_id="control",
                    outcome="converted" if i < 4 else "abandoned",
                    duration_seconds=30.0 + i,
                    turns_count=3,
                    first_audio_ms=320.0,
                )
            )

        # 10 variant_b sessions: 8 converted, 2 abandoned
        for i in range(10):
            conv = Conversation(channel="test")
            db.add(conv)
            db.flush()
            db.add(
                ABAssignment(
                    conversation_id=conv.id,
                    experiment_id=exp.id,
                    variant_id="variant_b",
                    outcome="converted" if i < 8 else "abandoned",
                    duration_seconds=25.0 + i,
                    turns_count=4,
                    first_audio_ms=280.0,
                )
            )
        db.commit()

        report = get_experiment_report(db, exp.id)
        assert report["total_experiment_sessions"] == 20
        assert report["total_converted_sessions"] == 12
        assert report["overall_conversion_pct"] == 60.0
        assert len(report["variants"]) == 2

        ctrl_stat = next(v for v in report["variants"] if v["variant_id"] == "control")
        var_stat = next(v for v in report["variants"] if v["variant_id"] == "variant_b")

        assert ctrl_stat["conversion_rate_pct"] == 40.0
        assert var_stat["conversion_rate_pct"] == 80.0
        assert var_stat["avg_first_audio_ms"] == 280.0

        # Verify comparison
        assert len(report["comparisons"]) == 1
        comp = report["comparisons"][0]
        assert comp["variant_id"] == "variant_b"
        assert comp["relative_lift_pct"] == 100.0  # 40% -> 80% is 100% lift
        assert comp["z_score"] > 1.5
        assert "Varyant B" in report["best_performing_variant"]


def test_dialogue_prompt_template_variants():
    # Standard prompt
    d_std = Dialogue(conversation_id="conv-std", prompt_template="standard")
    prompt_std = d_std.build_prompt()
    assert "Türkçe ekspertiz görüşmesinden alan çıkar" in prompt_std

    # Friendly prompt
    d_fr = Dialogue(conversation_id="conv-fr", prompt_template="friendly")
    d_fr.customer = "Ahmet Bey"
    prompt_fr = d_fr.build_prompt()
    assert "nezaketle ve titizlikle analiz et" in prompt_fr
    assert "Bilinen müşteri adı: Ahmet Bey" in d_fr.build_state_message()
    assert "Ahmet" not in prompt_fr  # sistem istemi sabit kalır

    # Concise prompt
    d_conc = Dialogue(conversation_id="conv-conc", prompt_template="concise")
    prompt_conc = d_conc.build_prompt()
    assert "Jeton tasarruflu" in prompt_conc or "Hızlı ve doğrudan" in prompt_conc


def test_api_ab_endpoints(ab_test_setup):
    client, SessionLocal, tmp_path = ab_test_setup
    auth = ("admin", "test-pass")

    # 1. Templates
    r_tpl = client.get("/api/ab/templates", auth=auth)
    assert r_tpl.status_code == 200
    tpl_data = r_tpl.json()
    assert "prompt_templates" in tpl_data
    assert "greeting_templates" in tpl_data
    assert "tts_seed_presets" in tpl_data
    assert len(tpl_data["prompt_templates"]) >= 4

    # 2. Experiments list (with default seed)
    r_exps = client.get("/api/ab/experiments", auth=auth)
    assert r_exps.status_code == 200
    exps = r_exps.json()
    assert len(exps) >= 1
    default_id = exps[0]["id"]

    # 3. Create new experiment
    r_create = client.post(
        "/api/ab/experiments",
        auth=auth,
        json={
            "name": "API Test Deneyi",
            "description": "API üzerinden oluşturulan test",
            "experiment_type": "prompt",
            "variants": [
                {"id": "ctrl", "name": "Kontrol", "weight": 50, "prompt_template": "standard", "tts_seed": 9},
                {"id": "test_b", "name": "Varyant B", "weight": 50, "prompt_template": "concise", "tts_seed": 42},
            ],
            "target_metric": "conversion_rate",
        },
    )
    assert r_create.status_code == 200
    created_exp = r_create.json()
    assert created_exp["name"] == "API Test Deneyi"

    # 4. Status update
    r_status = client.post(
        f"/api/ab/experiments/{created_exp['id']}/status",
        auth=auth,
        json={"status": "paused"},
    )
    assert r_status.status_code == 200
    assert r_status.json()["status"] == "paused"

    # 5. Report
    r_rep = client.get(f"/api/ab/experiments/{default_id}/report", auth=auth)
    assert r_rep.status_code == 200
    rep = r_rep.json()
    assert rep["experiment_id"] == default_id
    assert "variants" in rep
    assert "comparisons" in rep

    # 6. Preview synth (Mocking models.synth to avoid requiring CUDA in tests)
    async def mock_synth(text, seed=9):
        # Return 1 second of dummy float32 audio at 48000 Hz
        return np.zeros(48000, dtype=np.float32)

    monkeypatch_models = pytest.MonkeyPatch()
    monkeypatch_models.setattr(main.models, "synth", mock_synth)

    r_synth = client.post(
        "/api/ab/preview-synth",
        auth=auth,
        json={"text": "Ses sentezi testi", "seed": 42},
    )
    assert r_synth.status_code == 200
    assert r_synth.headers["content-type"] == "audio/wav"
    assert len(r_synth.content) > 1000
    monkeypatch_models.undo()


async def test_voice_session_ab_integration(tmp_path, monkeypatch):
    from backend import session as session_mod

    engine = create_engine("sqlite:///" + str(tmp_path / "session_ab.db"))
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", sm)

    class MockVad:
        def reset_states(self):
            pass

    monkeypatch.setattr(session_mod.models, "vad", MockVad())

    with sm() as db:
        seed_default_experiment(db)

    events = []
    frames = []

    async def emit(ev):
        events.append(ev)

    async def send(fr):
        frames.append(fr)

    sess = session_mod.VoiceSession("test_chan", emit, send)
    assert sess.ab_experiment_id is not None
    assert sess.ab_variant_id in ("control", "variant_b")
    assert sess.tts_seed in (9, 42)
    assert sess.prompt_template in ("standard", "friendly")

    await sess.close()

    with sm() as db:
        assign = db.scalars(
            select(ABAssignment).where(ABAssignment.conversation_id == sess.id)
        ).first()
        assert assign is not None
        assert assign.outcome == "abandoned"
        assert assign.duration_seconds is not None

    engine.dispose()

