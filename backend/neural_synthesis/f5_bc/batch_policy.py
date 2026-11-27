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

from dataclasses import dataclass
from typing import Sequence

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.f5_bc.batch_layout import BatchExecutionLayout, BatchLayoutBuilder
from backend.runtime_resources.contracts import PriorityClass
from backend.runtime_resources.memory_budget import MemoryBudget

DEFAULT_FRAME_BUCKETS: tuple[tuple[int, int], ...] = (
    (1, 32),
    (33, 64),
    (65, 128),
    (129, 300),
)
DEFAULT_MAX_PADDING_FRACTION = 0.25


@dataclass(frozen=True, slots=True)
class BatchCandidate:
    """Candidate synthesis item submitted to M06-coordinated micro-batch formation."""

    member_id: str
    true_token_length: int
    true_latent_frames: int
    expected_waveform_samples: int
    latent_dim: int
    compatibility_key: str
    priority: PriorityClass
    enqueue_monotonic_ns: int
    deadline_monotonic_ns: int | None
    seed: int
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class BatchFormationDecision:
    """Result of deadline-aware, length-bucketed micro-batch formation under M06."""

    formation_owner: str
    batches: tuple[BatchExecutionLayout, ...]
    deferred_member_ids: tuple[str, ...]
    rejected_member_ids: tuple[str, ...]
    formation_wait_ns: int
    reason: str
    error: ErrorInfo | None = None


