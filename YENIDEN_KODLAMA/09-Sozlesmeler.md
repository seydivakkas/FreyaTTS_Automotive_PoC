# Olay ve mesaj sözleşmeleri

Üretici ve tüketicileri aynı şema sürümüne göre doğrulayın. Zorunlu alanlar, sabitler ve değer kümeleri her mesajın kendi şemasındadır.


### contracts/access_context.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/access_context.schema.json",
  "type": "object", "additionalProperties": false,
  "required": ["authenticated", "crm_processing_allowed", "marketing_opt_in"],
  "properties": {
    "authenticated": {"type": "boolean"},
    "crm_processing_allowed": {"type": "boolean"},
    "marketing_opt_in": {"type": "boolean"}
  }
}
````


### contracts/approved_lexicon_rule.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/approved_lexicon_rule.schema.json",
  "type": "object", "additionalProperties": false,
  "required": ["canonical","spoken_tr","approved","source_ref","reviewer","evidence","aliases","suffix_map","context"],
  "properties": {
    "canonical": {"type":"string","minLength":1},
    "spoken_tr": {"type":"string","minLength":1},
    "approved": {"const":true},
    "source_ref": {"type":"string","minLength":1},
    "reviewer": {"type":"string","minLength":1},
    "evidence": {"type":"array","minItems":1,"items":{"type":"object","required":["annotation_id","clip_id","source_url"]}},
    "aliases": {"type":"array","items":{"type":"string"}},
    "suffix_map": {"type":"object","additionalProperties":{"type":"string"}},
    "context": {"type":"string"}
  }
}
````


### contracts/audio_frame.metadata.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:audio-frame-metadata:v1",
  "title": "AudioFrameMetadata (binary payload is NOT in JSON)",
  "type": "object",
  "additionalProperties": false,
  "required": ["session_id", "stream_id", "generation_id", "seq", "sample_count", "timestamp_mono_ns", "audio_format"],
  "properties": {
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "stream_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "generation_id": {"type": "integer", "minimum": 0},
    "seq": {"type": "integer", "minimum": 0},
    "sample_count": {"type": "integer", "minimum": 1},
    "timestamp_mono_ns": {"type": "integer", "minimum": 0},
    "audio_format": {
      "oneOf": [
        {"type": "object", "properties": {"encoding": {"const":"pcm_s16le"}, "sample_width_bits": {"const":16}, "sample_rate": {"enum":[8000,16000,48000]}, "channels": {"const":1}}, "required":["encoding","sample_width_bits","sample_rate","channels"], "additionalProperties": false},
        {"type": "object", "properties": {"encoding": {"const":"float32"}, "sample_width_bits": {"const":32}, "sample_rate": {"enum":[8000,16000,48000]}, "channels": {"const":1}}, "required":["encoding","sample_width_bits","sample_rate","channels"], "additionalProperties": false},
        {"type": "object", "properties": {"encoding": {"enum":["mulaw","alaw"]}, "sample_width_bits": {"const":8}, "sample_rate": {"const":8000}, "channels": {"const":1}}, "required":["encoding","sample_width_bits","sample_rate","channels"], "additionalProperties": false}
      ]
    }
  }
}
````


### contracts/booking_receipt.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/booking_receipt.schema.json",
  "type": "object", "additionalProperties": false,
  "required": ["status", "reference_id"],
  "properties": {
    "status": {"enum": ["confirmed", "unavailable", "unknown"]},
    "reference_id": {"type": ["string", "null"], "maxLength": 128}
  },
  "allOf": [{"if": {"properties": {"status": {"const": "confirmed"}}},
    "then": {"properties": {"reference_id": {"type": "string", "minLength": 1}}},
    "else": {"properties": {"reference_id": {"type": "null"}}}}]
}
````


### contracts/clause_plan_diagnostics.schema.json

