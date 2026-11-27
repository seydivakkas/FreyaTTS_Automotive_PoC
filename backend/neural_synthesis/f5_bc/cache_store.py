"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.neural_synthesis.config_adapter import BASELINE_SAMPLE_RATE_HZ

CACHE_SCHEMA_VERSION = "f5b-raw-cache-v1"


class CacheEligibilityKind(str, Enum):
    PUBLIC_TEMPLATE = "PUBLIC_TEMPLATE"
    PRIVATE_SESSION = "PRIVATE_SESSION"
    BYPASS = "BYPASS"


@dataclass(frozen=True, slots=True)
class CacheEligibility:
    """Explicit privacy and cache eligibility classification (unknown => BYPASS)."""

    kind: CacheEligibilityKind
    policy_revision: str
    reason: str
    session_id: str | None = None
    template_id: str | None = None

    @property
    def cacheable(self) -> bool:
        return self.kind != CacheEligibilityKind.BYPASS


@dataclass(frozen=True, slots=True)
class CanonicalCacheDescriptor:
    """
    Versioned effective-behavior descriptor for raw 48 kHz FLOAT32_LE audio cache.

    Never stores source PII separately or logs raw descriptors. F6-only pause/playback
    settings are excluded so raw audio identity depends strictly on model-affecting behavior.
    """

    cache_schema_version: str
    policy_revision: str
    model_text: str
    language: str
    model_revision: str
    vocab_revision: str | None
    lexicon_revision: str | None
    capability_revision: str | None
    voice_profile_id: str
    seed: int
    solver_name: str
    ode_steps: int
    time_grid_mode: str
    numeric_precision: str
    layout_class: str
    duration_policy_revision: str
    effective_model_speed: float | None
    rng_profile_revision: str
    quality_policy_revision: str
    model_controls: tuple[tuple[str, str], ...] = ()
    sample_rate_hz: int = BASELINE_SAMPLE_RATE_HZ
    channels: int = 1
    encoding: str = AudioEncoding.FLOAT32_LE.value

    def canonical_json(self) -> str:
        payload = {
            "schema": self.cache_schema_version,
            "policy": self.policy_revision,
            "model_text": self.model_text,
            "language": self.language,
            "model_revision": self.model_revision,
            "vocab_revision": self.vocab_revision,
            "lexicon_revision": self.lexicon_revision,
            "capability_revision": self.capability_revision,
            "voice_profile_id": self.voice_profile_id,
            "seed": self.seed,
            "solver_name": self.solver_name,
            "ode_steps": self.ode_steps,
            "time_grid_mode": self.time_grid_mode,
            "numeric_precision": self.numeric_precision,
            "layout_class": self.layout_class,
            "duration_policy_revision": self.duration_policy_revision,
            "effective_model_speed": self.effective_model_speed,
            "rng_profile_revision": self.rng_profile_revision,
            "quality_policy_revision": self.quality_policy_revision,
            "model_controls": [[k, v] for k, v in self.model_controls],
            "format": [self.sample_rate_hz, self.channels, self.encoding],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(slots=True)
class VersionedCacheEntry:
    """Bounded in-memory raw-audio cache entry with monotonic TTL and borrower accounting."""

    key_digest: str
    descriptor: CanonicalCacheDescriptor
    eligibility_kind: CacheEligibilityKind
    owner_session_id: str | None
    payload: bytes
    sample_count: int
    format: AudioFormat
    created_monotonic_ns: int
    expires_monotonic_ns: int
    quality_policy_revision: str
    is_raw_unprocessed: bool = True
    active_borrowers: int = 0
    retired: bool = False


@dataclass(frozen=True, slots=True)
class CacheStoreStats:
    """Safe aggregate cache telemetry (zero text/audio/key leakage)."""

    entry_count: int
    owned_bytes: int
    retired_bytes: int
    active_borrowers: int
    hits: int
    misses: int
    bypasses: int
    evictions: int
    collisions_or_corrupt: int


class VersionedCacheStore:
    """
    Bounded in-memory versioned raw-audio cache store.

    - Public cache allowed ONLY for explicitly approved static public templates.
    - Private cache disabled by default; when enabled, strictly session-scoped and
      immediately invalidated on session close/revocation.
    - Monotonic clock domain TTL only (empty on restart, zero disk persistence).
    - Tracks retired bytes for evicted entries still held by active borrowers.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        max_entries: int = 32,
        max_bytes: int = 8 * 1024 * 1024,
        max_entry_bytes: int = 1 * 1024 * 1024,
        ttl_ns: int = 60_000_000_000,
        private_cache_enabled: bool = False,
        max_private_entries_per_session: int = 2,
        max_private_bytes_per_session: int = 1 * 1024 * 1024,
        private_ttl_ns: int = 10_000_000_000,
        allowlisted_public_templates: frozenset[str] = frozenset(),
        policy_revision: str = "f5b-cache-policy-v1",
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self.max_entry_bytes = max(1, int(max_entry_bytes))
        self.ttl_ns = max(1, int(ttl_ns))
        self.private_cache_enabled = bool(private_cache_enabled)
        self.max_private_entries_per_session = max(1, int(max_private_entries_per_session))
        self.max_private_bytes_per_session = max(1, int(max_private_bytes_per_session))
        self.private_ttl_ns = max(1, int(private_ttl_ns))
        self.allowlisted_public_templates = allowlisted_public_templates
        self.policy_revision = policy_revision

        self._lock = threading.Lock()
        self._public: OrderedDict[str, VersionedCacheEntry] = OrderedDict()
        self._private: dict[str, OrderedDict[str, VersionedCacheEntry]] = {}
        self._retired_entries: dict[int, VersionedCacheEntry] = {}
        self._owned_bytes = 0
        self._retired_bytes = 0
        self._hits = 0
        self._misses = 0
        self._bypasses = 0
        self._evictions = 0
        self._collisions = 0

    def classify_eligibility(
        self,
        *,
        session_id: str | None,
        is_public_template: bool = False,
        template_id: str | None = None,
        contains_pii: bool | None = None,
        allow_private_session: bool = False,
    ) -> CacheEligibility:
        """Conservative privacy gate: unknown or personal => BYPASS."""
        if contains_pii is True:
            return CacheEligibility(
                kind=CacheEligibilityKind.BYPASS,
                policy_revision=self.policy_revision,
                reason="PII_NEVER_CACHED_OR_SHARED",
            )
        if is_public_template and template_id and (
            not self.allowlisted_public_templates or template_id in self.allowlisted_public_templates
        ):
            if contains_pii is None:
                return CacheEligibility(
                    kind=CacheEligibilityKind.BYPASS,
                    policy_revision=self.policy_revision,
                    reason="UNKNOWN_PII_PROVENANCE_BYPASS",
                )
            return CacheEligibility(
                kind=CacheEligibilityKind.PUBLIC_TEMPLATE,
                policy_revision=self.policy_revision,
                reason="APPROVED_PUBLIC_TEMPLATE",
                template_id=template_id,
            )
        if allow_private_session and self.private_cache_enabled and session_id:
            return CacheEligibility(
                kind=CacheEligibilityKind.PRIVATE_SESSION,
                policy_revision=self.policy_revision,
                reason="SESSION_SCOPED_PRIVATE_CACHE",
                session_id=session_id,
            )
        return CacheEligibility(
            kind=CacheEligibilityKind.BYPASS,
            policy_revision=self.policy_revision,
            reason="DEFAULT_PRIVACY_BYPASS",
        )

    def put(
        self,
        *,
        descriptor: CanonicalCacheDescriptor,
        eligibility: CacheEligibility,
        payload: bytes,
        sample_count: int,
        audio_format: AudioFormat,
        is_raw_unprocessed: bool = True,
    ) -> bool:
        if not eligibility.cacheable or not is_raw_unprocessed:
            return False
        if (
            audio_format.sample_rate_hz != BASELINE_SAMPLE_RATE_HZ
            or audio_format.channels != 1
            or audio_format.encoding != AudioEncoding.FLOAT32_LE
        ):
            return False
        if not isinstance(payload, bytes) or len(payload) != sample_count * 4:
            return False

        nbytes = len(payload)
        if nbytes > self.max_entry_bytes or nbytes > self.max_bytes:
            return False

        now = self.clock.monotonic_ns()
        digest = descriptor.digest()
        ttl = self.private_ttl_ns if eligibility.kind == CacheEligibilityKind.PRIVATE_SESSION else self.ttl_ns

        with self._lock:
            self._prune_expired_locked(now)
            if eligibility.kind == CacheEligibilityKind.PRIVATE_SESSION:
                sid = eligibility.session_id
                if not sid or nbytes > self.max_private_bytes_per_session:
                    return False
                bucket = self._private.setdefault(sid, OrderedDict())
                if digest in bucket:
                    self._retire_or_drop_locked(bucket.pop(digest))
                while (
                    len(bucket) >= self.max_private_entries_per_session
                    or sum(e.format.sample_rate_hz * 0 + len(e.payload) for e in bucket.values()) + nbytes
                    > self.max_private_bytes_per_session
                ):
                    _, evicted = bucket.popitem(last=False)
                    self._retire_or_drop_locked(evicted)
                    self._evictions += 1
                target_map = bucket
            else:
                if digest in self._public:
                    self._retire_or_drop_locked(self._public.pop(digest))
                target_map = self._public

            while len(self._public) + sum(len(b) for b in self._private.values()) >= self.max_entries or (
                self._owned_bytes + nbytes > self.max_bytes
            ):
                if not self._evict_one_global_locked():
                    return False

            entry = VersionedCacheEntry(
                key_digest=digest,
                descriptor=descriptor,
                eligibility_kind=eligibility.kind,
                owner_session_id=eligibility.session_id,
                payload=bytes(payload),
                sample_count=sample_count,
                format=audio_format,
                created_monotonic_ns=now,
                expires_monotonic_ns=now + ttl,
                quality_policy_revision=descriptor.quality_policy_revision,
                is_raw_unprocessed=True,
            )
            target_map[digest] = entry
            self._owned_bytes += nbytes
            return True

    def get(
        self,
        *,
        descriptor: CanonicalCacheDescriptor,
        eligibility: CacheEligibility,
    ) -> tuple[VersionedCacheEntry | None, str]:
        if not eligibility.cacheable:
            with self._lock:
                self._bypasses += 1
            return None, eligibility.reason

        now = self.clock.monotonic_ns()
        digest = descriptor.digest()

        with self._lock:
            self._prune_expired_locked(now)
            if eligibility.kind == CacheEligibilityKind.PRIVATE_SESSION:
                sid = eligibility.session_id
                bucket = self._private.get(sid or "")
                entry = bucket.get(digest) if bucket is not None else None
                if entry is None:
                    self._misses += 1
                    return None, "CACHE_MISS"
                if entry.owner_session_id != sid:
                    self._bypasses += 1
                    return None, "PRIVATE_CROSS_SESSION_DISALLOWED"
                if entry.descriptor != descriptor:
                    self._collisions += 1
                    self._retire_or_drop_locked(bucket.pop(digest))
                    return None, "CACHE_DESCRIPTOR_COLLISION_QUARANTINED"
                bucket.move_to_end(digest)
            else:
                entry = self._public.get(digest)
                if entry is None:
                    self._misses += 1
                    return None, "CACHE_MISS"
                if entry.descriptor != descriptor:
                    self._collisions += 1
                    self._retire_or_drop_locked(self._public.pop(digest))
                    return None, "CACHE_DESCRIPTOR_COLLISION_QUARANTINED"
                self._public.move_to_end(digest)

            if not entry.is_raw_unprocessed or len(entry.payload) != entry.sample_count * 4:
                self._collisions += 1
                if eligibility.kind == CacheEligibilityKind.PRIVATE_SESSION and eligibility.session_id:
                    self._retire_or_drop_locked(self._private[eligibility.session_id].pop(digest))
                else:
                    self._retire_or_drop_locked(self._public.pop(digest))
                return None, "CORRUPT_CACHE_ENTRY_QUARANTINED"

            entry.active_borrowers += 1
            self._hits += 1
            return entry, "VERIFIED_RAW_CACHE_HIT"

    def release_borrow(self, entry: VersionedCacheEntry) -> None:
        with self._lock:
            if entry.active_borrowers > 0:
                entry.active_borrowers -= 1
            if entry.retired and entry.active_borrowers == 0:
                popped = self._retired_entries.pop(id(entry), None)
                if popped is not None:
                    self._retired_bytes = max(0, self._retired_bytes - len(popped.payload))

    def invalidate_session(self, session_id: str) -> int:
        with self._lock:
            bucket = self._private.pop(session_id, None)
            if not bucket:
                return 0
            count = len(bucket)
            for entry in bucket.values():
                self._retire_or_drop_locked(entry)
            return count

    def invalidate_all(self) -> int:
        with self._lock:
            count = len(self._public) + sum(len(b) for b in self._private.values())
            for entry in self._public.values():
                self._retire_or_drop_locked(entry)
            self._public.clear()
            for bucket in self._private.values():
                for entry in bucket.values():
                    self._retire_or_drop_locked(entry)
            self._private.clear()
            return count

    def stats(self) -> CacheStoreStats:
        with self._lock:
            total_entries = len(self._public) + sum(len(b) for b in self._private.values())
            borrowers = (
                sum(e.active_borrowers for e in self._public.values())
                + sum(e.active_borrowers for b in self._private.values() for e in b.values())
                + sum(e.active_borrowers for e in self._retired_entries.values())
            )
            return CacheStoreStats(
                entry_count=total_entries,
                owned_bytes=self._owned_bytes,
                retired_bytes=self._retired_bytes,
                active_borrowers=borrowers,
                hits=self._hits,
                misses=self._misses,
                bypasses=self._bypasses,
                evictions=self._evictions,
                collisions_or_corrupt=self._collisions,
            )

    def _prune_expired_locked(self, now_ns: int) -> None:
        for k in [k for k, e in self._public.items() if now_ns >= e.expires_monotonic_ns]:
            self._retire_or_drop_locked(self._public.pop(k))
            self._evictions += 1
        for sid in list(self._private.keys()):
            bucket = self._private[sid]
            for k in [k for k, e in bucket.items() if now_ns >= e.expires_monotonic_ns]:
                self._retire_or_drop_locked(bucket.pop(k))
                self._evictions += 1
            if not bucket:
                self._private.pop(sid, None)

    def _evict_one_global_locked(self) -> bool:
        if self._public:
            _, evicted = self._public.popitem(last=False)
            self._retire_or_drop_locked(evicted)
            self._evictions += 1
            return True
        for sid in list(self._private.keys()):
            bucket = self._private[sid]
            if bucket:
                _, evicted = bucket.popitem(last=False)
                self._retire_or_drop_locked(evicted)
                self._evictions += 1
                if not bucket:
                    self._private.pop(sid, None)
                return True
        return False

    def _retire_or_drop_locked(self, entry: VersionedCacheEntry) -> None:
        nbytes = len(entry.payload)
        self._owned_bytes = max(0, self._owned_bytes - nbytes)
        if entry.active_borrowers > 0:
            entry.retired = True
            self._retired_entries[id(entry)] = entry
            self._retired_bytes += nbytes


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CacheEligibility",
    "CacheEligibilityKind",
    "CacheStoreStats",
    "CanonicalCacheDescriptor",
    "VersionedCacheEntry",
    "VersionedCacheStore",
]