class DeadlineBatchFormer:
    """
    F5-C deadline-aware micro-batch former & latent-length bucketer under M06.

    Invariants:
    - Single formation owner (`M06_SCHEDULER_BRIDGE`), no second worker queue.
    - Priority isolation: P2 (first chunk), P4 (later chunks), P7 (lab) never mixed by default.
    - Urgent P2 or imminent deadline => zero formation wait (`formation_wait_ns == 0`).
    - Length bucketing groups compatible items within frame buckets while preserving
      enqueue fairness order and enforcing `max_padding_fraction` (default 0.25).
    - Checks M06 `MemoryBudget` before dispatching any formed batch.
    """

    def __init__(
        self,
        *,
        layout_builder: BatchLayoutBuilder | None = None,
        frame_buckets: tuple[tuple[int, int], ...] = DEFAULT_FRAME_BUCKETS,
        max_batch_size: int = 8,
        max_wait_ms: float = 12.0,
        max_padding_fraction: float = DEFAULT_MAX_PADDING_FRACTION,
        safety_margin_ns: int = 5_000_000,
    ) -> None:
        self.layout_builder = layout_builder or BatchLayoutBuilder()
        self.frame_buckets = frame_buckets
        self.max_batch_size = max(1, int(max_batch_size))
        self.max_wait_ns = max(0, int(max_wait_ms * 1_000_000))
        self.max_padding_fraction = float(max_padding_fraction)
        self.safety_margin_ns = max(0, int(safety_margin_ns))

    def bucket_index(self, true_latent_frames: int) -> int:
        for idx, (lo, hi) in enumerate(self.frame_buckets):
            if lo <= true_latent_frames <= hi:
                return idx
        return len(self.frame_buckets)

    def compute_formation_wait_ns(
        self,
        *,
        candidates: Sequence[BatchCandidate],
        now_monotonic_ns: int,
        predicted_batch_cost_ns: int,
    ) -> int:
        if not candidates or self.max_wait_ns == 0:
            return 0
        # Never wait to fill a batch when urgent P2 first-chunk work is present
        if any(c.priority == PriorityClass.P2 for c in candidates):
            return 0
        if len(candidates) >= self.max_batch_size:
            return 0

        min_slack = self.max_wait_ns
        for c in candidates:
            if c.deadline_monotonic_ns is not None:
                latest_start = c.deadline_monotonic_ns - predicted_batch_cost_ns - self.safety_margin_ns
                slack = max(0, latest_start - now_monotonic_ns)
                min_slack = min(min_slack, slack)
        return max(0, min(self.max_wait_ns, min_slack))

    def form_batches(
        self,
        *,
        candidates: Sequence[BatchCandidate],
        now_monotonic_ns: int,
        memory_budget: MemoryBudget | None = None,
        batch_id_prefix: str = "f5c-batch",
        predicted_batch_cost_ns: int = 20_000_000,
    ) -> BatchFormationDecision:
        if not candidates:
            return BatchFormationDecision(
                formation_owner="M06_SCHEDULER_BRIDGE",
                batches=(),
                deferred_member_ids=(),
                rejected_member_ids=(),
                formation_wait_ns=0,
                reason="NO_CANDIDATES",
            )

        rejected: list[str] = []
        eligible: list[BatchCandidate] = []
        for c in candidates:
            if c.deadline_monotonic_ns is not None and now_monotonic_ns >= c.deadline_monotonic_ns:
                rejected.append(c.member_id)
            else:
                eligible.append(c)

        if not eligible:
            return BatchFormationDecision(
                formation_owner="M06_SCHEDULER_BRIDGE",
                batches=(),
                deferred_member_ids=(),
                rejected_member_ids=tuple(rejected),
                formation_wait_ns=0,
                reason="ALL_CANDIDATES_EXPIRED",
                error=ErrorInfo(
                    code="BATCH_DEADLINE_EXPIRED",
                    category=ErrorCategory.CAPACITY,
                    retryable=Retryability.NO,
                    safe_message="All batch candidates exceeded deadline before formation",
                ),
            )

        # Group strictly by (priority, compatibility_key, length_bucket) while preserving enqueue order
        groups: dict[tuple[PriorityClass, str, int], list[BatchCandidate]] = {}
        for c in sorted(eligible, key=lambda x: (x.enqueue_monotonic_ns, x.member_id)):
            b_idx = self.bucket_index(c.true_latent_frames)
            key = (c.priority, c.compatibility_key, b_idx)
            groups.setdefault(key, []).append(c)

        formed_layouts: list[BatchExecutionLayout] = []
        deferred: list[str] = []
        seq = 0

        for (_prio, compat_key, _b_idx), members in groups.items():
            idx = 0
            while idx < len(members):
                chunk = members[idx : idx + self.max_batch_size]
                # Enforce max_padding_fraction; shrink chunk until satisfied (singleton always <= 0.0)
                while len(chunk) > 1:
                    l_max = max(m.true_latent_frames for m in chunk)
                    total_valid = sum(m.true_latent_frames for m in chunk)
                    pad_frac = 1.0 - (float(total_valid) / float(len(chunk) * l_max))
                    if pad_frac <= self.max_padding_fraction:
                        break
                    chunk = chunk[:-1]

                seq += 1
                layout = self.layout_builder.build_layout(
                    batch_id=f"{batch_id_prefix}-{seq}",
                    members=[
                        (
                            m.member_id,
                            m.true_token_length,
                            m.true_latent_frames,
                            m.expected_waveform_samples,
                            m.latent_dim,
                        )
                        for m in chunk
                    ],
                    compatibility_key=compat_key,
                    max_batch_size=self.max_batch_size,
                )

                # Check M06 MemoryBudget admission if provided
                if memory_budget is not None:
                    est_vram = (8 * 1024 * 1024) + (layout.estimated_padded_latent_bytes * 16)
                    adm = memory_budget.check_admission(est_vram)
                    if not adm.admitted:
                        if len(chunk) > 1:
                            # Split to singleton and retry budget check
                            chunk = chunk[:1]
                            layout = self.layout_builder.build_layout(
                                batch_id=f"{batch_id_prefix}-{seq}",
                                members=[
                                    (
                                        chunk[0].member_id,
                                        chunk[0].true_token_length,
                                        chunk[0].true_latent_frames,
                                        chunk[0].expected_waveform_samples,
                                        chunk[0].latent_dim,
                                    )
                                ],
                                compatibility_key=compat_key,
                                max_batch_size=self.max_batch_size,
                            )
                            est_single = (8 * 1024 * 1024) + (layout.estimated_padded_latent_bytes * 16)
                            if not memory_budget.check_admission(est_single).admitted:
                                deferred.append(chunk[0].member_id)
                                idx += 1
                                continue
                        else:
                            deferred.append(chunk[0].member_id)
                            idx += 1
                            continue

                formed_layouts.append(layout)
                idx += len(chunk)

        wait_ns = self.compute_formation_wait_ns(
            candidates=eligible,
            now_monotonic_ns=now_monotonic_ns,
            predicted_batch_cost_ns=predicted_batch_cost_ns,
        )
        return BatchFormationDecision(
            formation_owner="M06_SCHEDULER_BRIDGE",
            batches=tuple(formed_layouts),
            deferred_member_ids=tuple(deferred),
            rejected_member_ids=tuple(rejected),
            formation_wait_ns=wait_ns,
            reason="BATCHES_FORMED" if formed_layouts else "ALL_CANDIDATES_DEFERRED",
        )


__all__ = [
    "BatchCandidate",
    "BatchFormationDecision",
    "DEFAULT_FRAME_BUCKETS",
    "DEFAULT_MAX_PADDING_FRACTION",
    "DeadlineBatchFormer",
]