````json
{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"urn:freya-automotive:m05-clause-diagnostics:v1",
  "title":"Safe M05 plan metadata, never raw user or response text",
  "type":"object","additionalProperties":false,
  "required":["session_id","turn_id","generation_id","status","clause_count","protected_span_count","warning_codes"],
  "properties":{
    "session_id":{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "turn_id":{"type":"integer","minimum":0},
    "generation_id":{"type":"integer","minimum":0},
    "status":{"enum":["ready","review_required"]},
    "clause_count":{"type":"integer","minimum":1},
    "protected_span_count":{"type":"integer","minimum":0},
    "warning_codes":{"type":"array","items":{"type":"string"}}
  }
}
````


### contracts/conversation_effect.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:conversation-effect:v1",
  "title": "M02 Effect command metadata (delivery is not implied)",
  "type": "object",
  "additionalProperties": false,
  "required": ["effect_id", "kind", "session_id", "turn_id", "generation_id", "related_event_id", "reference"],
  "properties": {
    "effect_id": {"type": "string", "format": "uuid"},
    "kind": {"enum": ["request_llm", "start_tts", "queue_audio", "cancel_generation", "flush_media", "start_handoff", "terminate_call"]},
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "turn_id": {"type": "integer", "minimum": 0},
    "generation_id": {"type": "integer", "minimum": 0},
    "related_event_id": {"type": "string", "format": "uuid"},
    "reference": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$"}
  }
}
````


### contracts/conversation_signal.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:conversation-signal:v1",
  "title": "M02 ConversationSignal — inbound metadata (no raw speech)",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_id", "kind", "session_id", "turn_id", "generation_id", "sequence", "occurred_at_utc", "occurred_mono_ns", "reference", "flush_request_id"],
  "properties": {
    "event_id": {"type": "string", "format": "uuid"},
    "kind": {"enum": ["session_opened", "vad_speech_started", "transcript_final", "llm_response_ready", "audio_chunk_ready", "playout_finished", "media_flush_ack", "media_flush_timeout", "handoff_requested", "hangup"]},
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "turn_id": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "generation_id": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "sequence": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "occurred_at_utc": {"type": "string", "format": "date-time"},
    "occurred_mono_ns": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "reference": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$"},
    "flush_request_id": {"type": ["string", "null"], "format": "uuid"}
  },
  "allOf": [
    {"if": {"properties": {"kind": {"enum": ["transcript_final", "llm_response_ready", "audio_chunk_ready"]}}}, "then": {"properties": {"reference": {"type": "string"}, "flush_request_id": {"const": null}}}, "else": {"properties": {"reference": {"const": null}}}},
    {"if": {"properties": {"kind": {"enum": ["media_flush_ack", "media_flush_timeout"]}}}, "then": {"properties": {"flush_request_id": {"type": "string"}}}, "else": {"properties": {"flush_request_id": {"const": null}}}}
  ]
}
````


### contracts/dialogue_input.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/dialogue_input.schema.json",
  "title": "M03 structured NLU output (never raw transcript)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "intent"
  ],
  "properties": {
    "intent": {
      "enum": [
        "greeting",
        "vehicle_lookup",
        "price_lookup",
        "request_inspection",
        "confirm",
        "recheck_booking",
        "decline",
        "handoff",
        "unknown",
        "create_crm_case"
      ]
    },
    "vehicle_id": {
      "type": [
        "string",
        "null"
      ],
      "pattern": "^[a-zA-Z0-9_-]{1,48}$"
    },
    "slot": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "start_at",
            "location_id"
          ],
          "properties": {
            "start_at": {
              "type": "string",
              "minLength": 20,
              "maxLength": 40,
              "description": "Offset-aware ISO 8601; additional runtime datetime validation"
            },
            "location_id": {
              "type": "string",
              "pattern": "^[a-zA-Z0-9_-]{1,48}$"
            }
          }
        }
      ]
    },
    "case_kind": {
      "type": [
        "string",
        "null"
      ],
      "enum": [
        "expertise_info",
        "price_request",
        "callback",
        null
      ]
    }
  }
}
````


### contracts/event.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:event:v1",
  "title": "EventEnvelope",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "event_id", "event_type", "session_id", "turn_id", "generation_id", "sequence", "occurred_at_utc", "occurred_mono_ns", "payload"],
  "properties": {
    "schema_version": {"const": "1.0"},
    "event_id": {"type": "string", "format": "uuid"},
    "event_type": {"enum": ["session_started", "turn_started", "user_speech_started", "transcript_final", "response_started", "audio_chunk_enqueued", "playout_finished", "interrupted", "interruption_completed", "handoff_requested", "session_ended", "session_failed", "state_changed", "error"]},
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "turn_id": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "generation_id": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "sequence": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
    "occurred_at_utc": {"type": "string", "format": "date-time"},
    "occurred_mono_ns": {"type": "integer", "minimum": 0},
    "payload": {"type": "object"}
  }
}
````


