# Hat izi (F0–F6)

Taban commit `6f5867a` · Statik tarama (AST/regex); çalışma kanıtı değildir. Dosya/sembol başvuruları; çağrı grafiği çalıştırılarak doğrulanmadı.

## F0
- `backend/audio.py` — PRESENT · üst düzey tanımlar: `resample`:12, `pcm`:17, `frames`:21, `pace`:26, `Endpoint`:38
- `backend/car_denoiser.py` — PRESENT · üst düzey tanımlar: `CarNoiseFilter`:32, `SpectralNoiseSuppressor`:82, `SoftAGC`:229, `InboundCarDenoiser`:342, `process_audio_stream`:614
- `backend/dsp.py` — PRESENT · üst düzey tanımlar: `apply_fade_and_comfort_noise`:8, `apply_telephony_eq_and_downsample_8k`:26
- `backend/audiosocket_server.py` — PRESENT · üst düzey tanımlar: `read_packet`:82, `build_packet`:92, `LookbackBuffer`:97, `AudioPacer`:172, `TwoStageBargeInController`:252, `AudioSocketOrchestrator`:338
- `backend/websocket_adapter.py` — PRESENT · üst düzey tanımlar: `build_command`:57, `parse_event`:63, `ChanWebSocketSession`:75, `ChanWebSocketAdapter`:201

## F1
- `backend/session.py` — PRESENT · üst düzey tanımlar: `_metrics`:29, `VoiceSession`:39
- `backend/audio.py` — PRESENT · üst düzey tanımlar: `resample`:12, `pcm`:17, `frames`:21, `pace`:26, `Endpoint`:38
- `backend/semantic_turn_detector.py` — PRESENT · üst düzey tanımlar: `SemanticAnalysisResult`:181, `TurnDecision`:196, `normalize_turkish_text`:214, `analyze_semantic_completeness`:221, `resample_to_16k`:337, `estimate_f0_pitch_slope`:355, `SemanticTurnDetector`:405, `SmartTurnAudioSocketAdapter`:505

## F2
- `backend/models.py` — PRESENT · üst düzey tanımlar: `Models`:32
- `experimental/asr_mapper.py` — PRESENT · üst düzey tanımlar: `ASRMapper`:37, `canonicalize_asr_text`:220

## F3
- `backend/dialogue.py` — PRESENT · üst düzey tanımlar: `_find_active_appointment`:74, `Extract`:91, `_tr_lower`:136, `_tr_title`:140, `parse_name_sentence`:147, `_squash`:162, `parse_selected_option`:166, `extract_phone_number`:183, `Dialogue`:257
- `backend/caller_memory.py` — PRESENT · üst düzey tanımlar: `normalize_phone`:24, `normalize_plate`:38, `get_or_create_caller_profile`:50, `format_caller_memory_context`:130, `resolve_warranty_inquiry`:185, `resolve_past_maintenance`:246, `add_maintenance_record`:282, `seed_default_profiles`:310
- `backend/db.py` — PRESENT · üst düzey tanımlar: `pragmas`:18, `uid`:26, `now`:30, `Base`:34, `Vehicle`:38, `InspectionReport`:46, `VehicleDiagnostic`:73, `Quote`:113, `Slot`:120, `Appointment`:127, `InspectionLift`:156, `InspectionQueue`:186, `CorporateAccount`:220, `CorporateLedger`:235 …
- `backend/supervisor/__init__.py` — PRESENT · üst düzey tanımlar: —

## F4
- `backend/text.py` — PRESENT · üst düzey tanımlar: `normalize`:67, `date_words`:177, `protected_atoms`:189, `turkish_capitalize`:236, `prepare_tts_clause`:246, `clauses`:263
- `backend/automotive_frontend.py` — PRESENT · üst düzey tanımlar: `load_freya_vocab`:77, `AutomotiveTextNormalizer`:104, `AutomotiveDSPChain`:342, `AutomotiveFrontend`:478
- `backend/normalizer_rules.py` — PRESENT · üst düzey tanımlar: `load_custom_lexicon`:171, `save_custom_lexicon`:206, `get_lexicon`:216, `get_lexicon_entries`:222, `set_lexicon_term`:254, `delete_lexicon_term`:304, `reset_to_base_lexicon`:331, `spell_tr_int`:368, `harmonize_suffix`:403, `normalize_automotive_turkish`:491

## F5
- `backend/models.py` — PRESENT · üst düzey tanımlar: `Models`:32
- `backend/batched_ode.py` — PRESENT · üst düzey tanımlar: `clause_frame_count`:46, `check_voicedness`:54, `BatchItem`:99, `ConcurrentCallController`:107, `BatchedODEEngine`:163
- `backend/sft_leyla.py` — PRESENT · üst düzey tanımlar: `LeylaSFTConfig`:48, `freeze_for_conservative_sft`:93, `IdentityDriftGuard`:132, `AutomotiveCorpusBuilder`:199, `ConservativeSFTTrainer`:311, `FreyaCrossAttentionLoRAConfig`:565, `FreyaCrossAttentionLoRAManager`:617

## F6
- `backend/dsp.py` — PRESENT · üst düzey tanımlar: `apply_fade_and_comfort_noise`:8, `apply_telephony_eq_and_downsample_8k`:26
- `backend/audiosocket_server.py` — PRESENT · üst düzey tanımlar: `read_packet`:82, `build_packet`:92, `LookbackBuffer`:97, `AudioPacer`:172, `TwoStageBargeInController`:252, `AudioSocketOrchestrator`:338
- `backend/telephony.py` — PRESENT · üst düzey tanımlar: `register_inbound_metadata`:38, `get_inbound_metadata`:61, `connection`:66
- `experimental/prosody_wsola_streamer.py` — PRESENT · üst düzey tanımlar: `IntentCategory`:49, `ProsodyProfile`:60, `VoicingReport`:117, `SynthesizedClause`:128, `WSOLATimeStretch`:152, `ContextualProsodyPlanner`:275, `DurationFloorGuard`:371, `AudioVoicingChecker`:410, `ModelHashAndSeedGuard`:506, `OverlappingClauseStreamer`:545
