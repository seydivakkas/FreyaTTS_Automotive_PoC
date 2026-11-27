"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import pytest

from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.linguistic_frontend import format_turkish_phone, format_turkish_time
from backend.security import (
    CallerVerificationRecord,
    CallerVerificationSession,
    CallerVerificationStatus,
)
from backend.supervisor.ai_disclosure import (
    AI_DISCLOSURE_GREETING,
    AI_DISCLOSURE_HUMAN_QUESTION_REPLY,
    AI_DISCLOSURE_INTERRUPTED_FOLLOWUP,
    AIDisclosureTracker,
    DEFAULT_EMBEDDING_POLICY,
)


def test_adr_f4_02_natural_turkish_time() -> None:
    assert format_turkish_time(0, 0) == "gece yarısı"
    assert format_turkish_time(0, 0, with_locative=True) == "gece yarısında"
    assert format_turkish_time(9, 30) == "sabah dokuz buçuk"
    assert format_turkish_time(14, 0) == "öğleden sonra iki"
    assert format_turkish_time(14, 30, with_locative=True) == "öğleden sonra iki buçukta"
    assert format_turkish_time(18, 30) == "akşam altı buçuk"
    assert format_turkish_time(9, 15) == "sabah dokuzu çeyrek geçe"
    assert format_turkish_time(20, 15) == "akşam sekizi çeyrek geçe"
    assert format_turkish_time(9, 45) == "sabah ona çeyrek var"
    assert format_turkish_time(11, 45) == "sabah on ikiye çeyrek var"
    assert format_turkish_time(9, 40, with_locative=True) == "sabah ona yirmi kala"
    assert format_turkish_time(23, 0) == "gece on bir"
    with pytest.raises(ValueError):
        format_turkish_time(25, 0)


def test_adr_f4_03_turkish_phone_4322_grouping() -> None:
    assert format_turkish_phone("0532 123 45 67") == "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"
    assert format_turkish_phone("+90 (532) 123-45-67") == "sıfır beş yüz otuz iki, yüz yirmi üç, kırk beş, altmış yedi"
    assert format_turkish_phone("0212 400 07 00") == "sıfır iki yüz on iki, dört yüz, sıfır yedi, sıfır sıfır"
    assert format_turkish_phone("0532 045 00 05") == "sıfır beş yüz otuz iki, sıfır kırk beş, sıfır sıfır, sıfır beş"
    # Short / non-11-digit fallback without inventing missing digits
    assert format_turkish_phone("444 0 123") == "dört dört dört sıfır bir iki üç"


def test_adr_f3_01_caller_second_factor_verification() -> None:
    # Birth year preferred
    rec = CallerVerificationRecord(customer_ref="cust-1", birth_year="1988", plate="34ABC1234")
    sess = CallerVerificationSession(call_id="call-1", record=rec)
    assert sess.required_factor_kind() == "birth_year"

    r1 = sess.verify_attempt(provided_value="1990")
    assert r1.status == CallerVerificationStatus.FAILED_RETRY
    assert r1.verified is False
    assert r1.attempts_remaining == 2
    assert "1988" not in repr(r1)

    r2 = sess.verify_attempt(provided_value="1988")
    assert r2.status == CallerVerificationStatus.VERIFIED
    assert r2.verified is True

    # Plate fallback + 3-attempt lock
    rec_plate = CallerVerificationRecord(customer_ref="cust-2", birth_year=None, plate="34 XYZ 987")
    sess2 = CallerVerificationSession(call_id="call-2", record=rec_plate)
    assert sess2.required_factor_kind() == "plate_suffix"
    assert sess2.verify_attempt(provided_value="000").status == CallerVerificationStatus.FAILED_RETRY
    assert sess2.verify_attempt(provided_value="111").status == CallerVerificationStatus.FAILED_RETRY
    locked = sess2.verify_attempt(provided_value="222")
    assert locked.status == CallerVerificationStatus.LOCKED_OPERATOR_REQUIRED
    assert locked.requires_operator_transfer is True
    # Even correct value after lock stays locked for this call
    assert sess2.verify_attempt(provided_value="987").status == CallerVerificationStatus.LOCKED_OPERATOR_REQUIRED

    # Valid plate suffix succeeds when not locked
    sess3 = CallerVerificationSession(call_id="call-3", record=rec_plate)
    assert sess3.verify_attempt(provided_value="987").verified is True

    # No second factor on record -> operator required
    sess4 = CallerVerificationSession(call_id="call-4", record=CallerVerificationRecord(customer_ref="cust-4"))
    no_factor = sess4.verify_attempt(provided_value="1990")
    assert no_factor.status == CallerVerificationStatus.NO_SECOND_FACTOR_ON_RECORD
    assert no_factor.requires_operator_transfer is True


def test_adr_x_03_and_f3_02_and_pipeline_v2_flags() -> None:
    tracker = AIDisclosureTracker()
    assert AI_DISCLOSURE_GREETING in tracker.build_greeting_text("Nasıl yardımcı olabilirim?")
    tracker.mark_greeting_interrupted()
    assert tracker.is_disclosed is False
    next_msg = tracker.wrap_next_reply("Randevunuzu kontrol ediyorum.")
    assert next_msg.startswith(AI_DISCLOSURE_INTERRUPTED_FOLLOWUP)
    assert tracker.is_disclosed is True
    assert "yapay zekâ" in tracker.answer_human_inquiry()
    assert AI_DISCLOSURE_HUMAN_QUESTION_REPLY == tracker.answer_human_inquiry()

    assert DEFAULT_EMBEDDING_POLICY.model_id == "bge-m3"
    assert DEFAULT_EMBEDDING_POLICY.device == "cpu"
    assert DEFAULT_EMBEDDING_POLICY.allow_gpu is False

    flags = FeatureFlagRegistry.default()
    for i in range(7):
        assert flags.values[f"f{i}_pipeline_v2"] is False