### contracts/m06_audio_chunk_metadata.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m06_audio_chunk_metadata:v1",
  "title": "M06 AudioChunkMetadata (no audio payload)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "session_id",
    "turn_id",
    "generation_id",
    "stream_id",
    "seq",
    "sample_count",
    "duration_ms",
    "timestamp_mono_ns",
    "clause_index",
    "media_format"
  ],
  "properties": {
    "session_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    },
    "turn_id": {
      "type": "integer",
      "minimum": 0
    },
    "generation_id": {
      "type": "integer",
      "minimum": 0
    },
    "stream_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9._:-]+$"
    },
    "seq": {
      "type": "integer",
      "minimum": 0
    },
    "sample_count": {
      "type": "integer",
      "minimum": 1
    },
    "duration_ms": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2000
    },
    "timestamp_mono_ns": {
      "type": "integer",
      "minimum": 0
    },
    "clause_index": {
      "type": "integer",
      "minimum": 0
    },
    "media_format": {
      "$ref": "m06_media_format.schema.json"
    }
  }
}
````


### contracts/m06_flush_ack.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m06_flush_ack:v1",
  "title": "M06 FlushAck (simulation receipt, NOT PBX proof)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "session_id",
    "turn_id",
    "generation_id",
    "flush_request_id",
    "adapter_id",
    "confirmed_by_adapter",
    "adapter_kind"
  ],
  "properties": {
    "session_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    },
    "turn_id": {
      "type": "integer",
      "minimum": 0
    },
    "generation_id": {
      "type": "integer",
      "minimum": 0
    },
    "flush_request_id": {
      "type": "string",
      "format": "uuid"
    },
    "adapter_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 64
    },
    "confirmed_by_adapter": {
      "type": "boolean"
    },
    "adapter_kind": {
      "enum": [
        "fake",
        "asterisk"
      ]
    }
  }
}
````


### contracts/m06_flush_request.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m06_flush_request:v1",
  "title": "M06 FlushRequest",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "session_id",
    "turn_id",
    "generation_id",
    "flush_request_id"
  ],
  "properties": {
    "session_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    },
    "turn_id": {
      "type": "integer",
      "minimum": 0
    },
    "generation_id": {
      "type": "integer",
      "minimum": 0
    },
    "flush_request_id": {
      "type": "string",
      "format": "uuid"
    }
  }
}
````


### contracts/m06_media_format.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m06_media_format:v1",
  "title": "M06 MediaFormat metadata (runtime enforces codec-specific values)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "codec",
    "sample_rate_hz",
    "channels",
    "rtp_clock_hz"
  ],
  "properties": {
    "codec": {
      "enum": [
        "pcm_s16le",
        "alaw",
        "mulaw",
        "g722"
      ]
    },
    "sample_rate_hz": {
      "type": "integer",
      "enum": [
        8000,
        16000,
        48000
      ]
    },
    "channels": {
      "const": 1
    },
    "rtp_clock_hz": {
      "type": [
        "integer",
        "null"
      ]
    }
  }
}
````


### contracts/m06_transport_control.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m06_transport_control:v1",
  "title": "M06 Asterisk JSON dry-run command",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "command"
  ],
  "properties": {
    "command": {
      "enum": [
        "FLUSH_MEDIA",
        "HANGUP"
      ]
    },
    "correlation_id": {
      "type": "string",
      "format": "uuid"
    }
  }
}
````


### contracts/m07_health_snapshot.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m07_health_snapshot:v1",
  "title": "M07 Mock Health Snapshot",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "kind",
    "state",
    "circuit",
    "queued",
    "in_flight",
    "completed",
    "last_error_code",
    "observed_mono_ns",
    "mock_only"
  ],
  "properties": {
    "kind": {
      "type": "string",
      "enum": [
        "stt",
        "tts",
        "llm",
        "telephony"
      ]
    },
    "state": {
      "type": "string",
      "enum": [
        "created",
        "starting",
        "ready",
        "degraded",
        "stopping",
        "stopped",
        "failed"
      ]
    },
    "circuit": {
      "type": "string",
      "enum": [
        "closed",
        "open",
        "half_open"
      ]
    },
    "queued": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "in_flight": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "completed": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "last_error_code": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1
        },
        {
          "type": "null"
        }
      ]
    },
    "observed_mono_ns": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "mock_only": {
      "const": true
    }
  }
}
````


### contracts/m07_retry_policy.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m07_retry_policy:v1",
  "title": "M07 Explicit Retry Policy",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "max_attempts",
    "base_delay_ns",
    "max_delay_ns"
  ],
  "properties": {
    "max_attempts": {
      "type": "integer",
      "minimum": 1,
      "maximum": 16
    },
    "base_delay_ns": {
      "type": "integer",
      "minimum": 1
    },
    "max_delay_ns": {
      "type": "integer",
      "minimum": 1
    }
  }
}
````


