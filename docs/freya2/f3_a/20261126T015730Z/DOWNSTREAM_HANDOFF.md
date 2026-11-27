# F3-A Downstream Handoff

- **Run ID**: `20261126T015730Z`
- **F4-A (Linguistic Frontend)**: Consumes immutable M01 `DialogueResponse` emitted by `backend/supervisor/dialogue_facade.py` (`DialogueFacade.process_asr_turn` -> `BoundedDialogueConsumer.admit_response`). `speech_text` is semantic Turkish only (zero F4 normalization, IPA, or SSML); `speech_act`, `focus_entity_refs`, `verified_fact_refs`, `tool_receipt_refs`, `state_revision`, `source_asr_revision`, and `outcome` are preserved.
- **F2-B / F1-C**: Bounded non-sensitive cues and `DialogueContextSnapshot` candidate-vs-confirmed slot distinctions (`SlotStatus`) are exposed via `backend/supervisor/context_manager.py` and `slot_manager.py`.
- **F3-B / F3-C**: `WorkflowAdapter` and `StateAdapter` document existing allowlisted workflows under M07 (`PolicyEngine`, `ConfirmationManager`, `DurableIdempotencyStore`, `SecurityAuditLog`, `IdempotencyReconciler`) without introducing new specialist agents or unapproved write tools.
