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
from typing import Iterable

from tests.harness.contracts import GateRecord, GateStatus


@dataclass(frozen=True, slots=True)
class AcceptanceSummary:
    overall: GateStatus
    ready: bool
    mandatory_pass_count: int
    mandatory_fail_count: int
    mandatory_hold_count: int
    mandatory_not_run_count: int
    optional_fail_count: int
    gates: tuple[GateRecord, ...]
    blocking_reasons: tuple[str, ...]


def evaluate_gates(gates: Iterable[GateRecord]) -> AcceptanceSummary:
    """
    Exact mandatory gate truth table:
    - Any mandatory FAIL => overall FAIL, ready=False
    - Else any mandatory HOLD or NOT_RUN => overall HOLD, ready=False
    - Else all mandatory PASS => overall PASS, ready=True
    Optional gates cannot mask mandatory failures or holds.
    """
    gate_list = tuple(gates)
    m_pass = m_fail = m_hold = m_not_run = o_fail = 0
    blockers: list[str] = []

    for g in gate_list:
        if g.mandatory:
            if g.status == GateStatus.PASS:
                m_pass += 1
            elif g.status == GateStatus.FAIL:
                m_fail += 1
                blockers.append(f"{g.gate_id}:FAIL:{g.reason}")
            elif g.status == GateStatus.HOLD:
                m_hold += 1
                blockers.append(f"{g.gate_id}:HOLD:{g.reason}")
            else:
                m_not_run += 1
                blockers.append(f"{g.gate_id}:NOT_RUN:{g.reason}")
        else:
            if g.status == GateStatus.FAIL:
                o_fail += 1

    if not gate_list or m_fail > 0:
        overall = GateStatus.FAIL
    elif m_hold > 0 or m_not_run > 0:
        overall = GateStatus.HOLD
    else:
        overall = GateStatus.PASS

    return AcceptanceSummary(
        overall=overall,
        ready=(overall == GateStatus.PASS),
        mandatory_pass_count=m_pass,
        mandatory_fail_count=m_fail,
        mandatory_hold_count=m_hold,
        mandatory_not_run_count=m_not_run,
        optional_fail_count=o_fail,
        gates=gate_list,
        blocking_reasons=tuple(blockers),
    )