### contracts/m07_stream_receipt.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m07_stream_receipt:v1",
  "title": "M07 Stream Receipt",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "accepted",
    "reason",
    "command_id"
  ],
  "properties": {
    "accepted": {
      "type": "boolean"
    },
    "reason": {
      "type": "string",
      "minLength": 1
    },
    "command_id": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^[A-Za-z0-9_.:/-]{1,128}$"
        },
        {
          "type": "null"
        }
      ]
    }
  }
}
````


### contracts/m07_synthetic_command.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m07_synthetic_command:v1",
  "title": "M07 Synthetic Command - no raw text or audio",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "command_id",
    "kind",
    "session_id",
    "turn_id",
    "generation_id",
    "sequence",
    "payload_ref",
    "deadline_mono_ns",
    "idempotent"
  ],
  "properties": {
    "command_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_.:/-]{1,128}$"
    },
    "kind": {
      "type": "string",
      "enum": [
        "stt",
        "tts",
        "llm",
        "telephony"
      ]
    },
    "session_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    },
    "turn_id": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "generation_id": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "sequence": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "payload_ref": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_.:/-]{1,128}$"
    },
    "deadline_mono_ns": {
      "type": "integer",
      "minimum": 1,
      "maximum": 9223372036854775807
    },
    "idempotent": {
      "type": "boolean"
    }
  }
}
````


### contracts/m07_synthetic_result.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m07_synthetic_result:v1",
  "title": "M07 Synthetic Result",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "command_id",
    "kind",
    "session_id",
    "turn_id",
    "generation_id",
    "code",
    "attempts",
    "output_ref"
  ],
  "properties": {
    "command_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_.:/-]{1,128}$"
    },
    "kind": {
      "type": "string",
      "enum": [
        "stt",
        "tts",
        "llm",
        "telephony"
      ]
    },
    "session_id": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    },
    "turn_id": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "generation_id": {
      "type": "integer",
      "minimum": 0,
      "maximum": 9223372036854775807
    },
    "code": {
      "type": "string",
      "enum": [
        "ok",
        "transient_failure",
        "permanent_failure",
        "timed_out",
        "stale_generation",
        "cancelled",
        "disconnected",
        "retry_exhausted"
      ]
    },
    "attempts": {
      "type": "integer",
      "minimum": 0,
      "maximum": 16
    },
    "output_ref": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^[A-Za-z0-9_.:/-]{1,128}$"
        },
        {
          "type": "null"
        }
      ]
    }
  }
}
````


### contracts/m08_operator_action.schema.json

````json
{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"urn:freya:m08:operator-action:v1",
  "type":"object","required":["action"],"additionalProperties":false,
  "properties":{
    "action":{"enum":["open","vad","transcript","llm","playout","hangup","handoff","fake_ack","xoff","xon","tick","review"]},
    "session_id":{"type":"string","maxLength":128,"pattern":"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"},
    "delta_ms":{"enum":[20,100,1600]},
    "annotation_id":{"type":"string","maxLength":128},
    "decision":{"enum":["approved","rejected"]},
    "reviewer":{"type":"string","maxLength":48},
    "reason_code":{"enum":["verified_evidence","incorrect_reading","insufficient_evidence","duplicate","other"]}
  }
}
````


### contracts/m08_operator_snapshot.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya:m08:operator-snapshot:v1",
  "title": "M08 synthetic read-only operator snapshot",
  "type": "object",
  "additionalProperties": true,
  "required": ["mode","simulation_time_ms","counts","sessions","adapters","timeline","sources","annotations","golden_summary","golden_cases","audio_bytes_generated","real_pbx_connected","production_ready"],
  "properties": {
    "mode": {"const":"OFFLINE MOCK ONLY"},
    "simulation_time_ms": {"type":"integer","minimum":0},
    "counts":{"type":"object","required":["sessions","active","waiting_flush","mock_tts_results"],"properties":{"sessions":{"type":"integer","minimum":0},"active":{"type":"integer","minimum":0},"waiting_flush":{"type":"integer","minimum":0},"mock_tts_results":{"type":"integer","minimum":0}}},
    "sessions":{"type":"array","items":{"type":"object","required":["session_id","state","turn_id","generation_id","pending_flush_id"],"properties":{"session_id":{"type":"string"},"state":{"enum":["IDLE","LISTENING","THINKING","SPEAKING","INTERRUPTING","HANDOFF","ENDED","FAILED"]},"turn_id":{"type":"integer","minimum":0},"generation_id":{"type":"integer","minimum":0},"pending_flush_id":{"type":["string","null"]}}}},
    "adapters":{"type":"array","minItems":4,"items":{"type":"object","required":["kind","state","circuit","mock_only"],"properties":{"kind":{"enum":["stt","tts","llm","telephony"]},"mock_only":{"const":true}}}},
    "timeline":{"type":"array"},"sources":{"type":"array"},"annotations":{"type":"array"},"golden_summary":{"type":"object"},"golden_cases":{"type":"array","minItems":320,"maxItems":320},
    "audio_bytes_generated":{"const":0},"real_pbx_connected":{"const":false},"production_ready":{"const":false}
  }
}
````


