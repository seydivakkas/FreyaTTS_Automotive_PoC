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
from typing import Iterable, Mapping

from tests.harness.acceptance import AcceptanceSummary, evaluate_gates
from tests.harness.contracts import GateRecord, GateStatus


@dataclass(frozen=True, slots=True)
class CoreIntegrationDecision:
    package_id: str
    m08_ready: bool
    m08_status: GateStatus
    core_integration_ready: bool
    core_integration_status: GateStatus
    vertical_slice_ready: bool
    owner_execution_authorized: bool
    synthetic_product_acceptance_status: GateStatus
    hardware_acceptance_status: GateStatus
    human_sip_status: GateStatus
    run_id: str
    accepted_dependency_runs: tuple[str, ...]
    blocking_reasons: tuple[str, ...]


REQUIRED_FOUNDATION_PACKAGES: tuple[str, ...] = ("M00", "M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08")
REQUIRED_CI_CASES: tuple[str, ...] = tuple(f"CI{i:02d}" for i in range(1, 25))
REQUIRED_CG_GATES: tuple[str, ...] = tuple(f"CG{i:02d}" for i in range(0, 12))


def evaluate_core_integration(
    *,
    run_id: str,
    m08_summary: AcceptanceSummary,
    package_statuses: Mapping[str, GateStatus],
    ci_results: Mapping[str, GateStatus],
    cg_gates: Iterable[GateRecord],
    owner_f0_a_authorized: bool = False,
) -> CoreIntegrationDecision:
    """
    Evaluate Core Foundation Integration Gate (CG00-CG11) independently from M08 harness readiness.
    Missing any M00-M08 package or CI01-CI24 seam blocks core_integration_ready even if M08 PASSes.
    Product/GPU/Human/SIP statuses remain strictly NOT_RUN/HOLD.
    """
    blockers: list[str] = []
    for pkg in REQUIRED_FOUNDATION_PACKAGES:
        st = package_statuses.get(pkg, GateStatus.NOT_RUN)
        if st != GateStatus.PASS:
            blockers.append(f"MISSING_OR_NONPASS_PACKAGE:{pkg}:{st.value}")

    for cid in REQUIRED_CI_CASES:
        st = ci_results.get(cid, GateStatus.NOT_RUN)
        if st != GateStatus.PASS:
            blockers.append(f"CI_NOT_PASS:{cid}:{st.value}")

    cg_summary = evaluate_gates(cg_gates)
    cg_ids = {g.gate_id for g in cg_summary.gates}
    for req_cg in REQUIRED_CG_GATES:
        if req_cg not in cg_ids:
            blockers.append(f"MISSING_CG_GATE:{req_cg}")

    blockers.extend(cg_summary.blocking_reasons)

    if any(":FAIL:" in b or b.startswith("CI_NOT_PASS:") and ":FAIL" in b for b in blockers):
        core_status = GateStatus.FAIL
    elif blockers or not cg_summary.ready:
        core_status = GateStatus.HOLD
    else:
        core_status = GateStatus.PASS

    core_ready = (core_status == GateStatus.PASS) and m08_summary.ready and not blockers
    return CoreIntegrationDecision(
        package_id="CORE_INTEGRATION",
        m08_ready=m08_summary.ready,
        m08_status=m08_summary.overall,
        core_integration_ready=core_ready,
        core_integration_status=core_status,
        vertical_slice_ready=core_ready,
        owner_execution_authorized=owner_f0_a_authorized,
        synthetic_product_acceptance_status=GateStatus.NOT_RUN,
        hardware_acceptance_status=GateStatus.NOT_RUN,
        human_sip_status=GateStatus.NOT_RUN,
        run_id=run_id,
        accepted_dependency_runs=tuple(f"{p}:{package_statuses.get(p, GateStatus.NOT_RUN).value}" for p in REQUIRED_FOUNDATION_PACKAGES),
        blocking_reasons=tuple(blockers),
    )
