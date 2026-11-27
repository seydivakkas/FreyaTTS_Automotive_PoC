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

from backend.observability.evidence import EvidenceKind
from backend.security import (
    AccessContext,
    AuthStrength,
    EvidenceSource,
    PrincipalKind,
    PrincipalRef,
    anonymous_principal,
    untrusted_principal,
    verified_principal,
)


class FakeIdentityProvider:
    """Synthetic opaque principal & resource-scope fixture provider (no real PII)."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME

    def __init__(self) -> None:
        self._owned_resources: dict[str, frozenset[str]] = {
            "cust-syn-001": frozenset({"rec-syn-001", "veh-syn-001"}),
            "cust-syn-002": frozenset({"rec-syn-002", "veh-syn-002"}),
        }

    def verified_customer(self, customer_id: str = "cust-syn-001", *, strong: bool = True) -> PrincipalRef:
        return verified_principal(
            customer_id,
            kind=PrincipalKind.CUSTOMER,
            auth_strength=AuthStrength.STRONG_VERIFIED if strong else AuthStrength.CHANNEL_VERIFIED,
            evidence_source=EvidenceSource.MFA_VERIFIED if strong else EvidenceSource.OTP_CHALLENGE,
        )

    def untrusted_caller(self, claimed_id: str = "cust-syn-001") -> PrincipalRef:
        return untrusted_principal(claimed_id, evidence_source=EvidenceSource.CALLER_ID)

    def anonymous(self) -> PrincipalRef:
        return anonymous_principal()

    def can_access_record(self, principal: PrincipalRef, record_id: str) -> bool:
        if not principal.verified:
            return False
        owned = self._owned_resources.get(principal.principal_id, frozenset())
        return record_id in owned

    def make_context(
        self,
        *,
        session_id: str,
        principal: PrincipalRef,
        channel: str = "web",
        state_revision: int = 1,
    ) -> AccessContext:
        return AccessContext(
            session_id=session_id,
            principal=principal,
            channel=channel,
            state_revision=state_revision,
        )