### contracts/m08_review_audit.schema.json

````json
{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"urn:freya:m08:review-audit:v1",
  "type":"object","additionalProperties":false,
  "required":["id","annotation_id","decision","reviewer","reason_code","source_sha256","reviewed_at"],
  "properties":{
    "id":{"type":"string","format":"uuid"},"annotation_id":{"type":"string"},
    "decision":{"enum":["approved","rejected"]},"reviewer":{"type":"string"},
    "reason_code":{"type":"string"},"source_sha256":{"type":["string","null"]},
    "reviewed_at":{"type":"string","format":"date-time"}
  }
}
````


### contracts/m09_scenario_result.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://local.freya.invalid/contracts/m09_scenario_result.schema.json",
  "title": "M09 synthetic end-to-end scenario result",
  "type": "object",
  "required": ["scenario", "passed", "checks", "sessions", "trace", "notes", "audio_bytes_generated", "real_pbx_connected", "real_crm_connected", "real_model_called", "production_ready"],
  "properties": {
    "scenario": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-z][a-z0-9_]*$"},
    "passed": {"type": "boolean"},
    "checks": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "boolean"}},
    "sessions": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id","state","turn","generation","booking_status","pending_flush","fake_transport_sent"], "properties": {"id":{"type":"string"},"state":{"type":"string"},"turn":{"type":"integer","minimum":0},"generation":{"type":"integer","minimum":0},"booking_status":{"type":"string"},"pending_flush":{"type":"boolean"},"fake_transport_sent":{"type":"integer","minimum":0}}}},
    "trace": {"type": "array", "items": {"type": "object", "required": ["ms","session","step","outcome"], "properties": {"ms":{"type":"integer","minimum":0},"session":{"type":"string"},"step":{"type":"string"},"outcome":{"type":"string"}}}},
    "notes": {"type": "array", "items": {"type": "string"}},
    "audio_bytes_generated": {"const": 0},
    "real_pbx_connected": {"const": false},
    "real_crm_connected": {"const": false},
    "real_model_called": {"const": false},
    "production_ready": {"const": false}
  },
  "additionalProperties": false
}
````


