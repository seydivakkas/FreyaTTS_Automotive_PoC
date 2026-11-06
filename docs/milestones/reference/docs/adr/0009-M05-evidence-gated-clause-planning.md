# ADR 0009 — Evidence-gated, text-only clause planning

Status: Accepted for M05 mock architecture.

Context: Turkish automotive speech prep needs correct punctuation and non-splitting of multi-token money/date/time/name phrases, without premature Freya audio tests.

Decision: M04 immutable `NormalizationResult` -> deterministic `ProsodyClausePlanner` -> immutable `ClausePlan` and `TTSInput` -> bounded mock queue. Review-required entries never get TTS inputs. M01 `SessionId/TurnId/GenerationId` and M02 `START_TTS` references remain authoritative. Read-only A01-YT does not auto-approve pronunciations.

Consequences: Reproducible text plans and simulated cancellation, but neither audio quality nor production durability is proven. Pause/delivery hints are not actual speech style controls. M06 must implement real media interface boundaries without voice tests.
