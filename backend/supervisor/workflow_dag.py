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

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from backend.core.contracts.dialogue import ToolReceipt, ToolReceiptStatus
from backend.core.contracts.validation import freeze_value

MAX_WORKFLOW_NODES = 8
MAX_WORKFLOW_EDGES = 12
MAX_WORKFLOW_DEPTH = 4
MAX_PARALLEL_READS = 2
MAX_READS_PER_TURN = 4
MAX_INFLIGHT_MUTATIONS = 1


class NodeKind(StrEnum):
    """F3-C bounded DAG node kind."""

    READ = "READ"
    MUTATION_PROPOSAL = "MUTATION_PROPOSAL"
    CONTROL = "CONTROL"


class EdgeKind(StrEnum):
    """F3-C declarative edge kind (no arbitrary code expressions)."""

    DATA_DEPENDENCY = "DATA_DEPENDENCY"
    ORDER_ONLY = "ORDER_ONLY"
    CONDITION = "CONDITION"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


class NodeStatus(StrEnum):
    """Private F3-C node execution status (never overrides M07 ToolReceipt)."""

    READY = "READY"
    RUNNING_READ = "RUNNING_READ"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ADMITTED_EFFECT = "ADMITTED_EFFECT"
    SUCCEEDED_READ = "SUCCEEDED_READ"
    COMMITTED = "COMMITTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    SKIPPED_DEPENDENCY = "SKIPPED_DEPENDENCY"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    """Directed dependency edge from source_node_id -> target_node_id."""

    source_node_id: str
    target_node_id: str
    kind: EdgeKind = EdgeKind.DATA_DEPENDENCY


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    """Immutable bounded workflow node."""

    node_id: str
    kind: NodeKind
    tool_id: str
    agent_id: str
    depends_on: tuple[str, ...] = ()
    arguments: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        if not self.node_id or not self.node_id.strip():
            raise ValueError("node_id must be non-empty")
        object.__setattr__(self, "arguments", freeze_value(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class WorkflowPlan:
    """Validated immutable F3-C multi-intent DAG."""

    workflow_id: str
    input_ref: str
    context_revision: int
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...] = ()
    max_parallel_reads: int = MAX_PARALLEL_READS
    max_inflight_mutations: int = MAX_INFLIGHT_MUTATIONS

    def __post_init__(self) -> None:
        validate_workflow_dag(self)


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Per-node execution outcome preserving M07 ToolReceipt truth."""

    node_id: str
    kind: NodeKind
    status: NodeStatus
    receipt: ToolReceipt | None = None
    data: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    reason_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze_value(dict(self.data)))


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    """Ordered per-node workflow outcome (never collapses mixed outcomes)."""

    workflow_id: str
    overall_status: str  # "SUCCEEDED", "MIXED", "BLOCKED", "NEEDS_CONFIRMATION", "FAILED"
    results: tuple[NodeResult, ...]
    read_count: int
    mutation_count: int


