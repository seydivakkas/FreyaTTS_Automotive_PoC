# W2 Vertical Slice Composition Map (20261126T032114Z)

Real implemented F0-A through F6-A and M01-M08 modules are composed end-to-end across Web 16 kHz and Phone AudioSocket 8 kHz profiles, with test doubles restricted strictly to external model/provider/clock/transport boundaries:

| Stage | Real Package Authority | External / Model Boundary Double (M08 / Test-Only) | Output Contract |
|---|---|---|---|
| F0-A | `backend.audio_frontend.AudioInputPipeline` | `HarnessClock`, `SyntheticAudioGenerator` (PCM_S16LE 8k/16k) + `generate_dtmf_tone` | 16 kHz mono `AudioFrame` + `DTMFEvent` |
| F1-A | `backend.voice_activity.StreamAcousticProcessor` + `M02TurnAllocatorBridge` + `BoundedUtteranceQueue` | `_ScriptedVADModel` (state-passing score fixture) | Finalized `Utterance` |
| F2-A | `backend.speech_recognition.SpeechRecognitionPipeline` + `WhisperSchedulerEngine` (M06 P1) | `_FakeWhisperModel` (lazy iterator) + `FakeGPUProbeAdapter` | `ASRResult` + M05 `EntityCandidate` |
| F3-A | `backend.supervisor.dialogue_facade.DialogueFacade` + M07 `WorkflowAdapter` / `PolicyEngine` / `ConfirmationManager` / `DurableIdempotencyStore` | `FakeOllamaWorker` (P3 LLM proposal), `FakeIdentityProvider`, isolated SQLite `crm.db` | `DialogueResponse` + `ToolReceipt` |
| F4-A | `backend.linguistic_frontend.LinguisticFrontendPipeline` + `FreyaVocabularyValidator` (`config/freya_vocab.json`) | None (real M03/M05/vocab) | Immutable `SynthesisPlan` (`normalization_passes=1`, seed 9) |
| F5-A | `backend.neural_synthesis.NeuralSynthesisPipeline` + `ModelResidencyAdapter` (M06 P2/P4) | `_FakeDiT` + `_FakeVAE` (48 kHz mono Float32 waveform) | Raw 48 kHz mono `FLOAT32_LE` `AudioChunk` |
| F6-A | `backend.audio_rendering.AudioRenderingPipeline` + `WebTransportAdapter` / `AudioSocketOutboundAdapter` | `HarnessClock` + `FakeAudioSocketTransport` / in-memory `web_frames` list | `RenderedFrame` (640 B Web 16k / 323 B AudioSocket 8k) + SERVER `SubmissionRecord` |