### contracts/m10_adapter_readiness.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "M10 Offline Adapter Readiness",
  "type": "object",
  "required": ["mode", "external_connections", "audio_bytes", "production_ready", "adapters"],
  "additionalProperties": false,
  "properties": {
    "mode": {"const": "M10_DRY_RUN"},
    "external_connections": {"const": 0},
    "audio_bytes": {"const": 0},
    "production_ready": {"const": false},
    "adapters": {"type": "array", "minItems": 4, "maxItems": 4,
      "items": {"type": "object", "additionalProperties": false,
        "required": ["adapter", "ready_for_activation", "dry_run_only", "findings"],
        "properties": {
          "adapter": {"enum": ["freya", "stt", "llm", "pbx"]},
          "ready_for_activation": {"const": false},
          "dry_run_only": {"const": true},
          "findings": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}
````


### contracts/m10_durable_snapshot.schema.json

````json
{
 "$schema":"https://json-schema.org/draft/2020-12/schema",
 "title":"M10 Durable Snapshot Diagnostic",
 "type":"object", "additionalProperties":false,
 "required":["sessions","pending_outbox","recovery_holds"],
 "properties":{
  "sessions":{"type":"integer","minimum":0},
  "pending_outbox":{"type":"integer","minimum":0},
  "recovery_holds":{"type":"integer","minimum":0}
 }
}
````


### contracts/nlu_diagnostics.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/nlu_diagnostics.schema.json",
  "title": "M04 non-PII NLU diagnostics — no transcript payloads",
  "type": "object", "additionalProperties": false,
  "required": ["intent","has_vehicle_id","has_slot","matched_rules","warning_codes","requires_clarification"],
  "properties": {
    "intent": {"type":"string","enum":["greeting","vehicle_lookup","create_crm_case","price_lookup","request_inspection","confirm","recheck_booking","decline","handoff","unknown"]},
    "has_vehicle_id": {"type":"boolean"},
    "has_slot": {"type":"boolean"},
    "matched_rules": {"type":"array","items":{"type":"string"}},
    "warning_codes": {"type":"array","items":{"type":"string"}},
    "requires_clarification": {"type":"boolean"}
  }
}
````


### contracts/normalization_result.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/normalization_result.schema.json",
  "title": "M04 prepared TTS text with explicit review gate",
  "type": "object", "additionalProperties": false,
  "required": ["display_text","spoken_text","rules_applied","warnings","unsupported_chars","review_required"],
  "properties": {
    "display_text": {"type":"string","minLength":1},
    "spoken_text": {"type":"string","minLength":1},
    "rules_applied": {"type":"array","items":{"type":"string"}},
    "warnings": {"type":"array","items":{"type":"string"}},
    "unsupported_chars": {"type":"array","items":{"type":"string"}},
    "review_required": {"type":"boolean"}
  }
}
````


### contracts/phrase_boundary.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:m05-phrase-boundary:v1",
  "title": "M05 protected Unicode character span in normalized spoken text",
  "type": "object", "additionalProperties": false,
  "required": ["start","end","kind","evidence"],
  "properties": {
    "start": {"type":"integer","minimum":0},
    "end": {"type":"integer","minimum":1},
    "kind": {"enum":["money","date","time","engine","model","distance","model_year","approved_lexicon"]},
    "evidence": {"type":"string","maxLength":96}
  }
}
````


### contracts/policy_decision.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://freya.example.invalid/contracts/policy_decision.schema.json",
  "title": "M03 policy output: opaque ref + status; no customer text",
  "type": "object",
  "additionalProperties": false,
  "required": ["response_ref", "booking_status", "action", "handoff_requested"],
  "properties": {
    "response_ref": {"type": ["string", "null"], "pattern": "^response:[a-f0-9]{32}$"},
    "booking_status": {"enum": ["idle", "awaiting_confirmation", "confirming", "confirmed", "unavailable", "unknown", "declined", "handoff"]},
    "action": {"type": "string", "pattern": "^[a-z_]{2,64}$"},
    "handoff_requested": {"type": "boolean"}
  }
}
````


### contracts/session_snapshot.schema.json

````json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:freya-automotive:session-snapshot:v1",
  "title": "SessionSnapshot",
  "type": "object",
  "additionalProperties": false,
  "required": ["session_id", "state", "turn_id", "generation_id", "last_sequence", "pending_events"],
  "properties": {
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "state": {"enum": ["IDLE", "LISTENING", "THINKING", "SPEAKING", "INTERRUPTING", "HANDOFF", "FAILED", "ENDED"]},
    "turn_id": {"type": "integer", "minimum": 0},
    "generation_id": {"type": "integer", "minimum": 0},
    "last_sequence": {"type": "integer", "minimum": -1},
    "pending_events": {"type": "integer", "minimum": 0}
  }
}
````


### contracts/tts_input.schema.json

````json
{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"urn:freya-automotive:m05-tts-input:v1",
  "title":"M05 private in-process text-only TTS input; NEVER put text in EventEnvelope or telemetry",
  "type":"object", "additionalProperties":false,
  "required":["session_id","turn_id","generation_id","clause_index","clause_count","text","text_sha256","break_kind","pause_after_ms","delivery_hint"],
  "properties":{
    "session_id":{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
    "turn_id":{"type":"integer","minimum":0},
    "generation_id":{"type":"integer","minimum":0},
    "clause_index":{"type":"integer","minimum":0},
    "clause_count":{"type":"integer","minimum":1},
    "text":{"type":"string","minLength":1,"maxLength":5000},
    "text_sha256":{"type":"string","pattern":"^[a-f0-9]{64}$"},
    "break_kind":{"enum":["sentence","pause","limit","final"]},
    "pause_after_ms":{"type":"integer","minimum":0,"maximum":2000},
    "delivery_hint":{"enum":["statement","question","continuation"]}
  }
}
````