def validate_workflow_dag(plan: WorkflowPlan) -> None:
    """Validate bounded size, unique node IDs, valid dependencies, acyclicity, and max depth."""
    if len(plan.nodes) > MAX_WORKFLOW_NODES:
        raise ValueError(f"WorkflowPlan exceeds max {MAX_WORKFLOW_NODES} nodes")
    if len(plan.edges) > MAX_WORKFLOW_EDGES:
        raise ValueError(f"WorkflowPlan exceeds max {MAX_WORKFLOW_EDGES} edges")
    if plan.max_parallel_reads < 1 or plan.max_parallel_reads > MAX_PARALLEL_READS:
        raise ValueError(f"max_parallel_reads must be in 1..{MAX_PARALLEL_READS}")
    if plan.max_inflight_mutations != MAX_INFLIGHT_MUTATIONS:
        raise ValueError("max_inflight_mutations must be 1")

    node_map: dict[str, WorkflowNode] = {}
    read_count = 0
    for node in plan.nodes:
        if node.node_id in node_map:
            raise ValueError(f"Duplicate node_id: {node.node_id}")
        node_map[node.node_id] = node
        if node.kind == NodeKind.READ:
            read_count += 1
    if read_count > MAX_READS_PER_TURN:
        raise ValueError(f"WorkflowPlan exceeds max {MAX_READS_PER_TURN} reads per turn")

    adj: dict[str, set[str]] = {nid: set() for nid in node_map}
    for node in plan.nodes:
        for dep in node.depends_on:
            if dep not in node_map:
                raise ValueError(f"Unknown dependency {dep!r} in node {node.node_id!r}")
            if dep == node.node_id:
                raise ValueError(f"Self-dependency on node {node.node_id!r}")
            adj[dep].add(node.node_id)

    for edge in plan.edges:
        if edge.source_node_id not in node_map or edge.target_node_id not in node_map:
            raise ValueError("WorkflowEdge references unknown node")
        if edge.source_node_id == edge.target_node_id:
            raise ValueError("WorkflowEdge cannot be self-referential")
        adj[edge.source_node_id].add(edge.target_node_id)

    # Cycle and depth check via Kahn's topological sort + longest path.
    indegree: dict[str, int] = {nid: 0 for nid in node_map}
    for src, targets in adj.items():
        for tgt in targets:
            indegree[tgt] += 1

    queue = [nid for nid, deg in indegree.items() if deg == 0]
    depth: dict[str, int] = {nid: 1 for nid in queue}
    visited = 0
    while queue:
        cur = queue.pop(0)
        visited += 1
        for nxt in adj[cur]:
            depth[nxt] = max(depth.get(nxt, 1), depth[cur] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(node_map):
        raise ValueError("WorkflowPlan contains a dependency cycle")
    if depth and max(depth.values()) > MAX_WORKFLOW_DEPTH:
        raise ValueError(f"WorkflowPlan exceeds max depth {MAX_WORKFLOW_DEPTH}")


ReadRunner = Callable[[WorkflowNode], Awaitable[NodeResult]]
MutationRunner = Callable[[WorkflowNode, Mapping[str, NodeResult]], Awaitable[NodeResult]]


def _deps_satisfied(node: WorkflowNode, results: Mapping[str, NodeResult]) -> tuple[bool, str | None]:
    for dep in node.depends_on:
        res = results.get(dep)
        if res is None:
            return False, None
        if res.status not in {NodeStatus.SUCCEEDED_READ, NodeStatus.COMMITTED}:
            return False, f"dependency_failed:{dep}:{res.status.value}"
    return True, None


class WorkflowDagExecutor:
    """
    Bounded F3-C DAG executor.

    - Executes independent authorized READ nodes in parallel (bounded by semaphore).
    - Executes MUTATION_PROPOSAL nodes sequentially, one at a time, only when
      prerequisites succeeded and M07 confirmation/gateway permits.
    - Reports exact per-node outcomes in original plan order.
    """

    def __init__(self, *, max_parallel_reads: int = MAX_PARALLEL_READS) -> None:
        self._max_parallel_reads = min(max(1, max_parallel_reads), MAX_PARALLEL_READS)

    async def execute(
        self,
        plan: WorkflowPlan,
        *,
        read_runner: ReadRunner,
        mutation_runner: MutationRunner,
    ) -> WorkflowOutcome:
        results: dict[str, NodeResult] = {}
        sem = asyncio.Semaphore(min(self._max_parallel_reads, plan.max_parallel_reads))
        read_count = 0
        mutation_count = 0

        # Wave 1+: run eligible READ nodes in parallel until no more READs are ready.
        pending_reads = [n for n in plan.nodes if n.kind == NodeKind.READ]
        while pending_reads:
            ready_batch: list[WorkflowNode] = []
            next_pending: list[WorkflowNode] = []
            for node in pending_reads:
                ok, fail_reason = _deps_satisfied(node, results)
                if fail_reason is not None:
                    results[node.node_id] = NodeResult(
                        node_id=node.node_id,
                        kind=node.kind,
                        status=NodeStatus.SKIPPED_DEPENDENCY,
                        reason_code=fail_reason,
                    )
                elif ok:
                    ready_batch.append(node)
                else:
                    next_pending.append(node)

            if not ready_batch:
                for node in next_pending:
                    results[node.node_id] = NodeResult(
                        node_id=node.node_id,
                        kind=node.kind,
                        status=NodeStatus.SKIPPED_DEPENDENCY,
                        reason_code="dependency_unresolved",
                    )
                break

            async def _run_bounded_read(n: WorkflowNode) -> NodeResult:
                async with sem:
                    return await read_runner(n)

            batch_outcomes = await asyncio.gather(*(_run_bounded_read(n) for n in ready_batch))
            for n, out in zip(ready_batch, batch_outcomes, strict=True):
                results[n.node_id] = out
                read_count += 1
            pending_reads = next_pending

        # Sequential phase: MUTATION_PROPOSAL and CONTROL nodes in plan order.
        stop_remaining_mutations = False
        for node in plan.nodes:
            if node.kind == NodeKind.READ:
                continue
            if stop_remaining_mutations:
                results[node.node_id] = NodeResult(
                    node_id=node.node_id,
                    kind=node.kind,
                    status=NodeStatus.SKIPPED_DEPENDENCY,
                    reason_code="prior_mutation_halted_workflow",
                )
                continue

            ok, fail_reason = _deps_satisfied(node, results)
            if not ok:
                results[node.node_id] = NodeResult(
                    node_id=node.node_id,
                    kind=node.kind,
                    status=NodeStatus.SKIPPED_DEPENDENCY,
                    reason_code=fail_reason or "dependency_unresolved",
                )
                continue

            out = await mutation_runner(node, results)
            results[node.node_id] = out
            if node.kind == NodeKind.MUTATION_PROPOSAL:
                mutation_count += 1
                if out.status in {
                    NodeStatus.UNKNOWN,
                    NodeStatus.PENDING,
                    NodeStatus.NEEDS_CONFIRMATION,
                    NodeStatus.NEEDS_CLARIFICATION,
                    NodeStatus.FAILED,
                }:
                    stop_remaining_mutations = True

        ordered_results = tuple(results[n.node_id] for n in plan.nodes)
        statuses = {r.status for r in ordered_results}
        success_set = {NodeStatus.SUCCEEDED_READ, NodeStatus.COMMITTED}
        if statuses <= success_set:
            overall = "SUCCEEDED"
        elif statuses & success_set:
            overall = "MIXED"
        elif NodeStatus.NEEDS_CONFIRMATION in statuses:
            overall = "NEEDS_CONFIRMATION"
        elif NodeStatus.BLOCKED in statuses or NodeStatus.SKIPPED_DEPENDENCY in statuses:
            overall = "BLOCKED"
        else:
            overall = "FAILED"

        return WorkflowOutcome(
            workflow_id=plan.workflow_id,
            overall_status=overall,
            results=ordered_results,
            read_count=read_count,
            mutation_count=mutation_count,
        )
