"""Offline real-adapter configuration capability checks; no socket ever opened."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit
import os
import re

class AdapterType(str,Enum):
    FREYA='freya'
    STT='stt'
    LLM='llm'
    PBX='pbx'

@dataclass(frozen=True)
class AdapterConfig:
    kind: AdapterType
    implementation: str
    endpoint: str | None = None
    model_path: str | None = None
    secret_env: str | None = None
    enabled: bool = False
    timeout_ms: int = 5000
    max_retries: int = 0
    sample_rate_hz: int | None = None
    codec: str | None = None

@dataclass(frozen=True)
class ReadinessResult:
    adapter: str
    ready_for_activation: bool
    dry_run_only: bool
    findings: tuple[str,...]
    def as_dict(self):
        return {'adapter':self.adapter,'ready_for_activation':self.ready_for_activation,
                'dry_run_only':self.dry_run_only,'findings':list(self.findings)}

ALLOWED={
    AdapterType.FREYA:{'freyatts-local'},
    AdapterType.STT:{'whisper-local'},
    AdapterType.LLM:{'ollama-local','openai-compatible'},
    AdapterType.PBX:{'asterisk-websocket','asterisk-audiosocket'},
}

class OfflineReadiness:
    """Config validation only. No resolve, connect, probe, model load or path traversal."""
    @staticmethod
    def check(cfg:AdapterConfig)->ReadinessResult:
        issues=[]
        if not isinstance(cfg,AdapterConfig):raise TypeError('AdapterConfig required')
        if cfg.implementation not in ALLOWED[cfg.kind]:issues.append('implementation_not_allowlisted')
        if type(cfg.timeout_ms) is not int or not 100<=cfg.timeout_ms<=120000:issues.append('invalid_timeout')
        if type(cfg.max_retries) is not int or not 0<=cfg.max_retries<=3:issues.append('invalid_retry_budget')
        if cfg.kind in (AdapterType.FREYA,AdapterType.STT):
            if cfg.model_path is None or not Path(cfg.model_path).is_absolute():issues.append('absolute_model_path_required')
            elif not Path(cfg.model_path).is_dir():issues.append('model_directory_missing')
        if cfg.kind in (AdapterType.LLM,AdapterType.PBX):
            if not cfg.endpoint:issues.append('endpoint_required')
            else:
                u=urlsplit(cfg.endpoint)
                if u.scheme not in ('http','https','ws','wss') or not u.hostname or u.username or u.password or u.fragment:
                    issues.append('unsafe_endpoint')
                if u.hostname and not (u.hostname in ('localhost','127.0.0.1','::1')):
                    issues.append('external_endpoint_not_tested')
                if u.scheme in ('http','ws') and u.hostname not in ('localhost','127.0.0.1','::1'):
                    issues.append('unencrypted_remote_transport')
        if cfg.kind==AdapterType.PBX:
            if cfg.codec not in ('slin8','slin16','ulaw','alaw','g722'):
                issues.append('unsupported_pbx_codec')
            if cfg.sample_rate_hz not in (8000,16000):issues.append('unsupported_pbx_sample_rate')
            if cfg.codec in ('ulaw','alaw') and cfg.sample_rate_hz!=8000:issues.append('codec_sample_rate_mismatch')
            if cfg.codec=='g722' and cfg.sample_rate_hz!=16000:issues.append('codec_sample_rate_mismatch')
        if cfg.secret_env:
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}',cfg.secret_env):
                issues.append('invalid_secret_env_name')
            elif cfg.enabled and not os.environ.get(cfg.secret_env):
                issues.append('secret_missing_in_environment')
        if cfg.enabled:
            issues.append('real_activation_explicitly_disabled_in_M10')
        # Not even a clean local config counts as a verified real connection.
        return ReadinessResult(cfg.kind.value,False,True,tuple(dict.fromkeys(issues)))

    @classmethod
    def evaluate(cls, configs:list[AdapterConfig])->dict:
        kinds=[c.kind for c in configs]
        if len(kinds)!=4 or len(set(kinds))!=4:raise ValueError('exactly one config for each of four adapters')
        results=[cls.check(c) for c in configs]
        return {'mode':'M10_DRY_RUN','external_connections':0,'audio_bytes':0,'production_ready':False,
                'adapters':[r.as_dict() for r in results]}
