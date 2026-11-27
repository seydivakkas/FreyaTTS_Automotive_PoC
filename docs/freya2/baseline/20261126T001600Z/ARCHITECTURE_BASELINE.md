# Architecture Baseline (20261126T001600Z)

- **Repository:** `FreyaTTS_Automotive_PoC` (`HEAD 6273981e1684686ae85f9458b608764e85a4552c`, branch `master`, working tree dirty prior to M00)
- **Web entrypoint:** `backend/main.py` (`app`, `lifespan`, `/api/session-ticket`, `/ws/voice`, 14 included routers, static UI mount `frontend/dist`)
- **Telephony entrypoints:** `backend/audiosocket_server.py` (`AudioSocketOrchestrator`, TCP 9092, 8 kHz slin16 20 ms) & `backend/websocket_adapter.py` (`chan_ws_adapter`, WS 8088)
- **Session & Dialogue:** `backend/session.py` (`VoiceSession`), `backend/milestones.py` (`LiveControl`), `backend/dialogue.py` (`Dialogue`), `backend/supervisor/` (`WebSupervisor`, `ToolGateway`)
- **Existing Core Contracts:** `automotive_voice/core/` (`identifiers.py`, `events.py`, `event_bus.py`, `cancellation.py`, `session.py`, `session_manager.py`, `audio.py`), `contracts/*.schema.json` (31 JSON Schemas), `backend/supervisor/contracts.py`, `backend/morphology/contracts.py`
- **Target Freya 2.0 Core Packages:** `backend/core/{contracts,adapters,runtime,configuration,model_registry}`, `backend/observability/`, `backend/shared_lexicon/`, `backend/runtime_resources/`, `backend/security/`
