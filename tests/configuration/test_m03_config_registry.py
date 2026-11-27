"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from backend.config import Settings
from backend.core.configuration import (
    DEFAULT_FEATURE_FLAGS,
    REDACTED_SENTINEL,
    SETTING_CATALOG,
    ConfigSnapshot,
    ConfigSnapshotStore,
    ConfigSource,
    FeatureFlagRegistry,
    FeatureFlagSpec,
    RestartPolicy,
    SecretBox,
    SecretRef,
    SensitivityLevel,
    SupervisorMode,
    compute_config_revision,
    legacy_values_from_snapshot,
    parse_dotenv_text,
    resolve_configuration,
    safe_projection,
    safe_snapshot_json,
    snapshot_from_legacy_settings,
)
from backend.core.model_registry import (
    EXPERIMENTAL_VOICE_SEEDS,
    LEYLA_BASELINE_SEED,
    ArtifactStatus,
    ModelArtifactSpec,
    ModelDescriptor,
    ModelKind,
    ModelRegistry,
    PreflightState,
    ProfileTier,
    VoiceProfileRegistry,
    run_offline_preflight,
    verify_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_m03_license_headers_present_on_all_new_files():
    owned_dirs = [
        REPO_ROOT / "backend" / "core" / "configuration",
        REPO_ROOT / "backend" / "core" / "model_registry",
    ]
    checked = 0
    for directory in owned_dirs:
        for py_file in sorted(directory.glob("*.py")):
            text = py_file.read_text(encoding="utf-8")
            assert "ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR" in text, f"Missing header in {py_file}"
            assert "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)" in text, f"Missing copyright in {py_file}"
            checked += 1
    assert checked == 14


def test_m03_passive_isolated_imports():
    code = (
        "import sys, backend.core.configuration, backend.core.model_registry; "
        "forbidden = ('torch', 'faster_whisper', 'freyatts', 'joblib', 'httpx', 'sqlalchemy', 'backend.config'); "
        "loaded = [m for m in forbidden if m in sys.modules]; "
        "assert not loaded, f'Forbidden modules imported: {loaded}'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_setting_catalog_covers_all_77_settings_keys_and_metadata():
    settings_fields = Settings.model_fields
    assert len(settings_fields) == 77
    assert len(SETTING_CATALOG) == 77
    assert set(SETTING_CATALOG.specs.keys()) == set(settings_fields.keys())

    for key, spec in SETTING_CATALOG.specs.items():
        assert spec.unit
        assert isinstance(spec.sensitivity, SensitivityLevel)
        assert isinstance(spec.restart_policy, RestartPolicy)
        assert key.upper() in spec.legacy_aliases

    # Explicit legacy aliases from repo
    assert SETTING_CATALOG.resolve_key("FREYA_PBX_METADATA_SECRET") == (
        "pbx_metadata_secret",
        "FREYA_PBX_METADATA_SECRET",
    )
    assert SETTING_CATALOG.resolve_key("LEYLA_SEED") == (
        "batched_ode_default_seed",
        "LEYLA_SEED",
    )
    for secret_key in (
        "admin_password",
        "pbx_metadata_secret",
        "ami_secret",
        "whatsapp_webhook_token",
        "twilio_account_sid",
        "twilio_auth_token",
        "audio_archive_master_key",
        "link_signing_key",
    ):
        assert SETTING_CATALOG.get(secret_key).sensitivity == SensitivityLevel.SECRET_REF


def test_resolver_precedence_legacy_aliases_and_validation():
    dotenv = parse_dotenv_text(
        """
        # Comment
        OLLAMA_MODEL="qwen2.5:14b"
        FREYA_PBX_METADATA_SECRET=alias-secret-123
        PBX_ALLOWED_IPS=["10.0.0.1","10.0.0.2"]
        SUPERVISOR_MODE=shadow
        """
    )
    res = resolve_configuration(
        file_values=dotenv,
        env={"OLLAMA_MODEL": "qwen2.5:32b", "LEYLA_SEED": "42"},
        overrides={"batched_ode_default_seed": 9},
    )
    snap = res.snapshot
    assert snap.get("ollama_model") == "qwen2.5:32b"
    assert snap.sources["ollama_model"] == ConfigSource.ENV
    assert snap.get("batched_ode_default_seed") == 9
    assert snap.sources["batched_ode_default_seed"] == ConfigSource.OVERRIDE
    assert snap.get("pbx_allowed_ips") == ("10.0.0.1", "10.0.0.2")
    assert snap.get("supervisor_mode") == "shadow"
    assert snap.sources["pbx_metadata_secret"] == ConfigSource.LEGACY_ALIAS
    assert snap.is_secret_configured("pbx_metadata_secret")
    assert snap.get_secret("pbx_metadata_secret") == "alias-secret-123"

    # Demo mode isolation matches backend/config.py
    demo_res = resolve_configuration(overrides={"demo_mode": True})
    assert demo_res.snapshot.get("data_dir") == Path("data/demo")
    assert demo_res.snapshot.get("database_url") == "sqlite:///./data/demo/assistant.db"

    # Validation rejections (NaN, <=0, bounds, unknown override)
    with pytest.raises(ValueError):
        resolve_configuration(overrides={"media_write_timeout_sec": 0.0})
    with pytest.raises(ValueError):
        resolve_configuration(overrides={"media_write_timeout_sec": float("nan")})
    with pytest.raises(ValueError):
        resolve_configuration(overrides={"stt_min_rms": 1.5})
    with pytest.raises(ValueError):
        resolve_configuration(overrides={"supervisor_mode": "active"})
    with pytest.raises(KeyError):
        resolve_configuration(overrides={"nonexistent_key": 1})


def test_secrets_never_leak_in_repr_or_safe_projection():
    secret_val = "ULTRA-TOP-SECRET-998877"
    db_pass = "postgres://freya:SuperDbPass42@127.0.0.1:5432/freyadb"
    res = resolve_configuration(
        overrides={
            "admin_password": secret_val,
            "pbx_metadata_secret": secret_val,
            "ami_secret": secret_val,
            "database_url": db_pass,
            "branch_name": f"Branch {secret_val}",
        }
    )
    snap = res.snapshot
    assert isinstance(snap.get("admin_password"), SecretRef)
    assert secret_val not in repr(snap)
    assert secret_val not in str(snap)
    assert secret_val not in repr(res.settings["admin_password"])
    assert secret_val not in repr(SETTING_CATALOG.get("admin_password"))
    assert secret_val not in repr(SecretBox(secret_val))

    proj_internal = safe_projection(snap, include_internal=True)
    dumped = safe_snapshot_json(snap, include_internal=True)
    assert secret_val not in dumped
    assert "SuperDbPass42" not in dumped
    assert proj_internal["settings"]["admin_password"]["value"] == REDACTED_SENTINEL
    assert proj_internal["settings"]["admin_password"]["configured"] is True
    assert "***:***" in proj_internal["settings"]["database_url"]["value"]

    proj_public = safe_projection(snap, include_internal=False)
    assert "database_url" not in proj_public["settings"]
    assert "admin_password" in proj_public["settings"]
    assert proj_public["settings"]["admin_password"]["value"] == REDACTED_SENTINEL


def test_config_snapshot_immutability_revision_stability_and_atomic_rollback():
    r1 = resolve_configuration(
        overrides={"ollama_model": "qwen2.5:7b", "admin_password": "secret-a"},
        created_utc="2026-11-26T00:00:00Z",
        created_monotonic_ns=100,
        snapshot_seq=0,
        note="first",
    )
    r2 = resolve_configuration(
        overrides={"ollama_model": "qwen2.5:7b", "admin_password": "secret-a"},
        created_utc="2026-11-27T12:34:56Z",
        created_monotonic_ns=999999,
        snapshot_seq=42,
        note="second",
    )
    # Canonical SHA-256 revision must be independent of timestamps and snapshot_seq
    assert r1.snapshot.config_revision == r2.snapshot.config_revision
    assert len(r1.snapshot.config_revision) == 64

    # Secret rotation changes canonical revision without exposing secret
    r3 = resolve_configuration(overrides={"ollama_model": "qwen2.5:7b", "admin_password": "secret-b"})
    assert r3.snapshot.config_revision != r1.snapshot.config_revision

    # Deep immutability
    with pytest.raises(FrozenInstanceError):
        r1.snapshot.snapshot_seq = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        r1.snapshot.values["ollama_model"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        r1.snapshot.feature_flags["demo_mode"] = True  # type: ignore[index]

    # Atomic swap & rollback to last known-good
    store = ConfigSnapshotStore(r1.snapshot)
    assert store.current.snapshot_seq == 0
    with pytest.raises(RuntimeError):
        store.rollback()

    promoted = store.swap(r3.snapshot)
    assert promoted.snapshot_seq == 1
    assert store.current.config_revision == r3.snapshot.config_revision
    assert store.last_known_good is not None
    assert store.last_known_good.config_revision == r1.snapshot.config_revision

    # Tampered revision rejected atomically without altering current snapshot
    bad_snap = ConfigSnapshot(
        schema_version="2.0",
        snapshot_seq=0,
        config_revision="0" * 64,
        values=r1.snapshot.values,
        sources=r1.snapshot.sources,
        feature_flags=r1.snapshot.feature_flags,
    )
    with pytest.raises(ValueError):
        store.swap(bad_snap)
    assert store.current.config_revision == r3.snapshot.config_revision

    rolled_back = store.rollback()
    assert rolled_back.config_revision == r1.snapshot.config_revision
    assert store.rollback_count == 1


def test_feature_flag_registry_defaults_and_experimental_guard():
    flags = FeatureFlagRegistry.default()
    assert flags.get_mode("supervisor_mode") == SupervisorMode.OFF
    assert not flags.is_enabled("supervisor_mode")
    assert flags.is_enabled("car_denoiser_enabled") is True
    assert flags.is_enabled("batched_ode_enabled") is True
    assert flags.is_enabled("auto_load_models") is True
    assert flags.is_enabled("fqici_enabled") is False

    # All experimental flags default OFF
    exp_specs = [s for s in DEFAULT_FEATURE_FLAGS if s.experimental]
    assert len(exp_specs) >= 3
    for spec in exp_specs:
        assert flags.is_enabled(spec.name) is False

    # Tri-state OFF / SHADOW / GUARDED preserved
    shadow_snap = resolve_configuration(overrides={"supervisor_mode": "SHADOW"}).snapshot
    shadow_flags = FeatureFlagRegistry.from_snapshot(shadow_snap)
    assert shadow_flags.get_mode("supervisor_mode") == SupervisorMode.SHADOW
    assert shadow_flags.is_enabled("supervisor_mode") is True

    guarded_snap = resolve_configuration(overrides={"supervisor_mode": "guarded"}).snapshot
    guarded_flags = FeatureFlagRegistry.from_snapshot(guarded_snap)
    assert guarded_flags.get_mode("supervisor_mode") == SupervisorMode.GUARDED

    # Experimental flag cannot default ON
    with pytest.raises(ValueError):
        FeatureFlagSpec(name="experimental_bad_bool", default=True, experimental=True)
    with pytest.raises(ValueError):
        FeatureFlagSpec(name="experimental_bad_mode", default=SupervisorMode.SHADOW, experimental=True)


def test_legacy_adapter_bridges_settings_safely():
    legacy = Settings(admin_password="panel-password-1", supervisor_mode="guarded", demo_mode=False)
    conv = snapshot_from_legacy_settings(legacy)
    assert conv.ok and conv.value is not None
    assert conv.missing_fields == ()
    assert conv.value.get("supervisor_mode") == "guarded"
    assert conv.value.get_secret("admin_password") == "panel-password-1"

    masked_dict = legacy_values_from_snapshot(conv.value, include_secrets=False)
    assert masked_dict["admin_password"] == ""
    assert masked_dict["supervisor_mode"] == "guarded"
    unmasked_dict = legacy_values_from_snapshot(conv.value, include_secrets=True)
    assert unmasked_dict["admin_password"] == "panel-password-1"


def test_voice_profile_registry_leyla_baseline_and_experimental_seeds():
    vreg = VoiceProfileRegistry()
    baseline = vreg.baseline()
    assert baseline.seed == LEYLA_BASELINE_SEED == 9
    assert baseline.tier == ProfileTier.BASELINE
    assert baseline.enabled_by_default is True

    # Default listing hides experimental seeds unless requested
    assert [p.seed for p in vreg.list_profiles()] == [9]
    assert [p.seed for p in vreg.list_profiles(include_experimental=True)] == [9, 42, 77, 123]
    assert EXPERIMENTAL_VOICE_SEEDS == (42, 77, 123)

    # Experimental seeds gated OFF by default
    for seed in EXPERIMENTAL_VOICE_SEEDS:
        assert vreg.resolve_seed(seed).seed == 9
        with pytest.raises(PermissionError):
            vreg.resolve_seed(seed, fallback_to_baseline=False)

    # Enabled via explicit feature flag or experimental_enabled=True
    assert vreg.resolve_seed(42, feature_flags={"experimental_voice_seed_42": True}, fallback_to_baseline=False).seed == 42
    assert vreg.resolve_seed(77, experimental_enabled=True, fallback_to_baseline=False).seed == 77


def test_artifact_verifier_streaming_sha256_and_path_traversal_rejection(tmp_path: Path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    artifact = model_dir / "ranker.bin"
    payload = b"freya-supervisor-model-bytes-" * 5000  # ~145 KB > default 64 KB chunk
    artifact.write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    # Streaming SHA-256 with small chunk size
    ok_res = verify_artifact(
        model_id="supervisor-ranker",
        base_dir=tmp_path,
        relative_path="models/ranker.bin",
        expected_sha256=expected_sha,
        chunk_size=1024,
    )
    assert ok_res.is_valid
    assert ok_res.status == ArtifactStatus.VERIFIED
    assert ok_res.actual_sha256 == expected_sha
    assert ok_res.size_bytes == len(payload)

    # Hash mismatch
    bad_hash = verify_artifact(
        model_id="supervisor-ranker",
        base_dir=tmp_path,
        relative_path="models/ranker.bin",
        expected_sha256="f" * 64,
    )
    assert not bad_hash.is_valid
    assert bad_hash.status == ArtifactStatus.HASH_MISMATCH

    # Unapproved digest when required
    unapproved = verify_artifact(
        model_id="supervisor-ranker",
        base_dir=tmp_path,
        relative_path="models/ranker.bin",
        expected_sha256=None,
        require_digest=True,
    )
    assert unapproved.status == ArtifactStatus.UNAPPROVED

    # Missing file
    missing = verify_artifact(
        model_id="supervisor-ranker",
        base_dir=tmp_path,
        relative_path="models/nonexistent.bin",
        expected_sha256=expected_sha,
    )
    assert missing.status == ArtifactStatus.MISSING

    # Path traversal and escape attempts
    outside_file = tmp_path.parent / "outside_secret.bin"
    outside_file.write_bytes(b"secret")
    escape_paths = [
        "../outside_secret.bin",
        "..\\outside_secret.bin",
        "models/../../outside_secret.bin",
        "/etc/passwd",
        "\\Windows\\System32\\drivers\\etc\\hosts",
        "C:\\Windows\\win.ini",
        "models/bad\x00name.bin",
        "",
    ]
    for bad_path in escape_paths:
        res = verify_artifact(
            model_id="supervisor-ranker",
            base_dir=tmp_path,
            relative_path=bad_path,
            expected_sha256=expected_sha,
        )
        assert res.status == ArtifactStatus.PATH_REJECTED, f"Expected PATH_REJECTED for {bad_path!r}"

    # Symlink escape check (skip cleanly if OS privileges disallow symlink creation)
    symlink_path = model_dir / "escape_link.bin"
    try:
        os.symlink(outside_file, symlink_path)
    except OSError:
        pass
    else:
        sym_res = verify_artifact(
            model_id="supervisor-ranker",
            base_dir=tmp_path,
            relative_path="models/escape_link.bin",
            expected_sha256=expected_sha,
        )
        assert sym_res.status == ArtifactStatus.PATH_REJECTED


def test_offline_preflight_read_only_without_loading_weights(tmp_path: Path):
    # Create fake FreyaTTS directory and verified supervisor artifact without any ML libraries
    (tmp_path / "vendor" / "FreyaTTS" / "freyatts").mkdir(parents=True)
    sup_file = tmp_path / "data" / "supervisor" / "model.bin"
    sup_file.parent.mkdir(parents=True)
    sup_bytes = b"not-even-pickle-bytes-never-loaded"
    sup_file.write_bytes(sup_bytes)
    sup_sha = hashlib.sha256(sup_bytes).hexdigest()

    snap = resolve_configuration(
        overrides={
            "freya_path": "vendor/FreyaTTS",
            "supervisor_mode": "guarded",
            "supervisor_model_path": Path("data/supervisor/model.bin"),
            "supervisor_model_sha256": sup_sha,
        }
    ).snapshot
    reg = ModelRegistry.from_snapshot(snap)
    assert reg.get("tts-freya") is not None
    assert reg.get("supervisor-ranker") is not None
    assert len(reg.model_registry_revision) == 64

    report = run_offline_preflight(snap, reg, base_dir=tmp_path, check_packages=False)
    assert report.checked_offline is True
    assert report.weights_loaded is False
    assert report.overall_state == PreflightState.READY
    assert "torch" not in sys.modules
    assert "joblib" not in sys.modules

    # Path traversal in freya_path or tampered artifact must block offline preflight
    bad_snap = resolve_configuration(
        overrides={
            "freya_path": "../../outside",
            "supervisor_mode": "guarded",
            "supervisor_model_path": Path("data/supervisor/model.bin"),
            "supervisor_model_sha256": "0" * 64,
        }
    ).snapshot
    bad_report = run_offline_preflight(bad_snap, base_dir=tmp_path)
    assert bad_report.overall_state == PreflightState.BLOCKED
    assert bad_report.weights_loaded is False

    # Custom ModelArtifactSpec verification through ModelRegistry
    extra_reg = reg.register(
        ModelDescriptor(
            model_id="custom-weights",
            kind=ModelKind.TTS,
            model_revision="v1",
            version="1.0",
            device="cpu",
            artifact=ModelArtifactSpec(
                model_id="custom-weights",
                kind=ModelKind.TTS,
                version="1.0",
                relative_path="data/supervisor/model.bin",
                expected_sha256=sup_sha,
            ),
        )
    )
    extra_report = run_offline_preflight(snap, extra_reg, base_dir=tmp_path)
    assert extra_report.overall_state == PreflightState.READY
    assert json.loads(safe_snapshot_json(snap))["config_revision"] == snap.config_revision
