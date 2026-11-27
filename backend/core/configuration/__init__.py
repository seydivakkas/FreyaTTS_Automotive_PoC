"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from backend.core.configuration.contracts import (
    ConfigSnapshot,
    ConfigSource,
    FeatureFlagSpec,
    ResolvedSetting,
    RestartPolicy,
    SecretBox,
    SecretRef,
    SensitivityLevel,
    SettingSpec,
    SettingValueType,
    SupervisorMode,
)
from backend.core.configuration.feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FeatureFlagRegistry,
    parse_supervisor_mode,
)
from backend.core.configuration.legacy_adapter import (
    legacy_values_from_snapshot,
    snapshot_from_legacy_settings,
)
from backend.core.configuration.resolver import (
    ConfigResolution,
    coerce_setting_value,
    parse_dotenv_file,
    parse_dotenv_text,
    resolve_configuration,
)
from backend.core.configuration.safe_projection import (
    REDACTED_SENTINEL,
    project_setting,
    redact_url_credentials,
    safe_projection,
    safe_snapshot_json,
)
from backend.core.configuration.setting_catalog import SETTING_CATALOG, SettingCatalog
from backend.core.configuration.snapshots import (
    ConfigSnapshotStore,
    build_snapshot,
    compute_config_revision,
)

__all__ = [
    "ConfigResolution",
    "ConfigSnapshot",
    "ConfigSnapshotStore",
    "ConfigSource",
    "DEFAULT_FEATURE_FLAGS",
    "FeatureFlagRegistry",
    "FeatureFlagSpec",
    "REDACTED_SENTINEL",
    "ResolvedSetting",
    "RestartPolicy",
    "SETTING_CATALOG",
    "SecretBox",
    "SecretRef",
    "SensitivityLevel",
    "SettingCatalog",
    "SettingSpec",
    "SettingValueType",
    "SupervisorMode",
    "build_snapshot",
    "coerce_setting_value",
    "compute_config_revision",
    "legacy_values_from_snapshot",
    "parse_dotenv_file",
    "parse_dotenv_text",
    "parse_supervisor_mode",
    "project_setting",
    "redact_url_credentials",
    "resolve_configuration",
    "safe_projection",
    "safe_snapshot_json",
    "snapshot_from_legacy_settings",
]
