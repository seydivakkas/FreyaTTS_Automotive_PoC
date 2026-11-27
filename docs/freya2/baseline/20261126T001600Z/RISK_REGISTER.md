# M00 Risk Register (20261126T001600Z)

| ID | Severity | Status | Source | Description |
|---|---|---|---|---|
| RISK-BASE-01 | High | CONFIRMED | `backend/dialogue.py:1174`, `backend/dialogue.py:423` | `_MULTI_VEHICLE_RE` matches `"İkinci aracım Renault Megane."` and resets state before vehicle lookup; `reset_for_next_vehicle()` leaves `multi_vehicle_planned=True`, causing 2 failing cases in `tests/test_madde3_customer_experience.py`. |
| RISK-BASE-02 | High | CONFIRMED | `backend/dialogue.py:1917,1970`, `backend/text.py:192` | `normalize(" . ")` raises `ValueError("Seslendirilebilir metin bulunamadı")` which crashes `_match_vehicles()` / `_apply_extract()`, causing 2 failing cases in `tests/test_voice_path_honesty.py`. |
| RISK-ARCH-01 | Medium | CONFIRMED | `automotive_voice/core/` vs `backend/core/` | Legacy M01-M11 `automotive_voice/core/` (`schema_version="1.0"`) already coexists with `backend/supervisor/contracts.py` and `backend/morphology/contracts.py`. Freya 2.0 `backend/core/` must wrap/reuse rather than duplicate. |
| RISK-ENV-01 | Medium | CONFIRMED | Dirty working tree | 51 modified + 12 untracked paths existed at M00 start; preserve all user edits. |
