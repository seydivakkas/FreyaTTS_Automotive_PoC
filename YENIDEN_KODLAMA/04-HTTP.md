# HTTP arayüzü

Önce alan ve işlem dizininden seçin. Alttaki OpenAPI belgesinde ilgili işlemin requestBody, parameters, responses ve security alanlarını ve başvurduğu şemayı okuyun. Dinamik kaynak yollarında çalışma zamanı izinleri ayrıca uygulanır.

## Kimlik doğrulama ve erişim modeli (özet)

OpenAPI belgesi her işlemin `security` alanını verir; aşağıdaki tablo kuralı tek yerde toplar. Yeni sürümde kural "her uç nokta kimlik ister, istisnalar listelidir" olmalıdır.

| Erişim | Uç noktalar | Kural |
|---|---|---|
| Kimliksiz | `GET /api/health`, `GET /health` | Yalnız canlılık bilgisi; model, veri veya sürüm sızdırmaz |
| HTTP Basic, kullanıcı `admin` | Diğer bütün `/api/*` uç noktaları; `/api/supervisor/*` router düzeyinde | Parola `ADMIN_PASSWORD`. Boşsa 503 "ADMIN_PASSWORD ayarlanmalı". Karşılaştırma sabit zamanlı (`secrets.compare_digest`). Hatalı girişte 401 ve `WWW-Authenticate: Basic` |
| Basic **veya** imzalı bağlantı | `GET /api/inspections/{id}/pdf?exp=…&sig=…` | HMAC imzası `LINK_SIGNING_KEY` ile, süreli. Anahtar boşsa imzalı erişim kapalıdır |
| Paylaşılan anahtar | `POST /api/webhooks/whatsapp` | `X-Webhook-Token` başlığı, gövde okunmadan denetlenir. Anahtar boşsa 503, yanlışsa 401 |
| IP listesi + paylaşılan anahtar | `POST /api/telephony/inbound-metadata` | İstemci IP'si `PBX_ALLOWED_IPS` içinde ve `X-PBX-Secret` = `PBX_METADATA_SECRET`; aksi halde 403. Gövde form veya JSON |
| Tahmin edilemeyen ad | `GET /api/inspections/photos/{filename}` | **Kimlik istemez.** Dosya adı 16 onaltılık karakter rastgele. Yeni sürümde PDF gibi imzalı bağlantıyla koruyun |
| Tek kullanımlık bilet | `WS /ws/voice?ticket=…` | Bilet `POST /api/session-ticket` (Basic) ile alınır, 30 s geçerli, bir kez kullanılır |

Diğer kurallar:

- **Genel listeleme** `GET /api/{resource}`: yalnız izin listesindeki 21 tablo (`vehicles`, `appointments`, `conversations`, `notifications` …) okunur; bilinmeyen ad 404. `limit` 1–1000 (varsayılan 200), `offset` ≥ 0, sıralama birincil anahtara göre. Bu yol, aynı biçimdeki tek parçalı GET yollarını gölgeler; router'ı en son ekleyin.
- **Yükleme sınırları:** ses en çok 25 MB (base64 alanlarında karşılığı), görsel en çok 10 MB ve `.jpg/.jpeg/.png/.webp`. Sınır, dosya belleğe alınmadan parça parça denetlenir; aşımda 413.
- **Hata biçimi:** FastAPI varsayılanı `{"detail": "…"}`. Mesajlar Türkçedir ve arayüzde doğrudan gösterilir. Doğrulama hataları 422.
- **Önbellek:** kişisel veri dönen operatör uç noktaları `Cache-Control: no-store` gönderir.
- **Durum değiştiren işlemler** (randevu taşıma, KVKK yürütme) `BEGIN IMMEDIATE` ile yeniden denetim yapar ve çakışmada 409 döner.

## İşlem dizini

- GET `/api/health` · Health
- GET `/api/readiness` · Readiness
- POST `/api/models/load` · Load
- GET `/api/system/unified-status` · Get Unified System Status Endpoint
- POST `/api/normalize` · Normal
- POST `/api/frontend/normalize-prosody` · Frontend Normalize Prosody
- POST `/api/frontend/dsp-telephony` · Frontend Dsp Telephony
- GET `/api/frontend/status` · Frontend Status
- POST `/api/frontend/morphological-check` · Frontend Morphological Check
- POST `/api/sft/prepare-corpus` · Sft Prepare Corpus
- POST `/api/sft/configure` · Sft Configure
- POST `/api/sft/train-step` · Sft Train Step
- GET `/api/sft/status` · Sft Status
- GET `/api/sft/verify-identity` · Sft Verify Identity
- POST `/api/sft/lora/configure` · Sft Lora Configure
- GET `/api/sft/lora/status` · Sft Lora Status
- POST `/api/sft/lora/benchmark-step` · Sft Lora Benchmark Step
- POST `/api/synthesize` · Synth
- GET `/api/hotwords` · Get Hotwords
- POST `/api/hotwords` · Update Hotwords
- GET `/api/lexicon` · Get Lexicon
- POST `/api/lexicon` · Update Lexicon
- POST `/api/lexicon/reset` · Reset Lexicon
- DELETE `/api/lexicon/{term}` · Delete Lexicon
- GET `/api/ab/templates` · Get Ab Templates
- GET `/api/ab/experiments` · List Ab Experiments
- POST `/api/ab/experiments` · Create Ab Experiment Endpoint
- GET `/api/ab/experiments/{id}` · Get Ab Experiment Endpoint
- POST `/api/ab/experiments/{id}/status` · Update Ab Experiment Status Endpoint
- GET `/api/ab/experiments/{id}/report` · Get Ab Experiment Report Endpoint
- POST `/api/ab/preview-synth` · Ab Preview Synth
- POST `/api/voice/chat-turn` · Voice Chat Turn Endpoint
- GET `/api/operator/today` · Operator Today
- POST `/api/operator/register-call` · Operator Register Call
- POST `/api/operator/takeover` · Operator Takeover
- POST `/api/operator/whisper` · Operator Whisper
- POST `/api/operator/release` · Operator Release
- GET `/api/operator/live-sessions` · Operator Live Sessions
- POST `/api/qa/evaluate-variants` · Qa Evaluate Variants
- GET `/api/qa/telemetry/{turn_id}` · Qa Get Telemetry
- GET `/api/qa/m11-status` · Qa M11 Status
- GET `/api/notifications` · List Notifications
- POST `/api/notifications/dispatch` · Dispatch Notifications
- POST `/api/notifications/{id}/retry` · Retry Single Notification
- GET `/api/notifications/status` · Notification Provider Status
- POST `/api/notifications/test-send` · Test Send Notification
- POST `/api/notifications/reminders/scan` · Scan Appointment Reminders Endpoint
- GET `/api/notifications/reminders/pending` · List Pending Reminders Endpoint
- POST `/api/telephony/inbound-metadata` · Record Inbound Metadata Endpoint
- POST `/api/outbound/call` · Create Outbound Call
- GET `/api/outbound/calls` · List Outbound Calls
- POST `/api/outbound/calls/{id}/cancel` · Cancel Call
- POST `/api/outbound/calls/{id}/complete` · Complete Call
- GET `/api/outbound/ami-status` · Get Ami Status
- POST `/api/outbound/campaign-dial` · Campaign Dial
- POST `/api/outbound/amd-analyze` · Amd Analyze
- POST `/api/outbound/amd-evaluate-call` · Amd Evaluate Call
- GET `/api/outbound/retry-queue` · Get Retry Queue
- POST `/api/outbound/retry-process` · Trigger Retry Process
- GET `/api/outbound/campaign-stats` · Get Campaign Stats
- GET `/api/audiosocket/stats` · Get Audiosocket Stats Endpoint
- POST `/api/audiosocket/simulate-bargein` · Simulate Barge In Endpoint
- GET `/api/chan-websocket/stats` · Get Chan Websocket Stats Endpoint
- POST `/api/chan-websocket/flush` · Trigger Chan Websocket Flush Endpoint
- GET `/api/transfers` · Get Transfers Endpoint
- GET `/api/transfers/{id}` · Get Transfer Detail Endpoint
- POST `/api/transfers/initiate` · Initiate Transfer Endpoint
- POST `/api/transfers/{id}/accept` · Accept Transfer Endpoint
- POST `/api/transfers/{id}/decline` · Decline Transfer Endpoint
- POST `/api/transfers/{id}/dtmf` · Transfer Dtmf Endpoint
- GET `/api/whatsapp/messages` · Get Whatsapp Messages Endpoint
- POST `/api/whatsapp/inbound` · Whatsapp Inbound Endpoint
- POST `/api/whatsapp/inbound-voice` · Whatsapp Inbound Voice Endpoint
- POST `/api/webhooks/whatsapp` · Whatsapp Webhook Endpoint
- POST `/api/whatsapp/inbound-image` · Whatsapp Inbound Image Endpoint
- POST `/api/analytics/evaluate-call` · Evaluate Call Endpoint
- GET `/api/analytics/calls` · Get Analytics Calls Endpoint
- GET `/api/analytics/call-stats` · Get Analytics Call Stats Endpoint
- GET `/api/vehicles/{id}` · Get Vehicle
- PUT `/api/vehicles/{id}` · Update Vehicle
- DELETE `/api/vehicles/{id}` · Delete Vehicle
- GET `/api/inspections` · List Inspections
- GET `/api/inspections/{id}` · Get Inspection
- GET `/api/analytics/overview` · Analytics Overview
- GET `/api/analytics/follow-ups` · List Follow Ups
- POST `/api/analytics/conversations/{id}/resolve` · Resolve Conv
- POST `/api/analytics/conversations/{id}/reopen` · Reopen Conv
- GET `/api/diagnostics/dtc-registry` · Get Dtc Registry
- GET `/api/diagnostics` · List All Diagnostics
- GET `/api/vehicles/{id}/diagnostics` · List Vehicle Diagnostics
- POST `/api/vehicles/{id}/diagnostics` · Add Vehicle Telemetry
- POST `/api/diagnostics/{id}/call` · Call Diagnostic Owner
- POST `/api/diagnostics/{id}/sms` · Sms Diagnostic Owner
- POST `/api/diagnostics/{id}/resolve` · Resolve Diag
- GET `/api/packages` · List Packages
- POST `/api/ruhsat/decode-image` · Ruhsat Decode Image Endpoint
- POST `/api/ruhsat/decode-text` · Ruhsat Decode Text Endpoint
- POST `/api/ruhsat/decode-phonetic` · Ruhsat Decode Phonetic Endpoint
- POST `/api/ruhsat/apply-to-crm` · Ruhsat Apply Crm Endpoint
- GET `/api/ruhsat/scans` · Get Ruhsat Scans Endpoint
- POST `/api/valuation/calculate` · Valuation Calculate Endpoint
- POST `/api/valuation/save` · Valuation Save Endpoint
- POST `/api/valuation/parse-spoken` · Valuation Parse Spoken Endpoint
- GET `/api/valuation/valuations` · Valuation List Endpoint
- POST `/api/corporate-accounts` · Create Corporate Account
- GET `/api/corporate-accounts/{id}` · Get Corporate Account
- PUT `/api/corporate-accounts/{id}` · Update Corporate Account
- DELETE `/api/corporate-accounts/{id}` · Delete Corporate Account
- GET `/api/corporate-accounts/{id}/ledger` · Get Corporate Ledger
- POST `/api/corporate-accounts/{id}/payments` · Add Corporate Payment
- POST `/api/vehicles` · Vehicle
- GET `/api/vehicles/by-vin/{vin}` · Get Vehicle By Vin
- GET `/api/vehicles/{id}/inspections` · Get Vehicle Inspections
- POST `/api/vehicles/{id}/inspections` · Add Vehicle Inspection
- GET `/api/inspections/{id}/pdf` · Get Inspection Pdf
- GET `/api/inspections/{id}/signed-link` · Get Inspection Signed Link
- POST `/api/inspections/{id}/send-link` · Send Inspection Link
- POST `/api/inspections/photos` · Upload Inspection Photo
- GET `/api/inspections/photos/{filename}` · Get Inspection Photo
- POST `/api/technician/dictate-text` · Technician Dictate Text
- POST `/api/technician/dictate-audio` · Technician Dictate Audio
- POST `/api/quotes` · Quote
- POST `/api/slots` · Slot
- POST `/api/appointments` · Appointment
- POST `/api/appointments/{id}/cancel` · Cancel
- GET `/api/appointments/{id}/reschedule-preview` · Preview Appointment Reschedule
- POST `/api/appointments/{id}/reschedule` · Reschedule Appointment
- GET `/api/appointments/calendar` · Get Calendar Events
- GET `/api/conversations/unclear` · List Unclear Conversations
- GET `/api/conversations/{id}` · Detail
- DELETE `/api/conversations/{id}` · Delete
- GET `/api/conversations/{id}/export` · Export Conversation
- GET `/api/conversations/{id}/audio` · Stream Conversation Audio
- POST `/api/conversations/{id}/feedback-lexicon` · Feedback Lexicon
- GET `/api/reports/weekly/summary` · Get Weekly Summary Endpoint
- GET `/api/reports/weekly/excel` · Get Weekly Excel Endpoint
- GET `/api/lifts` · List Lifts
- POST `/api/lifts` · Create Lift
- GET `/api/lifts/capacity` · Lift Capacity
- POST `/api/lifts/{id}/status` · Update Lift Status
- POST `/api/lifts/{id}/assign` · Assign Vehicle To Lift
- POST `/api/lifts/{id}/release` · Release Vehicle From Lift
- POST `/api/lifts/{id}/call-next` · Call Next For Lift
- GET `/api/queue` · List Queue
- POST `/api/queue` · Add To Queue
- POST `/api/queue/{id}/cancel` · Cancel Queue
- POST `/api/bay-scheduler/check-capacity` · Bay Check Capacity Endpoint
- POST `/api/bay-scheduler/book-stages` · Bay Book Stages Endpoint
- GET `/api/bay-scheduler/bays` · Bay List Endpoint
- GET `/api/bay-scheduler/technicians` · Technician List Endpoint
- GET `/api/bay-scheduler/schedules` · Bay Schedules List Endpoint
- GET `/api/bay-scheduler/analytics` · Bay Analytics Endpoint
- PUT `/api/bay-scheduler/bays/{bay_id}/status` · Bay Set Status Endpoint
- PUT `/api/bay-scheduler/technicians/{technician_id}/status` · Technician Set Status Endpoint
- DELETE `/api/bay-scheduler/appointments/{appointment_id}` · Cancel Appointment Schedules Endpoint
- POST `/api/dtmf/generate-tone` · Get Dtmf Tone Endpoint
- GET `/api/dsp/config` · Get Dsp Config
- POST `/api/dsp/config` · Update Dsp Config
- POST `/api/dsp/denoise-preview` · Denoise Audio Preview
- GET `/api/batched-ode/config` · Get Batched Ode Config Endpoint
- POST `/api/batched-ode/config` · Update Batched Ode Config Endpoint
- GET `/api/batched-ode/metrics` · Get Batched Ode Metrics Endpoint
- POST `/api/batched-ode/benchmark` · Run Batched Ode Benchmark
- POST `/api/turn-detector/evaluate` · Turn Evaluate Endpoint
- POST `/api/turn-detector/analyze-text` · Turn Analyze Text Endpoint
- GET `/api/turn-detector/config` · Turn Config Endpoint
- POST `/api/emotion-prosody/analyze` · Emotion Analyze Endpoint
- POST `/api/emotion-prosody/adapt` · Emotion Adapt Endpoint
- GET `/api/emotion-prosody/config` · Emotion Config Endpoint
- POST `/api/pause-cleaner/clean-audio` · Clean Audio Endpoint
- GET `/api/audio-cache/metrics` · Audio Cache Metrics Endpoint
- GET `/api/audio-cache/phrases` · Audio Cache Phrases Endpoint
- POST `/api/audio-cache/lookup` · Audio Cache Lookup Endpoint
- POST `/api/audio-cache/warmup` · Audio Cache Warmup Endpoint
- POST `/api/kvkk/redact-text` · Kvkk Redact Text Endpoint
- POST `/api/kvkk/validate-tckn` · Kvkk Validate Tckn Endpoint
- POST `/api/kvkk/validate-card` · Kvkk Validate Card Endpoint
- GET `/api/kvkk/policy` · Kvkk Get Policy Endpoint
- POST `/api/kvkk/redact-audio` · Kvkk Redact Audio Endpoint
- POST `/api/archive/call-session` · Archive Call Endpoint
- GET `/api/archive/retention-audit` · Retention Audit Endpoint
- POST `/api/archive/retention-purge` · Retention Purge Endpoint
- GET `/api/archive/{archive_id}/verify` · Verify Archive Endpoint
- GET `/api/archive/{archive_id}/download` · Download Archive Endpoint
- GET `/api/kvkk/transcript-retention-audit` · Kvkk Transcript Retention Audit Endpoint
- POST `/api/kvkk/transcript-retention-purge` · Kvkk Transcript Retention Purge Endpoint
- POST `/api/kvkk/erasure-requests` · Kvkk Create Erasure Request Endpoint
- GET `/api/kvkk/erasure-requests` · Kvkk List Erasure Requests Endpoint
- GET `/api/kvkk/erasure-requests/{request_id}` · Kvkk Get Erasure Request Endpoint
- POST `/api/kvkk/erasure-requests/{request_id}/execute` · Kvkk Execute Erasure Request Endpoint
- GET `/api/kvkk/erasure-requests/{request_id}/certificate` · Kvkk Get Certificate Endpoint
- GET `/api/gpu-health/telemetry` · Gpu Telemetry Endpoint
- GET `/api/gpu-health/circuit-status` · Gpu Circuit Status Endpoint
- POST `/api/gpu-health/configure` · Gpu Configure Endpoint
- POST `/api/gpu-health/simulate-oom` · Gpu Simulate Oom Endpoint
- POST `/api/gpu-health/reset` · Gpu Reset Endpoint
- GET `/api/sip-trunks` · List Sip Trunks Endpoint
- GET `/api/sip-trunks/{trunk_id}/ping` · Ping Sip Trunk Endpoint
- POST `/api/sip-trunks/select` · Select Sip Trunk Endpoint
- POST `/api/sip-trunks/simulate-outage` · Simulate Trunk Outage Endpoint
- POST `/api/sip-trunks/maintenance` · Trunk Maintenance Endpoint
- POST `/api/sip-trunks/configure` · Configure Sip Trunk Endpoint
- GET `/metrics` · Prometheus Metrics Endpoint
- GET `/api/sla/status` · Sla Status Endpoint
- GET `/api/dashboard/live-summary` · Dashboard Live Summary Endpoint
- POST `/api/metrics/record-call` · Record Call Metrics Endpoint
- POST `/api/sla/configure` · Configure Sla Endpoint
- GET `/api/milestones/overview` · Milestone Overview
- POST `/api/milestones/inspect` · Milestone Inspect
- GET `/api/milestones/pronunciation` · Pronunciation Items
- POST `/api/milestones/pronunciation` · Pronunciation Review
- GET `/api/milestones/timeline/{id}` · Milestone Timeline
- GET `/api/supervisor/fqici-queue` · Fqici Queue
- GET `/api/supervisor/conversations/{conversation_id}/detail` · Conversation Detail
- GET `/api/supervisor/quality` · Quality
- POST `/api/supervisor/review/{trace_id}` · Review
- GET `/api/supervisor/dataset` · Export Dataset
- GET `/api/ontology/schema` · Get Ontology Schema
- GET `/api/ontology/packages` · Get Certified Packages
- GET `/api/ontology/diagnostics` · Get Certified Diagnostics
- GET `/api/ontology/vehicles` · Get Certified Vehicles
- POST `/api/ontology/resolve-vehicle` · Resolve Vehicle
- POST `/api/ontology/validate-action` · Validate Action
- GET `/api/ontology/mcp/tools` · Get Mcp Tools
- POST `/api/ontology/mcp/execute` · Execute Mcp Tool
- GET `/api/{resource}` · Listing
- POST `/api/dataset/generate` · Api Generate Dataset
- GET `/api/dataset/export` · Api Export Dataset
- POST `/api/session-ticket` · Ticket

```json
{
 "openapi": "3.1.0",
 "info": {
  "title": "Freya Otomotiv Asistanı",
  "version": "0.1.0"
 },
 "paths": {
  "/api/health": {
   "get": {
    "summary": "Health",
    "operationId": "health_api_health_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    }
   }
  },
  "/api/readiness": {
   "get": {
    "summary": "Readiness",
    "operationId": "readiness_api_readiness_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/models/load": {
   "post": {
    "summary": "Load",
    "operationId": "load_api_models_load_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/system/unified-status": {
   "get": {
    "summary": "Get Unified System Status Endpoint",
    "description": "Tüm protokollerin (TCP 9092, WS 8088, HTTP, GPU/VRAM) birleşik durumunu döndürür.",
    "operationId": "get_unified_system_status_endpoint_api_system_unified_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/normalize": {
   "post": {
    "summary": "Normal",
    "operationId": "normal_api_normalize_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/frontend/normalize-prosody": {
   "post": {
    "summary": "Frontend Normalize Prosody",
    "operationId": "frontend_normalize_prosody_api_frontend_normalize_prosody_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/frontend/dsp-telephony": {
   "post": {
    "summary": "Frontend Dsp Telephony",
    "operationId": "frontend_dsp_telephony_api_frontend_dsp_telephony_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/DSPProcessIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/frontend/status": {
   "get": {
    "summary": "Frontend Status",
    "operationId": "frontend_status_api_frontend_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/frontend/morphological-check": {
   "post": {
    "summary": "Frontend Morphological Check",
    "operationId": "frontend_morphological_check_api_frontend_morphological_check_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/MorphologicalCheckIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/prepare-corpus": {
   "post": {
    "summary": "Sft Prepare Corpus",
    "operationId": "sft_prepare_corpus_api_sft_prepare_corpus_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SFTCorpusIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/configure": {
   "post": {
    "summary": "Sft Configure",
    "operationId": "sft_configure_api_sft_configure_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SFTConfigureIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/train-step": {
   "post": {
    "summary": "Sft Train Step",
    "operationId": "sft_train_step_api_sft_train_step_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SFTTrainIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/status": {
   "get": {
    "summary": "Sft Status",
    "operationId": "sft_status_api_sft_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/verify-identity": {
   "get": {
    "summary": "Sft Verify Identity",
    "operationId": "sft_verify_identity_api_sft_verify_identity_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/lora/configure": {
   "post": {
    "summary": "Sft Lora Configure",
    "operationId": "sft_lora_configure_api_sft_lora_configure_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SFTLoRAConfigureIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/lora/status": {
   "get": {
    "summary": "Sft Lora Status",
    "operationId": "sft_lora_status_api_sft_lora_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sft/lora/benchmark-step": {
   "post": {
    "summary": "Sft Lora Benchmark Step",
    "operationId": "sft_lora_benchmark_step_api_sft_lora_benchmark_step_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SFTLoRABenchmarkIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/synthesize": {
   "post": {
    "summary": "Synth",
    "operationId": "synth_api_synthesize_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/hotwords": {
   "get": {
    "summary": "Get Hotwords",
    "operationId": "get_hotwords_api_hotwords_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Update Hotwords",
    "operationId": "update_hotwords_api_hotwords_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/HotwordsIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/lexicon": {
   "get": {
    "summary": "Get Lexicon",
    "operationId": "get_lexicon_api_lexicon_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Update Lexicon",
    "operationId": "update_lexicon_api_lexicon_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/LexiconTermIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/lexicon/reset": {
   "post": {
    "summary": "Reset Lexicon",
    "operationId": "reset_lexicon_api_lexicon_reset_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/lexicon/{term}": {
   "delete": {
    "summary": "Delete Lexicon",
    "operationId": "delete_lexicon_api_lexicon__term__delete",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "term",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Term"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/ab/templates": {
   "get": {
    "summary": "Get Ab Templates",
    "operationId": "get_ab_templates_api_ab_templates_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ab/experiments": {
   "get": {
    "summary": "List Ab Experiments",
    "operationId": "list_ab_experiments_api_ab_experiments_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Create Ab Experiment Endpoint",
    "operationId": "create_ab_experiment_endpoint_api_ab_experiments_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ABExperimentIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ab/experiments/{id}": {
   "get": {
    "summary": "Get Ab Experiment Endpoint",
    "operationId": "get_ab_experiment_endpoint_api_ab_experiments__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/ab/experiments/{id}/status": {
   "post": {
    "summary": "Update Ab Experiment Status Endpoint",
    "operationId": "update_ab_experiment_status_endpoint_api_ab_experiments__id__status_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ABStatusIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/ab/experiments/{id}/report": {
   "get": {
    "summary": "Get Ab Experiment Report Endpoint",
    "operationId": "get_ab_experiment_report_endpoint_api_ab_experiments__id__report_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/ab/preview-synth": {
   "post": {
    "summary": "Ab Preview Synth",
    "operationId": "ab_preview_synth_api_ab_preview_synth_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ABPreviewSynthIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/voice/chat-turn": {
   "post": {
    "summary": "Voice Chat Turn Endpoint",
    "description": "Canlı konuşma metin girişi: F3 LLM çıkarımı + Slot & Niyet takibi.",
    "operationId": "voice_chat_turn_endpoint_api_voice_chat_turn_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/VoiceChatTurnIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/operator/today": {
   "get": {
    "summary": "Operator Today",
    "operationId": "operator_today_api_operator_today_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "period",
      "in": "query",
      "required": false,
      "schema": {
       "enum": [
        "all",
        "today",
        "carryover"
       ],
       "type": "string",
       "default": "all",
       "title": "Period"
      }
     },
     {
      "name": "category",
      "in": "query",
      "required": false,
      "schema": {
       "enum": [
        "all",
        "transfer",
        "callback",
        "booking",
        "follow_up"
       ],
       "type": "string",
       "default": "all",
       "title": "Category"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 100,
       "minimum": 1,
       "default": 50,
       "title": "Limit"
      }
     },
     {
      "name": "offset",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "minimum": 0,
       "default": 0,
       "title": "Offset"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/operator/register-call": {
   "post": {
    "summary": "Operator Register Call",
    "operationId": "operator_register_call_api_operator_register_call_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OperatorRegisterCallIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/operator/takeover": {
   "post": {
    "summary": "Operator Takeover",
    "operationId": "operator_takeover_api_operator_takeover_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OperatorTakeoverIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/operator/whisper": {
   "post": {
    "summary": "Operator Whisper",
    "operationId": "operator_whisper_api_operator_whisper_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OperatorWhisperIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/operator/release": {
   "post": {
    "summary": "Operator Release",
    "operationId": "operator_release_api_operator_release_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OperatorReleaseIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/operator/live-sessions": {
   "get": {
    "summary": "Operator Live Sessions",
    "operationId": "operator_live_sessions_api_operator_live_sessions_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/qa/evaluate-variants": {
   "post": {
    "summary": "Qa Evaluate Variants",
    "operationId": "qa_evaluate_variants_api_qa_evaluate_variants_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/QAEvaluateVariantsIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/qa/telemetry/{turn_id}": {
   "get": {
    "summary": "Qa Get Telemetry",
    "operationId": "qa_get_telemetry_api_qa_telemetry__turn_id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "turn_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Turn Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/qa/m11-status": {
   "get": {
    "summary": "Qa M11 Status",
    "operationId": "qa_m11_status_api_qa_m11_status_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "has_physical_pbx_trace",
      "in": "query",
      "required": false,
      "schema": {
       "type": "boolean",
       "default": false,
       "title": "Has Physical Pbx Trace"
      }
     },
     {
      "name": "has_hardware_trunk",
      "in": "query",
      "required": false,
      "schema": {
       "type": "boolean",
       "default": false,
       "title": "Has Hardware Trunk"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/notifications": {
   "get": {
    "summary": "List Notifications",
    "operationId": "list_notifications_api_notifications_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Status"
      }
     },
     {
      "name": "appointment_id",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Appointment Id"
      }
     },
     {
      "name": "recipient_type",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Recipient Type"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/notifications/dispatch": {
   "post": {
    "summary": "Dispatch Notifications",
    "operationId": "dispatch_notifications_api_notifications_dispatch_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/notifications/{id}/retry": {
   "post": {
    "summary": "Retry Single Notification",
    "operationId": "retry_single_notification_api_notifications__id__retry_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/notifications/status": {
   "get": {
    "summary": "Notification Provider Status",
    "operationId": "notification_provider_status_api_notifications_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/notifications/test-send": {
   "post": {
    "summary": "Test Send Notification",
    "operationId": "test_send_notification_api_notifications_test_send_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TestNotificationIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/notifications/reminders/scan": {
   "post": {
    "summary": "Scan Appointment Reminders Endpoint",
    "description": "Randevusuna 24 saat kalan müşteriler için hatırlatma SMS/WhatsApp bildirimlerini tarar ve kuyruklar.",
    "operationId": "scan_appointment_reminders_endpoint_api_notifications_reminders_scan_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "hours_ahead_min",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 20,
       "title": "Hours Ahead Min"
      }
     },
     {
      "name": "hours_ahead_max",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 36,
       "title": "Hours Ahead Max"
      }
     },
     {
      "name": "trigger_voice_call",
      "in": "query",
      "required": false,
      "schema": {
       "type": "boolean",
       "default": false,
       "title": "Trigger Voice Call"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/notifications/reminders/pending": {
   "get": {
    "summary": "List Pending Reminders Endpoint",
    "description": "Zaman penceresi içindeki randevuları ve hatırlatma durumlarını listeler.",
    "operationId": "list_pending_reminders_endpoint_api_notifications_reminders_pending_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "hours_ahead_min",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 20,
       "title": "Hours Ahead Min"
      }
     },
     {
      "name": "hours_ahead_max",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 36,
       "title": "Hours Ahead Max"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/telephony/inbound-metadata": {
   "post": {
    "summary": "Record Inbound Metadata Endpoint",
    "description": "Asterisk dialplan (CURL / FastAGI) tarafından gelen çağrı üstverisini kaydeder.",
    "operationId": "record_inbound_metadata_endpoint_api_telephony_inbound_metadata_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    }
   }
  },
  "/api/outbound/call": {
   "post": {
    "summary": "Create Outbound Call",
    "operationId": "create_outbound_call_api_outbound_call_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OutboundCallIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/calls": {
   "get": {
    "summary": "List Outbound Calls",
    "operationId": "list_outbound_calls_api_outbound_calls_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "appointment_id",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Appointment Id"
      }
     },
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Status"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/outbound/calls/{id}/cancel": {
   "post": {
    "summary": "Cancel Call",
    "operationId": "cancel_call_api_outbound_calls__id__cancel_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/outbound/calls/{id}/complete": {
   "post": {
    "summary": "Complete Call",
    "operationId": "complete_call_api_outbound_calls__id__complete_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CallOutcomeIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/outbound/ami-status": {
   "get": {
    "summary": "Get Ami Status",
    "operationId": "get_ami_status_api_outbound_ami_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/campaign-dial": {
   "post": {
    "summary": "Campaign Dial",
    "operationId": "campaign_dial_api_outbound_campaign_dial_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CampaignDialIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/amd-analyze": {
   "post": {
    "summary": "Amd Analyze",
    "operationId": "amd_analyze_api_outbound_amd_analyze_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/AMDAnalyzeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/amd-evaluate-call": {
   "post": {
    "summary": "Amd Evaluate Call",
    "operationId": "amd_evaluate_call_api_outbound_amd_evaluate_call_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/AMDEvaluateCallIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/retry-queue": {
   "get": {
    "summary": "Get Retry Queue",
    "operationId": "get_retry_queue_api_outbound_retry_queue_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/outbound/retry-process": {
   "post": {
    "summary": "Trigger Retry Process",
    "operationId": "trigger_retry_process_api_outbound_retry_process_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 10,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/outbound/campaign-stats": {
   "get": {
    "summary": "Get Campaign Stats",
    "operationId": "get_campaign_stats_api_outbound_campaign_stats_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audiosocket/stats": {
   "get": {
    "summary": "Get Audiosocket Stats Endpoint",
    "description": "Asterisk app_audiosocket TCP 9092 orkestratör metriklerini döndürür.",
    "operationId": "get_audiosocket_stats_endpoint_api_audiosocket_stats_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audiosocket/simulate-bargein": {
   "post": {
    "summary": "Simulate Barge In Endpoint",
    "description": "Çift kademeli barge-in (Stage 1 soft pause, Stage 2 rollback vs commit) simülasyonu.",
    "operationId": "simulate_barge_in_endpoint_api_audiosocket_simulate_bargein_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SimulateBargeInIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/chan-websocket/stats": {
   "get": {
    "summary": "Get Chan Websocket Stats Endpoint",
    "description": "Asterisk chan_websocket WS 8088 adaptör metriklerini döndürür.",
    "operationId": "get_chan_websocket_stats_endpoint_api_chan_websocket_stats_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/chan-websocket/flush": {
   "post": {
    "summary": "Trigger Chan Websocket Flush Endpoint",
    "description": "Tüm aktif chan_websocket oturumlarına anında FLUSH_MEDIA komutu gönderir.",
    "operationId": "trigger_chan_websocket_flush_endpoint_api_chan_websocket_flush_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/transfers": {
   "get": {
    "summary": "Get Transfers Endpoint",
    "operationId": "get_transfers_endpoint_api_transfers_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Status"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/transfers/{id}": {
   "get": {
    "summary": "Get Transfer Detail Endpoint",
    "operationId": "get_transfer_detail_endpoint_api_transfers__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/transfers/initiate": {
   "post": {
    "summary": "Initiate Transfer Endpoint",
    "operationId": "initiate_transfer_endpoint_api_transfers_initiate_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TransferInitiateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/transfers/{id}/accept": {
   "post": {
    "summary": "Accept Transfer Endpoint",
    "operationId": "accept_transfer_endpoint_api_transfers__id__accept_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TransferAcceptIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/transfers/{id}/decline": {
   "post": {
    "summary": "Decline Transfer Endpoint",
    "operationId": "decline_transfer_endpoint_api_transfers__id__decline_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TransferDeclineIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/transfers/{id}/dtmf": {
   "post": {
    "summary": "Transfer Dtmf Endpoint",
    "operationId": "transfer_dtmf_endpoint_api_transfers__id__dtmf_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TransferDTMFIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/whatsapp/messages": {
   "get": {
    "summary": "Get Whatsapp Messages Endpoint",
    "operationId": "get_whatsapp_messages_endpoint_api_whatsapp_messages_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/whatsapp/inbound": {
   "post": {
    "summary": "Whatsapp Inbound Endpoint",
    "operationId": "whatsapp_inbound_endpoint_api_whatsapp_inbound_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/WhatsAppInboundIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/whatsapp/inbound-voice": {
   "post": {
    "summary": "Whatsapp Inbound Voice Endpoint",
    "operationId": "whatsapp_inbound_voice_endpoint_api_whatsapp_inbound_voice_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_whatsapp_inbound_voice_endpoint_api_whatsapp_inbound_voice_post"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/webhooks/whatsapp": {
   "post": {
    "summary": "Whatsapp Webhook Endpoint",
    "description": "Twilio / WhatsApp Cloud API webhook alıcısı.\nForm-urlencoded (Twilio) veya JSON (WhatsApp Cloud) kabul eder.\nPaylaşılan gizli anahtar (X-Webhook-Token) gövde işlenmeden önce doğrulanır.",
    "operationId": "whatsapp_webhook_endpoint_api_webhooks_whatsapp_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    }
   }
  },
  "/api/whatsapp/inbound-image": {
   "post": {
    "summary": "Whatsapp Inbound Image Endpoint",
    "operationId": "whatsapp_inbound_image_endpoint_api_whatsapp_inbound_image_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_whatsapp_inbound_image_endpoint_api_whatsapp_inbound_image_post"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/analytics/evaluate-call": {
   "post": {
    "summary": "Evaluate Call Endpoint",
    "operationId": "evaluate_call_endpoint_api_analytics_evaluate_call_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CallAnalyticsIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/analytics/calls": {
   "get": {
    "summary": "Get Analytics Calls Endpoint",
    "operationId": "get_analytics_calls_endpoint_api_analytics_calls_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     },
     {
      "name": "lead_tier",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Lead Tier"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/analytics/call-stats": {
   "get": {
    "summary": "Get Analytics Call Stats Endpoint",
    "operationId": "get_analytics_call_stats_endpoint_api_analytics_call_stats_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/vehicles/{id}": {
   "get": {
    "summary": "Get Vehicle",
    "operationId": "get_vehicle_api_vehicles__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "put": {
    "summary": "Update Vehicle",
    "operationId": "update_vehicle_api_vehicles__id__put",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/VehicleUpdateIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "delete": {
    "summary": "Delete Vehicle",
    "operationId": "delete_vehicle_api_vehicles__id__delete",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/inspections": {
   "get": {
    "summary": "List Inspections",
    "operationId": "list_inspections_api_inspections_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/inspections/{id}": {
   "get": {
    "summary": "Get Inspection",
    "operationId": "get_inspection_api_inspections__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/analytics/overview": {
   "get": {
    "summary": "Analytics Overview",
    "operationId": "analytics_overview_api_analytics_overview_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/analytics/follow-ups": {
   "get": {
    "summary": "List Follow Ups",
    "operationId": "list_follow_ups_api_analytics_follow_ups_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "type": "string",
       "default": "all",
       "title": "Status"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/analytics/conversations/{id}/resolve": {
   "post": {
    "summary": "Resolve Conv",
    "operationId": "resolve_conv_api_analytics_conversations__id__resolve_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ConversationResolveIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/analytics/conversations/{id}/reopen": {
   "post": {
    "summary": "Reopen Conv",
    "operationId": "reopen_conv_api_analytics_conversations__id__reopen_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/diagnostics/dtc-registry": {
   "get": {
    "summary": "Get Dtc Registry",
    "operationId": "get_dtc_registry_api_diagnostics_dtc_registry_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/diagnostics": {
   "get": {
    "summary": "List All Diagnostics",
    "operationId": "list_all_diagnostics_api_diagnostics_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "is_resolved",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "boolean"
        },
        {
         "type": "null"
        }
       ],
       "title": "Is Resolved"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/vehicles/{id}/diagnostics": {
   "get": {
    "summary": "List Vehicle Diagnostics",
    "operationId": "list_vehicle_diagnostics_api_vehicles__id__diagnostics_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "post": {
    "summary": "Add Vehicle Telemetry",
    "operationId": "add_vehicle_telemetry_api_vehicles__id__diagnostics_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TelemetryIngestIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/diagnostics/{id}/call": {
   "post": {
    "summary": "Call Diagnostic Owner",
    "operationId": "call_diagnostic_owner_api_diagnostics__id__call_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ProactiveActionIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/diagnostics/{id}/sms": {
   "post": {
    "summary": "Sms Diagnostic Owner",
    "operationId": "sms_diagnostic_owner_api_diagnostics__id__sms_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ProactiveActionIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/diagnostics/{id}/resolve": {
   "post": {
    "summary": "Resolve Diag",
    "operationId": "resolve_diag_api_diagnostics__id__resolve_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/packages": {
   "get": {
    "summary": "List Packages",
    "operationId": "list_packages_api_packages_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ruhsat/decode-image": {
   "post": {
    "summary": "Ruhsat Decode Image Endpoint",
    "operationId": "ruhsat_decode_image_endpoint_api_ruhsat_decode_image_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_ruhsat_decode_image_endpoint_api_ruhsat_decode_image_post"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ruhsat/decode-text": {
   "post": {
    "summary": "Ruhsat Decode Text Endpoint",
    "operationId": "ruhsat_decode_text_endpoint_api_ruhsat_decode_text_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/RuhsatTextDecodeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ruhsat/decode-phonetic": {
   "post": {
    "summary": "Ruhsat Decode Phonetic Endpoint",
    "operationId": "ruhsat_decode_phonetic_endpoint_api_ruhsat_decode_phonetic_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/PhoneticDecodeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ruhsat/apply-to-crm": {
   "post": {
    "summary": "Ruhsat Apply Crm Endpoint",
    "operationId": "ruhsat_apply_crm_endpoint_api_ruhsat_apply_to_crm_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/RuhsatApplyIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ruhsat/scans": {
   "get": {
    "summary": "Get Ruhsat Scans Endpoint",
    "operationId": "get_ruhsat_scans_endpoint_api_ruhsat_scans_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/valuation/calculate": {
   "post": {
    "summary": "Valuation Calculate Endpoint",
    "operationId": "valuation_calculate_endpoint_api_valuation_calculate_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/VehicleValuationIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/valuation/save": {
   "post": {
    "summary": "Valuation Save Endpoint",
    "operationId": "valuation_save_endpoint_api_valuation_save_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/VehicleValuationIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/valuation/parse-spoken": {
   "post": {
    "summary": "Valuation Parse Spoken Endpoint",
    "operationId": "valuation_parse_spoken_endpoint_api_valuation_parse_spoken_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SpokenValuationIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/valuation/valuations": {
   "get": {
    "summary": "Valuation List Endpoint",
    "operationId": "valuation_list_endpoint_api_valuation_valuations_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/corporate-accounts": {
   "post": {
    "summary": "Create Corporate Account",
    "operationId": "create_corporate_account_api_corporate_accounts_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CorporateAccountIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/corporate-accounts/{id}": {
   "get": {
    "summary": "Get Corporate Account",
    "operationId": "get_corporate_account_api_corporate_accounts__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "put": {
    "summary": "Update Corporate Account",
    "operationId": "update_corporate_account_api_corporate_accounts__id__put",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CorporateAccountUpdateIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "delete": {
    "summary": "Delete Corporate Account",
    "operationId": "delete_corporate_account_api_corporate_accounts__id__delete",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/corporate-accounts/{id}/ledger": {
   "get": {
    "summary": "Get Corporate Ledger",
    "operationId": "get_corporate_ledger_api_corporate_accounts__id__ledger_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/corporate-accounts/{id}/payments": {
   "post": {
    "summary": "Add Corporate Payment",
    "operationId": "add_corporate_payment_api_corporate_accounts__id__payments_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/PaymentIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/vehicles": {
   "post": {
    "summary": "Vehicle",
    "operationId": "vehicle_api_vehicles_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/VehicleIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/vehicles/by-vin/{vin}": {
   "get": {
    "summary": "Get Vehicle By Vin",
    "operationId": "get_vehicle_by_vin_api_vehicles_by_vin__vin__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "vin",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Vin"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/vehicles/{id}/inspections": {
   "get": {
    "summary": "Get Vehicle Inspections",
    "operationId": "get_vehicle_inspections_api_vehicles__id__inspections_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "post": {
    "summary": "Add Vehicle Inspection",
    "operationId": "add_vehicle_inspection_api_vehicles__id__inspections_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/InspectionReportIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/inspections/{id}/pdf": {
   "get": {
    "summary": "Get Inspection Pdf",
    "operationId": "get_inspection_pdf_api_inspections__id__pdf_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     },
     {
      "name": "exp",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Exp"
      }
     },
     {
      "name": "sig",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Sig"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/inspections/{id}/signed-link": {
   "get": {
    "summary": "Get Inspection Signed Link",
    "operationId": "get_inspection_signed_link_api_inspections__id__signed_link_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/inspections/{id}/send-link": {
   "post": {
    "summary": "Send Inspection Link",
    "operationId": "send_inspection_link_api_inspections__id__send_link_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/inspections/photos": {
   "post": {
    "summary": "Upload Inspection Photo",
    "operationId": "upload_inspection_photo_api_inspections_photos_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_upload_inspection_photo_api_inspections_photos_post"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/inspections/photos/{filename}": {
   "get": {
    "summary": "Get Inspection Photo",
    "operationId": "get_inspection_photo_api_inspections_photos__filename__get",
    "parameters": [
     {
      "name": "filename",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Filename"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/technician/dictate-text": {
   "post": {
    "summary": "Technician Dictate Text",
    "operationId": "technician_dictate_text_api_technician_dictate_text_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/DictationTextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/technician/dictate-audio": {
   "post": {
    "summary": "Technician Dictate Audio",
    "operationId": "technician_dictate_audio_api_technician_dictate_audio_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_technician_dictate_audio_api_technician_dictate_audio_post"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/quotes": {
   "post": {
    "summary": "Quote",
    "operationId": "quote_api_quotes_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/QuoteIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/slots": {
   "post": {
    "summary": "Slot",
    "operationId": "slot_api_slots_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SlotIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/appointments": {
   "post": {
    "summary": "Appointment",
    "operationId": "appointment_api_appointments_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BookingIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/appointments/{id}/cancel": {
   "post": {
    "summary": "Cancel",
    "operationId": "cancel_api_appointments__id__cancel_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/appointments/{id}/reschedule-preview": {
   "get": {
    "summary": "Preview Appointment Reschedule",
    "operationId": "preview_appointment_reschedule_api_appointments__id__reschedule_preview_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     },
     {
      "name": "target_slot_id",
      "in": "query",
      "required": true,
      "schema": {
       "type": "string",
       "minLength": 1,
       "maxLength": 100,
       "title": "Target Slot Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/appointments/{id}/reschedule": {
   "post": {
    "summary": "Reschedule Appointment",
    "operationId": "reschedule_appointment_api_appointments__id__reschedule_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/RescheduleIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/appointments/calendar": {
   "get": {
    "summary": "Get Calendar Events",
    "operationId": "get_calendar_events_api_appointments_calendar_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/conversations/unclear": {
   "get": {
    "summary": "List Unclear Conversations",
    "operationId": "list_unclear_conversations_api_conversations_unclear_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/conversations/{id}": {
   "get": {
    "summary": "Detail",
    "operationId": "detail_api_conversations__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "delete": {
    "summary": "Delete",
    "operationId": "delete_api_conversations__id__delete",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/conversations/{id}/export": {
   "get": {
    "summary": "Export Conversation",
    "operationId": "export_conversation_api_conversations__id__export_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     },
     {
      "name": "format",
      "in": "query",
      "required": false,
      "schema": {
       "type": "string",
       "default": "json",
       "title": "Format"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/conversations/{id}/audio": {
   "get": {
    "summary": "Stream Conversation Audio",
    "operationId": "stream_conversation_audio_api_conversations__id__audio_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/conversations/{id}/feedback-lexicon": {
   "post": {
    "summary": "Feedback Lexicon",
    "operationId": "feedback_lexicon_api_conversations__id__feedback_lexicon_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/FeedbackLexiconIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/reports/weekly/summary": {
   "get": {
    "summary": "Get Weekly Summary Endpoint",
    "operationId": "get_weekly_summary_endpoint_api_reports_weekly_summary_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "days",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 7,
       "title": "Days"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/reports/weekly/excel": {
   "get": {
    "summary": "Get Weekly Excel Endpoint",
    "operationId": "get_weekly_excel_endpoint_api_reports_weekly_excel_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "days",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 7,
       "title": "Days"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/lifts": {
   "get": {
    "summary": "List Lifts",
    "operationId": "list_lifts_api_lifts_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Create Lift",
    "operationId": "create_lift_api_lifts_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/LiftIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/lifts/capacity": {
   "get": {
    "summary": "Lift Capacity",
    "operationId": "lift_capacity_api_lifts_capacity_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/lifts/{id}/status": {
   "post": {
    "summary": "Update Lift Status",
    "operationId": "update_lift_status_api_lifts__id__status_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/LiftStatusIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/lifts/{id}/assign": {
   "post": {
    "summary": "Assign Vehicle To Lift",
    "operationId": "assign_vehicle_to_lift_api_lifts__id__assign_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/LiftAssignIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/lifts/{id}/release": {
   "post": {
    "summary": "Release Vehicle From Lift",
    "operationId": "release_vehicle_from_lift_api_lifts__id__release_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/lifts/{id}/call-next": {
   "post": {
    "summary": "Call Next For Lift",
    "operationId": "call_next_for_lift_api_lifts__id__call_next_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/queue": {
   "get": {
    "summary": "List Queue",
    "operationId": "list_queue_api_queue_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Status"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "post": {
    "summary": "Add To Queue",
    "operationId": "add_to_queue_api_queue_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/QueueEntryIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/queue/{id}/cancel": {
   "post": {
    "summary": "Cancel Queue",
    "operationId": "cancel_queue_api_queue__id__cancel_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/bay-scheduler/check-capacity": {
   "post": {
    "summary": "Bay Check Capacity Endpoint",
    "operationId": "bay_check_capacity_endpoint_api_bay_scheduler_check_capacity_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BayCapacityCheckIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/bay-scheduler/book-stages": {
   "post": {
    "summary": "Bay Book Stages Endpoint",
    "operationId": "bay_book_stages_endpoint_api_bay_scheduler_book_stages_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BayBookingIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/bay-scheduler/bays": {
   "get": {
    "summary": "Bay List Endpoint",
    "operationId": "bay_list_endpoint_api_bay_scheduler_bays_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/bay-scheduler/technicians": {
   "get": {
    "summary": "Technician List Endpoint",
    "operationId": "technician_list_endpoint_api_bay_scheduler_technicians_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/bay-scheduler/schedules": {
   "get": {
    "summary": "Bay Schedules List Endpoint",
    "operationId": "bay_schedules_list_endpoint_api_bay_scheduler_schedules_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "date",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Date"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 100,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/bay-scheduler/analytics": {
   "get": {
    "summary": "Bay Analytics Endpoint",
    "operationId": "bay_analytics_endpoint_api_bay_scheduler_analytics_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "date",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Date"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/bay-scheduler/bays/{bay_id}/status": {
   "put": {
    "summary": "Bay Set Status Endpoint",
    "operationId": "bay_set_status_endpoint_api_bay_scheduler_bays__bay_id__status_put",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "bay_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Bay Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BayStatusIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/bay-scheduler/technicians/{technician_id}/status": {
   "put": {
    "summary": "Technician Set Status Endpoint",
    "operationId": "technician_set_status_endpoint_api_bay_scheduler_technicians__technician_id__status_put",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "technician_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Technician Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TechnicianStatusIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/bay-scheduler/appointments/{appointment_id}": {
   "delete": {
    "summary": "Cancel Appointment Schedules Endpoint",
    "operationId": "cancel_appointment_schedules_endpoint_api_bay_scheduler_appointments__appointment_id__delete",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "appointment_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Appointment Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/dtmf/generate-tone": {
   "post": {
    "summary": "Get Dtmf Tone Endpoint",
    "operationId": "get_dtmf_tone_endpoint_api_dtmf_generate_tone_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/DTMFIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/dsp/config": {
   "get": {
    "summary": "Get Dsp Config",
    "operationId": "get_dsp_config_api_dsp_config_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Update Dsp Config",
    "operationId": "update_dsp_config_api_dsp_config_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/DSPConfigIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/dsp/denoise-preview": {
   "post": {
    "summary": "Denoise Audio Preview",
    "operationId": "denoise_audio_preview_api_dsp_denoise_preview_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_denoise_audio_preview_api_dsp_denoise_preview_post"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/batched-ode/config": {
   "get": {
    "summary": "Get Batched Ode Config Endpoint",
    "operationId": "get_batched_ode_config_endpoint_api_batched_ode_config_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Update Batched Ode Config Endpoint",
    "operationId": "update_batched_ode_config_endpoint_api_batched_ode_config_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BatchedODEConfigIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/batched-ode/metrics": {
   "get": {
    "summary": "Get Batched Ode Metrics Endpoint",
    "operationId": "get_batched_ode_metrics_endpoint_api_batched_ode_metrics_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/batched-ode/benchmark": {
   "post": {
    "summary": "Run Batched Ode Benchmark",
    "operationId": "run_batched_ode_benchmark_api_batched_ode_benchmark_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/BatchedBenchmarkIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/turn-detector/evaluate": {
   "post": {
    "summary": "Turn Evaluate Endpoint",
    "operationId": "turn_evaluate_endpoint_api_turn_detector_evaluate_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TurnEvaluateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/turn-detector/analyze-text": {
   "post": {
    "summary": "Turn Analyze Text Endpoint",
    "operationId": "turn_analyze_text_endpoint_api_turn_detector_analyze_text_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TurnAnalyzeTextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/turn-detector/config": {
   "get": {
    "summary": "Turn Config Endpoint",
    "operationId": "turn_config_endpoint_api_turn_detector_config_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/emotion-prosody/analyze": {
   "post": {
    "summary": "Emotion Analyze Endpoint",
    "operationId": "emotion_analyze_endpoint_api_emotion_prosody_analyze_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/EmotionAnalyzeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/emotion-prosody/adapt": {
   "post": {
    "summary": "Emotion Adapt Endpoint",
    "operationId": "emotion_adapt_endpoint_api_emotion_prosody_adapt_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/EmotionAdaptIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/emotion-prosody/config": {
   "get": {
    "summary": "Emotion Config Endpoint",
    "operationId": "emotion_config_endpoint_api_emotion_prosody_config_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/pause-cleaner/clean-audio": {
   "post": {
    "summary": "Clean Audio Endpoint",
    "operationId": "clean_audio_endpoint_api_pause_cleaner_clean_audio_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/PauseCleanIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audio-cache/metrics": {
   "get": {
    "summary": "Audio Cache Metrics Endpoint",
    "operationId": "audio_cache_metrics_endpoint_api_audio_cache_metrics_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audio-cache/phrases": {
   "get": {
    "summary": "Audio Cache Phrases Endpoint",
    "operationId": "audio_cache_phrases_endpoint_api_audio_cache_phrases_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audio-cache/lookup": {
   "post": {
    "summary": "Audio Cache Lookup Endpoint",
    "operationId": "audio_cache_lookup_endpoint_api_audio_cache_lookup_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/AudioCacheLookupIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/audio-cache/warmup": {
   "post": {
    "summary": "Audio Cache Warmup Endpoint",
    "operationId": "audio_cache_warmup_endpoint_api_audio_cache_warmup_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/redact-text": {
   "post": {
    "summary": "Kvkk Redact Text Endpoint",
    "operationId": "kvkk_redact_text_endpoint_api_kvkk_redact_text_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/KVKKRedactIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/validate-tckn": {
   "post": {
    "summary": "Kvkk Validate Tckn Endpoint",
    "operationId": "kvkk_validate_tckn_endpoint_api_kvkk_validate_tckn_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TCKNValidateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/validate-card": {
   "post": {
    "summary": "Kvkk Validate Card Endpoint",
    "operationId": "kvkk_validate_card_endpoint_api_kvkk_validate_card_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/CardValidateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/policy": {
   "get": {
    "summary": "Kvkk Get Policy Endpoint",
    "operationId": "kvkk_get_policy_endpoint_api_kvkk_policy_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/redact-audio": {
   "post": {
    "summary": "Kvkk Redact Audio Endpoint",
    "operationId": "kvkk_redact_audio_endpoint_api_kvkk_redact_audio_post",
    "requestBody": {
     "content": {
      "multipart/form-data": {
       "schema": {
        "$ref": "#/components/schemas/Body_kvkk_redact_audio_endpoint_api_kvkk_redact_audio_post"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/archive/call-session": {
   "post": {
    "summary": "Archive Call Endpoint",
    "operationId": "archive_call_endpoint_api_archive_call_session_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ArchiveCallIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/archive/retention-audit": {
   "get": {
    "summary": "Retention Audit Endpoint",
    "operationId": "retention_audit_endpoint_api_archive_retention_audit_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/archive/retention-purge": {
   "post": {
    "summary": "Retention Purge Endpoint",
    "operationId": "retention_purge_endpoint_api_archive_retention_purge_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ArchivePurgeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/archive/{archive_id}/verify": {
   "get": {
    "summary": "Verify Archive Endpoint",
    "operationId": "verify_archive_endpoint_api_archive__archive_id__verify_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "archive_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Archive Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/archive/{archive_id}/download": {
   "get": {
    "summary": "Download Archive Endpoint",
    "operationId": "download_archive_endpoint_api_archive__archive_id__download_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "archive_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Archive Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/kvkk/transcript-retention-audit": {
   "get": {
    "summary": "Kvkk Transcript Retention Audit Endpoint",
    "description": "Transkript saklama süresi durumunu denetler ve özetler.",
    "operationId": "kvkk_transcript_retention_audit_endpoint_api_kvkk_transcript_retention_audit_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "retention_days",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "integer"
        },
        {
         "type": "null"
        }
       ],
       "title": "Retention Days"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/kvkk/transcript-retention-purge": {
   "post": {
    "summary": "Kvkk Transcript Retention Purge Endpoint",
    "description": "Süresi dolmuş konuşma transkriptlerini anonimleştirir/imha eder.",
    "operationId": "kvkk_transcript_retention_purge_endpoint_api_kvkk_transcript_retention_purge_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TranscriptRetentionPurgeIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/kvkk/erasure-requests": {
   "post": {
    "summary": "Kvkk Create Erasure Request Endpoint",
    "description": "KVKK Madde 11 uyarınca yeni bir veri silme (unutulma) talebi kaydeder.",
    "operationId": "kvkk_create_erasure_request_endpoint_api_kvkk_erasure_requests_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/KVKKErasureRequestIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   },
   "get": {
    "summary": "Kvkk List Erasure Requests Endpoint",
    "description": "Kayıtlı KVKK veri silme taleplerini listeler.",
    "operationId": "kvkk_list_erasure_requests_endpoint_api_kvkk_erasure_requests_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "status",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "title": "Status"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 200,
       "minimum": 1,
       "default": 50,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/kvkk/erasure-requests/{request_id}": {
   "get": {
    "summary": "Kvkk Get Erasure Request Endpoint",
    "description": "Tek bir silme talebinin detayını ve etki özetini döner.",
    "operationId": "kvkk_get_erasure_request_endpoint_api_kvkk_erasure_requests__request_id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "request_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Request Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/kvkk/erasure-requests/{request_id}/execute": {
   "post": {
    "summary": "Kvkk Execute Erasure Request Endpoint",
    "description": "KVKK veri silme talebini icra eder: kayıtları anonimleştirir/siler ve SHA-256 özeti üretir.",
    "operationId": "kvkk_execute_erasure_request_endpoint_api_kvkk_erasure_requests__request_id__execute_post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "request_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Request Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/KVKKErasureExecuteIn"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/kvkk/erasure-requests/{request_id}/certificate": {
   "get": {
    "summary": "Kvkk Get Certificate Endpoint",
    "description": "İcra edilmiş bir silme talebinin uygulama işlem kaydını döner.",
    "operationId": "kvkk_get_certificate_endpoint_api_kvkk_erasure_requests__request_id__certificate_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "request_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Request Id"
      }
     },
     {
      "name": "format",
      "in": "query",
      "required": false,
      "schema": {
       "type": "string",
       "default": "json",
       "title": "Format"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/gpu-health/telemetry": {
   "get": {
    "summary": "Gpu Telemetry Endpoint",
    "operationId": "gpu_telemetry_endpoint_api_gpu_health_telemetry_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/gpu-health/circuit-status": {
   "get": {
    "summary": "Gpu Circuit Status Endpoint",
    "operationId": "gpu_circuit_status_endpoint_api_gpu_health_circuit_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/gpu-health/configure": {
   "post": {
    "summary": "Gpu Configure Endpoint",
    "operationId": "gpu_configure_endpoint_api_gpu_health_configure_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/GPUConfigureIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/gpu-health/simulate-oom": {
   "post": {
    "summary": "Gpu Simulate Oom Endpoint",
    "operationId": "gpu_simulate_oom_endpoint_api_gpu_health_simulate_oom_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/GPUSimulateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/gpu-health/reset": {
   "post": {
    "summary": "Gpu Reset Endpoint",
    "operationId": "gpu_reset_endpoint_api_gpu_health_reset_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sip-trunks": {
   "get": {
    "summary": "List Sip Trunks Endpoint",
    "operationId": "list_sip_trunks_endpoint_api_sip_trunks_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sip-trunks/{trunk_id}/ping": {
   "get": {
    "summary": "Ping Sip Trunk Endpoint",
    "operationId": "ping_sip_trunk_endpoint_api_sip_trunks__trunk_id__ping_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "trunk_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Trunk Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/sip-trunks/select": {
   "post": {
    "summary": "Select Sip Trunk Endpoint",
    "operationId": "select_sip_trunk_endpoint_api_sip_trunks_select_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TrunkSelectIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sip-trunks/simulate-outage": {
   "post": {
    "summary": "Simulate Trunk Outage Endpoint",
    "operationId": "simulate_trunk_outage_endpoint_api_sip_trunks_simulate_outage_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TrunkSimulateIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sip-trunks/maintenance": {
   "post": {
    "summary": "Trunk Maintenance Endpoint",
    "operationId": "trunk_maintenance_endpoint_api_sip_trunks_maintenance_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TrunkMaintenanceIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sip-trunks/configure": {
   "post": {
    "summary": "Configure Sip Trunk Endpoint",
    "operationId": "configure_sip_trunk_endpoint_api_sip_trunks_configure_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TrunkConfigIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/metrics": {
   "get": {
    "summary": "Prometheus Metrics Endpoint",
    "description": "Prometheus text exposition formatı (version 0.0.4) ile anlık sistem telemetrisi.",
    "operationId": "prometheus_metrics_endpoint_metrics_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sla/status": {
   "get": {
    "summary": "Sla Status Endpoint",
    "description": "Canlı kurumsal SLA uyumluluk durumu, ihlal kontrolleri ve skoru.",
    "operationId": "sla_status_endpoint_api_sla_status_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/dashboard/live-summary": {
   "get": {
    "summary": "Dashboard Live Summary Endpoint",
    "description": "Grafana ve web arayüzleri için konsolide anlık sistem özeti.",
    "operationId": "dashboard_live_summary_endpoint_api_dashboard_live_summary_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/metrics/record-call": {
   "post": {
    "summary": "Record Call Metrics Endpoint",
    "description": "Çağrı tamamlandığında telemetri ve kalite metriklerini kaydeder.",
    "operationId": "record_call_metrics_endpoint_api_metrics_record_call_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SLARecordCallIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/sla/configure": {
   "post": {
    "summary": "Configure Sla Endpoint",
    "description": "SLA kurallarını ve eşik değerlerini dinamik günceller.",
    "operationId": "configure_sla_endpoint_api_sla_configure_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/SLAConfigureIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/milestones/overview": {
   "get": {
    "summary": "Milestone Overview",
    "operationId": "milestone_overview_api_milestones_overview_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/milestones/inspect": {
   "post": {
    "summary": "Milestone Inspect",
    "operationId": "milestone_inspect_api_milestones_inspect_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/TextIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/milestones/pronunciation": {
   "get": {
    "summary": "Pronunciation Items",
    "operationId": "pronunciation_items_api_milestones_pronunciation_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   },
   "post": {
    "summary": "Pronunciation Review",
    "operationId": "pronunciation_review_api_milestones_pronunciation_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/ReviewIn"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/milestones/timeline/{id}": {
   "get": {
    "summary": "Milestone Timeline",
    "operationId": "milestone_timeline_api_milestones_timeline__id__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/supervisor/fqici-queue": {
   "get": {
    "summary": "Fqici Queue",
    "operationId": "fqici_queue_api_supervisor_fqici_queue_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 100,
       "minimum": 1,
       "default": 25,
       "title": "Limit"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/supervisor/conversations/{conversation_id}/detail": {
   "get": {
    "summary": "Conversation Detail",
    "operationId": "conversation_detail_api_supervisor_conversations__conversation_id__detail_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "conversation_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Conversation Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/supervisor/quality": {
   "get": {
    "summary": "Quality",
    "operationId": "quality_api_supervisor_quality_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "queue",
      "in": "query",
      "required": false,
      "schema": {
       "enum": [
        "all",
        "pending"
       ],
       "type": "string",
       "default": "all",
       "title": "Queue"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 200,
       "minimum": 1,
       "default": 50,
       "title": "Limit"
      }
     },
     {
      "name": "conversation_id",
      "in": "query",
      "required": false,
      "schema": {
       "anyOf": [
        {
         "type": "string",
         "format": "uuid"
        },
        {
         "type": "null"
        }
       ],
       "title": "Conversation Id"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/supervisor/review/{trace_id}": {
   "post": {
    "summary": "Review",
    "operationId": "review_api_supervisor_review__trace_id__post",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "trace_id",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "format": "uuid",
       "title": "Trace Id"
      }
     }
    ],
    "requestBody": {
     "required": true,
     "content": {
      "application/json": {
       "schema": {
        "type": "object",
        "additionalProperties": true,
        "title": "Data"
       }
      }
     }
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/supervisor/dataset": {
   "get": {
    "summary": "Export Dataset",
    "operationId": "export_dataset_api_supervisor_dataset_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/schema": {
   "get": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Get Ontology Schema",
    "description": "Veritabanı şemasını ve semantik iş kavramlarını graf yapısında döner (Discover adımı).",
    "operationId": "get_ontology_schema_api_ontology_schema_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/OntologySchemaGraph"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/packages": {
   "get": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Get Certified Packages",
    "description": "Sertifikalı ekspertiz paketleri ve fiyatlandırma sözleşmesini döner (Single Source of Truth).",
    "operationId": "get_certified_packages_api_ontology_packages_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "items": {
          "$ref": "#/components/schemas/ServicePackageConcept"
         },
         "type": "array",
         "title": "Response Get Certified Packages Api Ontology Packages Get"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/diagnostics": {
   "get": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Get Certified Diagnostics",
    "description": "Sertifikalı OBD-II arıza kodları ve ikaz lambası ontolojisini döner.",
    "operationId": "get_certified_diagnostics_api_ontology_diagnostics_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "query",
      "in": "query",
      "required": false,
      "schema": {
       "type": "string",
       "description": "Arıza kodu veya semptom filtresi",
       "default": "",
       "title": "Query"
      },
      "description": "Arıza kodu veya semptom filtresi"
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "type": "array",
         "items": {
          "$ref": "#/components/schemas/DiagnosticFaultConcept"
         },
         "title": "Response Get Certified Diagnostics Api Ontology Diagnostics Get"
        }
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/ontology/vehicles": {
   "get": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Get Certified Vehicles",
    "description": "Katalogdaki standart referans araç modellerini döner.",
    "operationId": "get_certified_vehicles_api_ontology_vehicles_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "items": {
          "$ref": "#/components/schemas/VehicleConcept"
         },
         "type": "array",
         "title": "Response Get Certified Vehicles Api Ontology Vehicles Get"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/resolve-vehicle": {
   "post": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Resolve Vehicle",
    "description": "Doğal dille söylenmiş araç metnini sertifikalı araç ontolojisine eşler.",
    "operationId": "resolve_vehicle_api_ontology_resolve_vehicle_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "additionalProperties": {
         "type": "string"
        },
        "type": "object",
        "title": "Body"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "additionalProperties": true,
         "type": "object",
         "title": "Response Resolve Vehicle Api Ontology Resolve Vehicle Post"
        }
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/validate-action": {
   "post": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Validate Action",
    "description": "Agent veya Supervisor tarafından planlanan veritabanı eylemini ontoloji kurallarıyla doğrular (Guardrail).",
    "operationId": "validate_action_api_ontology_validate_action_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/OntologyValidationRequest"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/OntologyValidationResult"
        }
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/mcp/tools": {
   "get": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Get Mcp Tools",
    "description": "NVIDIA Auto-Ontology standardına uygun MCP araç şemalarını listeler.",
    "operationId": "get_mcp_tools_api_ontology_mcp_tools_get",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "additionalProperties": true,
         "type": "object",
         "title": "Response Get Mcp Tools Api Ontology Mcp Tools Get"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/ontology/mcp/execute": {
   "post": {
    "tags": [
     "Automotive Ontology"
    ],
    "summary": "Execute Mcp Tool",
    "description": "MCP üzerinden gelen araç çağrısını güvenli bir şekilde yürütür.",
    "operationId": "execute_mcp_tool_api_ontology_mcp_execute_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "additionalProperties": true,
        "type": "object",
        "title": "Body"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {
         "additionalProperties": true,
         "type": "object",
         "title": "Response Execute Mcp Tool Api Ontology Mcp Execute Post"
        }
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/{resource}": {
   "get": {
    "summary": "Listing",
    "operationId": "listing_api__resource__get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "resource",
      "in": "path",
      "required": true,
      "schema": {
       "type": "string",
       "title": "Resource"
      }
     },
     {
      "name": "limit",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 1000,
       "minimum": 1,
       "default": 200,
       "title": "Limit"
      }
     },
     {
      "name": "offset",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "minimum": 0,
       "default": 0,
       "title": "Offset"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/dataset/generate": {
   "post": {
    "tags": [
     "dataset"
    ],
    "summary": "Api Generate Dataset",
    "description": "Yeni bir fine-tuning veri seti oluşturur ve yerel diske kaydeder.",
    "operationId": "api_generate_dataset_api_dataset_generate_post",
    "requestBody": {
     "content": {
      "application/json": {
       "schema": {
        "$ref": "#/components/schemas/DatasetGenerateRequest"
       }
      }
     },
     "required": true
    },
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  },
  "/api/dataset/export": {
   "get": {
    "tags": [
     "dataset"
    ],
    "summary": "Api Export Dataset",
    "description": "Veri setini istemciye anında JSONL (application/x-jsonlines) olarak akıtır.",
    "operationId": "api_export_dataset_api_dataset_export_get",
    "security": [
     {
      "HTTPBasic": []
     }
    ],
    "parameters": [
     {
      "name": "format",
      "in": "query",
      "required": false,
      "schema": {
       "type": "string",
       "pattern": "^(alpaca|sharegpt)$",
       "default": "alpaca",
       "title": "Format"
      }
     },
     {
      "name": "count",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "maximum": 10000,
       "minimum": 1,
       "default": 50,
       "title": "Count"
      }
     },
     {
      "name": "seed",
      "in": "query",
      "required": false,
      "schema": {
       "type": "integer",
       "default": 42,
       "title": "Seed"
      }
     }
    ],
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     },
     "422": {
      "description": "Validation Error",
      "content": {
       "application/json": {
        "schema": {
         "$ref": "#/components/schemas/HTTPValidationError"
        }
       }
      }
     }
    }
   }
  },
  "/api/session-ticket": {
   "post": {
    "summary": "Ticket",
    "operationId": "ticket_api_session_ticket_post",
    "responses": {
     "200": {
      "description": "Successful Response",
      "content": {
       "application/json": {
        "schema": {}
       }
      }
     }
    },
    "security": [
     {
      "HTTPBasic": []
     }
    ]
   }
  }
 },
 "components": {
  "schemas": {
   "ABExperimentIn": {
    "properties": {
     "name": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Name"
     },
     "description": {
      "type": "string",
      "maxLength": 1000,
      "title": "Description",
      "default": ""
     },
     "experiment_type": {
      "type": "string",
      "pattern": "^(prompt|tts_seed|greeting|composite)$",
      "title": "Experiment Type",
      "default": "composite"
     },
     "variants": {
      "items": {
       "additionalProperties": true,
       "type": "object"
      },
      "type": "array",
      "minItems": 2,
      "title": "Variants"
     },
     "target_metric": {
      "type": "string",
      "maxLength": 40,
      "title": "Target Metric",
      "default": "conversion_rate"
     }
    },
    "type": "object",
    "required": [
     "name",
     "variants"
    ],
    "title": "ABExperimentIn"
   },
   "ABPreviewSynthIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 1000,
      "minLength": 1,
      "title": "Text"
     },
     "seed": {
      "type": "integer",
      "title": "Seed",
      "default": 9
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "ABPreviewSynthIn"
   },
   "ABStatusIn": {
    "properties": {
     "status": {
      "type": "string",
      "pattern": "^(active|paused|completed)$",
      "title": "Status"
     }
    },
    "type": "object",
    "required": [
     "status"
    ],
    "title": "ABStatusIn"
   },
   "AMDAnalyzeIn": {
    "properties": {
     "audio_base64": {
      "type": "string",
      "maxLength": 34952536,
      "minLength": 1,
      "title": "Audio Base64"
     },
     "sample_rate": {
      "type": "integer",
      "maximum": 48000.0,
      "minimum": 8000.0,
      "title": "Sample Rate",
      "default": 8000
     }
    },
    "type": "object",
    "required": [
     "audio_base64"
    ],
    "title": "AMDAnalyzeIn"
   },
   "AMDEvaluateCallIn": {
    "properties": {
     "call_id": {
      "type": "string",
      "title": "Call Id"
     },
     "classification": {
      "type": "string",
      "enum": [
       "HUMAN",
       "MACHINE",
       "UNKNOWN"
      ],
      "title": "Classification"
     },
     "reason": {
      "type": "string",
      "maxLength": 200,
      "title": "Reason",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "call_id",
     "classification"
    ],
    "title": "AMDEvaluateCallIn"
   },
   "ArchiveCallIn": {
    "properties": {
     "audio_base64": {
      "type": "string",
      "maxLength": 34952536,
      "minLength": 4,
      "title": "Audio Base64"
     },
     "sample_rate": {
      "type": "integer",
      "maximum": 48000.0,
      "minimum": 8000.0,
      "title": "Sample Rate",
      "default": 8000
     },
     "conversation_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Conversation Id"
     },
     "call_session_id": {
      "type": "string",
      "title": "Call Session Id",
      "default": ""
     },
     "caller_phone": {
      "type": "string",
      "title": "Caller Phone",
      "default": ""
     },
     "codec": {
      "type": "string",
      "pattern": "^(opus|gsm_fr|raw_wav)$",
      "title": "Codec",
      "default": "opus"
     },
     "is_redacted": {
      "type": "boolean",
      "title": "Is Redacted",
      "default": false
     },
     "retention_years": {
      "type": "integer",
      "maximum": 10.0,
      "minimum": 1.0,
      "title": "Retention Years",
      "default": 2
     }
    },
    "type": "object",
    "required": [
     "audio_base64"
    ],
    "title": "ArchiveCallIn"
   },
   "ArchivePurgeIn": {
    "properties": {
     "dry_run": {
      "type": "boolean",
      "title": "Dry Run",
      "default": true
     },
     "target_date": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Target Date"
     }
    },
    "type": "object",
    "title": "ArchivePurgeIn"
   },
   "AudioCacheLookupIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 1000,
      "minLength": 1,
      "title": "Text"
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "AudioCacheLookupIn"
   },
   "BatchedBenchmarkIn": {
    "properties": {
     "texts": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Texts"
     },
     "seed": {
      "type": "integer",
      "title": "Seed",
      "default": 9
     },
     "concurrency": {
      "type": "integer",
      "maximum": 32.0,
      "minimum": 1.0,
      "title": "Concurrency",
      "default": 8
     }
    },
    "type": "object",
    "title": "BatchedBenchmarkIn"
   },
   "BatchedODEConfigIn": {
    "properties": {
     "enabled": {
      "type": "boolean",
      "title": "Enabled",
      "default": true
     },
     "batch_size": {
      "type": "integer",
      "maximum": 32.0,
      "minimum": 1.0,
      "title": "Batch Size",
      "default": 8
     },
     "micro_window_ms": {
      "type": "number",
      "maximum": 100.0,
      "minimum": 1.0,
      "title": "Micro Window Ms",
      "default": 12.0
     },
     "max_concurrent_calls": {
      "type": "integer",
      "maximum": 200.0,
      "minimum": 1.0,
      "title": "Max Concurrent Calls",
      "default": 50
     },
     "steps": {
      "type": "integer",
      "maximum": 64.0,
      "minimum": 8.0,
      "title": "Steps",
      "default": 32
     }
    },
    "type": "object",
    "title": "BatchedODEConfigIn"
   },
   "BayBookingIn": {
    "properties": {
     "appointment_id": {
      "type": "string",
      "maxLength": 64,
      "minLength": 1,
      "title": "Appointment Id"
     },
     "package_type": {
      "type": "string",
      "maxLength": 64,
      "title": "Package Type",
      "default": "standart_ekspertiz"
     },
     "start_time_iso": {
      "type": "string",
      "maxLength": 40,
      "minLength": 10,
      "title": "Start Time Iso"
     },
     "plate": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Plate",
      "default": ""
     },
     "notes": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "appointment_id",
     "start_time_iso"
    ],
    "title": "BayBookingIn"
   },
   "BayCapacityCheckIn": {
    "properties": {
     "package_type": {
      "type": "string",
      "maxLength": 64,
      "title": "Package Type",
      "default": "standart_ekspertiz"
     },
     "requested_start_iso": {
      "type": "string",
      "maxLength": 40,
      "minLength": 10,
      "title": "Requested Start Iso"
     },
     "exclude_schedule_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Exclude Schedule Id"
     }
    },
    "type": "object",
    "required": [
     "requested_start_iso"
    ],
    "title": "BayCapacityCheckIn"
   },
   "BayStatusIn": {
    "properties": {
     "status": {
      "type": "string",
      "maxLength": 32,
      "minLength": 3,
      "title": "Status"
     }
    },
    "type": "object",
    "required": [
     "status"
    ],
    "title": "BayStatusIn"
   },
   "Body_denoise_audio_preview_api_dsp_denoise_preview_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "audio_file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "Audio File"
     },
     "hpf_cutoff": {
      "type": "number",
      "title": "Hpf Cutoff"
     },
     "suppression_db": {
      "type": "number",
      "title": "Suppression Db"
     },
     "target_dbfs": {
      "type": "number",
      "title": "Target Dbfs"
     }
    },
    "type": "object",
    "title": "Body_denoise_audio_preview_api_dsp_denoise_preview_post"
   },
   "Body_kvkk_redact_audio_endpoint_api_kvkk_redact_audio_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "ranges_json": {
      "type": "string",
      "title": "Ranges Json",
      "default": "[]"
     },
     "mode": {
      "type": "string",
      "title": "Mode",
      "default": "beep"
     }
    },
    "type": "object",
    "required": [
     "file"
    ],
    "title": "Body_kvkk_redact_audio_endpoint_api_kvkk_redact_audio_post"
   },
   "Body_ruhsat_decode_image_endpoint_api_ruhsat_decode_image_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "from_phone": {
      "type": "string",
      "title": "From Phone",
      "default": ""
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     }
    },
    "type": "object",
    "title": "Body_ruhsat_decode_image_endpoint_api_ruhsat_decode_image_post"
   },
   "Body_technician_dictate_audio_api_technician_dictate_audio_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "report_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Report Id"
     },
     "vehicle_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Vehicle Id"
     },
     "technician_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Technician Name",
      "default": "Uzman Teknisyen"
     }
    },
    "type": "object",
    "required": [
     "file"
    ],
    "title": "Body_technician_dictate_audio_api_technician_dictate_audio_post"
   },
   "Body_upload_inspection_photo_api_inspections_photos_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "caption": {
      "type": "string",
      "title": "Caption",
      "default": ""
     },
     "category": {
      "type": "string",
      "title": "Category",
      "default": "Genel"
     }
    },
    "type": "object",
    "required": [
     "file"
    ],
    "title": "Body_upload_inspection_photo_api_inspections_photos_post"
   },
   "Body_whatsapp_inbound_image_endpoint_api_whatsapp_inbound_image_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "image_file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "Image File"
     },
     "from_phone": {
      "type": "string",
      "title": "From Phone"
     },
     "phone": {
      "type": "string",
      "title": "Phone"
     },
     "customer_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Customer Name"
     }
    },
    "type": "object",
    "title": "Body_whatsapp_inbound_image_endpoint_api_whatsapp_inbound_image_post"
   },
   "Body_whatsapp_inbound_voice_endpoint_api_whatsapp_inbound_voice_post": {
    "properties": {
     "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
     },
     "audio_file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "Audio File"
     },
     "from_phone": {
      "type": "string",
      "title": "From Phone"
     },
     "phone": {
      "type": "string",
      "title": "Phone"
     },
     "customer_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Customer Name"
     }
    },
    "type": "object",
    "title": "Body_whatsapp_inbound_voice_endpoint_api_whatsapp_inbound_voice_post"
   },
   "BookingIn": {
    "properties": {
     "slot_id": {
      "type": "string",
      "title": "Slot Id"
     },
     "vehicle_id": {
      "type": "string",
      "title": "Vehicle Id"
     },
     "customer": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Customer"
     },
     "customer_phone": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 30
       },
       {
        "type": "null"
       }
      ],
      "title": "Customer Phone",
      "default": ""
     },
     "idempotency_key": {
      "type": "string",
      "maxLength": 100,
      "minLength": 8,
      "title": "Idempotency Key"
     },
     "confirmed": {
      "type": "boolean",
      "title": "Confirmed",
      "default": false
     },
     "corporate_account_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Corporate Account Id"
     },
     "package_type": {
      "type": "string",
      "maxLength": 64,
      "title": "Package Type",
      "default": "standart_ekspertiz"
     }
    },
    "type": "object",
    "required": [
     "slot_id",
     "vehicle_id",
     "customer",
     "idempotency_key"
    ],
    "title": "BookingIn"
   },
   "CallAnalyticsIn": {
    "properties": {
     "conversation_id": {
      "type": "string",
      "minLength": 1,
      "title": "Conversation Id"
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     },
     "caller_phone": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Caller Phone"
     },
     "caller_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Caller Name"
     },
     "duration_sec": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Duration Sec"
     },
     "transcript": {
      "anyOf": [
       {
        "items": {
         "additionalProperties": true,
         "type": "object"
        },
        "type": "array"
       },
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Transcript"
     }
    },
    "type": "object",
    "required": [
     "conversation_id"
    ],
    "title": "CallAnalyticsIn"
   },
   "CallOutcomeIn": {
    "properties": {
     "outcome": {
      "type": "string",
      "pattern": "^(confirmed|cancelled|unreachable)$",
      "title": "Outcome"
     },
     "notes": {
      "type": "string",
      "maxLength": 200,
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "outcome"
    ],
    "title": "CallOutcomeIn"
   },
   "CampaignDialIn": {
    "properties": {
     "appointment_ids": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Appointment Ids"
     },
     "dial_mode": {
      "type": "string",
      "enum": [
       "ami",
       "callfile"
      ],
      "title": "Dial Mode",
      "default": "ami"
     },
     "call_type": {
      "type": "string",
      "maxLength": 32,
      "title": "Call Type",
      "default": "reminder"
     }
    },
    "type": "object",
    "required": [
     "appointment_ids"
    ],
    "title": "CampaignDialIn"
   },
   "CardValidateIn": {
    "properties": {
     "card_number": {
      "type": "string",
      "maxLength": 30,
      "minLength": 12,
      "title": "Card Number"
     }
    },
    "type": "object",
    "required": [
     "card_number"
    ],
    "title": "CardValidateIn"
   },
   "ConversationResolveIn": {
    "properties": {
     "notes": {
      "type": "string",
      "maxLength": 1000,
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "title": "ConversationResolveIn"
   },
   "CorporateAccountIn": {
    "properties": {
     "name": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Name"
     },
     "tax_id": {
      "type": "string",
      "maxLength": 11,
      "minLength": 10,
      "title": "Tax Id"
     },
     "phone": {
      "type": "string",
      "maxLength": 20,
      "title": "Phone",
      "default": ""
     },
     "credit_limit_kurus": {
      "type": "integer",
      "exclusiveMinimum": 0.0,
      "title": "Credit Limit Kurus",
      "default": 5000000
     },
     "discount_percent": {
      "type": "integer",
      "maximum": 100.0,
      "minimum": 0.0,
      "title": "Discount Percent",
      "default": 10
     },
     "active": {
      "type": "boolean",
      "title": "Active",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "name",
     "tax_id"
    ],
    "title": "CorporateAccountIn"
   },
   "CorporateAccountUpdateIn": {
    "properties": {
     "name": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 120,
        "minLength": 2
       },
       {
        "type": "null"
       }
      ],
      "title": "Name"
     },
     "phone": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 20
       },
       {
        "type": "null"
       }
      ],
      "title": "Phone"
     },
     "credit_limit_kurus": {
      "anyOf": [
       {
        "type": "integer",
        "exclusiveMinimum": 0.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Credit Limit Kurus"
     },
     "discount_percent": {
      "anyOf": [
       {
        "type": "integer",
        "maximum": 100.0,
        "minimum": 0.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Discount Percent"
     },
     "active": {
      "anyOf": [
       {
        "type": "boolean"
       },
       {
        "type": "null"
       }
      ],
      "title": "Active"
     }
    },
    "type": "object",
    "title": "CorporateAccountUpdateIn"
   },
   "DSPConfigIn": {
    "properties": {
     "enabled": {
      "type": "boolean",
      "title": "Enabled",
      "default": true
     },
     "hpf_cutoff": {
      "type": "number",
      "maximum": 400.0,
      "minimum": 40.0,
      "title": "Hpf Cutoff",
      "default": 120.0
     },
     "suppression_db": {
      "type": "number",
      "maximum": 36.0,
      "minimum": 0.0,
      "title": "Suppression Db",
      "default": 18.0
     },
     "target_dbfs": {
      "type": "number",
      "maximum": -6.0,
      "minimum": -40.0,
      "title": "Target Dbfs",
      "default": -16.0
     },
     "noise_gate_dbfs": {
      "type": "number",
      "maximum": -20.0,
      "minimum": -60.0,
      "title": "Noise Gate Dbfs",
      "default": -42.0
     },
     "max_boost_db": {
      "type": "number",
      "maximum": 24.0,
      "minimum": 0.0,
      "title": "Max Boost Db",
      "default": 12.0
     }
    },
    "type": "object",
    "title": "DSPConfigIn"
   },
   "DSPProcessIn": {
    "properties": {
     "audio_base64": {
      "type": "string",
      "maxLength": 34952536,
      "minLength": 1,
      "title": "Audio Base64"
     },
     "apply_de_esser": {
      "type": "boolean",
      "title": "Apply De Esser",
      "default": true
     },
     "inject_comfort_noise": {
      "type": "boolean",
      "title": "Inject Comfort Noise",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "audio_base64"
    ],
    "title": "DSPProcessIn"
   },
   "DTMFIn": {
    "properties": {
     "digit": {
      "type": "string",
      "maxLength": 10,
      "minLength": 1,
      "title": "Digit"
     },
     "session_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Session Id"
     }
    },
    "type": "object",
    "required": [
     "digit"
    ],
    "title": "DTMFIn"
   },
   "DatasetGenerateRequest": {
    "properties": {
     "count": {
      "type": "integer",
      "maximum": 10000.0,
      "minimum": 1.0,
      "title": "Count",
      "description": "Üretilecek diyalog sayısı",
      "default": 50
     },
     "format": {
      "type": "string",
      "pattern": "^(alpaca|sharegpt)$",
      "title": "Format",
      "description": "Format: alpaca veya sharegpt",
      "default": "alpaca"
     },
     "seed": {
      "type": "integer",
      "title": "Seed",
      "description": "Deterministik rastgelelik tohumu",
      "default": 42
     }
    },
    "type": "object",
    "title": "DatasetGenerateRequest"
   },
   "DiagnosticFaultConcept": {
    "properties": {
     "obd_code": {
      "type": "string",
      "title": "Obd Code"
     },
     "system": {
      "type": "string",
      "title": "System"
     },
     "warning_light": {
      "type": "string",
      "title": "Warning Light"
     },
     "severity": {
      "$ref": "#/components/schemas/DiagnosticSeverity"
     },
     "description": {
      "type": "string",
      "title": "Description"
     },
     "common_symptoms": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Common Symptoms"
     },
     "suggested_action": {
      "type": "string",
      "title": "Suggested Action"
     },
     "recommended_package_id": {
      "type": "string",
      "title": "Recommended Package Id"
     }
    },
    "type": "object",
    "required": [
     "obd_code",
     "system",
     "warning_light",
     "severity",
     "description",
     "common_symptoms",
     "suggested_action",
     "recommended_package_id"
    ],
    "title": "DiagnosticFaultConcept"
   },
   "DiagnosticSeverity": {
    "type": "string",
    "enum": [
     "info",
     "low",
     "medium",
     "high",
     "critical"
    ],
    "title": "DiagnosticSeverity"
   },
   "DictationTextIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 5000,
      "minLength": 1,
      "title": "Text"
     },
     "report_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Report Id"
     },
     "vehicle_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Vehicle Id"
     },
     "technician_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Technician Name",
      "default": "Uzman Teknisyen"
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "DictationTextIn"
   },
   "EmotionAdaptIn": {
    "properties": {
     "assistant_response_text": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 1,
      "title": "Assistant Response Text"
     },
     "caller_transcript": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Caller Transcript"
     },
     "emotion_category": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Emotion Category"
     }
    },
    "type": "object",
    "required": [
     "assistant_response_text"
    ],
    "title": "EmotionAdaptIn"
   },
   "EmotionAnalyzeIn": {
    "properties": {
     "transcript": {
      "type": "string",
      "maxLength": 2000,
      "title": "Transcript",
      "default": ""
     },
     "audio_base64": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 34952536
       },
       {
        "type": "null"
       }
      ],
      "title": "Audio Base64"
     },
     "audio_duration_sec": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Audio Duration Sec"
     },
     "sample_rate": {
      "type": "integer",
      "maximum": 48000.0,
      "minimum": 8000.0,
      "title": "Sample Rate",
      "default": 16000
     }
    },
    "type": "object",
    "title": "EmotionAnalyzeIn"
   },
   "FeedbackLexiconIn": {
    "properties": {
     "term": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Term"
     },
     "spoken": {
      "type": "string",
      "maxLength": 160,
      "minLength": 1,
      "title": "Spoken"
     },
     "category": {
      "type": "string",
      "maxLength": 50,
      "title": "Category",
      "default": "custom"
     },
     "turn_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Turn Id"
     }
    },
    "type": "object",
    "required": [
     "term",
     "spoken"
    ],
    "title": "FeedbackLexiconIn"
   },
   "GPUConfigureIn": {
    "properties": {
     "vram_threshold_percent": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 99.0,
        "minimum": 10.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Vram Threshold Percent"
     },
     "temp_threshold_c": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 100.0,
        "minimum": 40.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Temp Threshold C"
     },
     "latency_threshold_ms": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 2000.0,
        "minimum": 50.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Latency Threshold Ms"
     },
     "cooldown_seconds": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 300.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Cooldown Seconds"
     },
     "consecutive_failure_limit": {
      "anyOf": [
       {
        "type": "integer",
        "maximum": 20.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Consecutive Failure Limit"
     },
     "default_failover_mode": {
      "anyOf": [
       {
        "type": "string",
        "pattern": "^(cpu_cache|operator_transfer|graceful_degrade)$"
       },
       {
        "type": "null"
       }
      ],
      "title": "Default Failover Mode"
     }
    },
    "type": "object",
    "title": "GPUConfigureIn"
   },
   "GPUSimulateIn": {
    "properties": {
     "simulate_oom": {
      "type": "boolean",
      "title": "Simulate Oom",
      "default": false
     },
     "vram_percent": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Vram Percent"
     },
     "temperature_c": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Temperature C"
     },
     "latency_ms": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Latency Ms"
     }
    },
    "type": "object",
    "title": "GPUSimulateIn"
   },
   "HTTPValidationError": {
    "properties": {
     "detail": {
      "items": {
       "$ref": "#/components/schemas/ValidationError"
      },
      "type": "array",
      "title": "Detail"
     }
    },
    "type": "object",
    "title": "HTTPValidationError"
   },
   "HotwordsIn": {
    "properties": {
     "words": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Words"
     }
    },
    "type": "object",
    "required": [
     "words"
    ],
    "title": "HotwordsIn"
   },
   "InspectionReportIn": {
    "properties": {
     "summary": {
      "type": "string",
      "maxLength": 1000,
      "minLength": 5,
      "title": "Summary"
     },
     "mileage_km": {
      "type": "integer",
      "minimum": 0.0,
      "title": "Mileage Km"
     },
     "score": {
      "type": "integer",
      "maximum": 100.0,
      "minimum": 0.0,
      "title": "Score"
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     },
     "technician_name": {
      "type": "string",
      "title": "Technician Name",
      "default": "Uzman Teknisyen"
     },
     "findings": {
      "additionalProperties": true,
      "type": "object",
      "title": "Findings"
     },
     "photos": {
      "items": {
       "additionalProperties": true,
       "type": "object"
      },
      "type": "array",
      "title": "Photos"
     }
    },
    "type": "object",
    "required": [
     "summary",
     "mileage_km",
     "score"
    ],
    "title": "InspectionReportIn"
   },
   "KVKKErasureExecuteIn": {
    "properties": {
     "confirmed_record_count": {
      "type": "integer",
      "minimum": 0.0,
      "title": "Confirmed Record Count"
     }
    },
    "type": "object",
    "required": [
     "confirmed_record_count"
    ],
    "title": "KVKKErasureExecuteIn"
   },
   "KVKKErasureRequestIn": {
    "properties": {
     "identifier_type": {
      "type": "string",
      "enum": [
       "phone",
       "plate",
       "customer_name",
       "conversation_id"
      ],
      "title": "Identifier Type",
      "default": "phone"
     },
     "identifier_value": {
      "type": "string",
      "maxLength": 120,
      "minLength": 3,
      "title": "Identifier Value"
     },
     "requester_name": {
      "type": "string",
      "maxLength": 120,
      "title": "Requester Name",
      "default": ""
     },
     "reason": {
      "type": "string",
      "maxLength": 255,
      "title": "Reason",
      "default": "KVKK Madde 11 uyarınca silme talebi"
     },
     "notes": {
      "type": "string",
      "maxLength": 1000,
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "identifier_value"
    ],
    "title": "KVKKErasureRequestIn"
   },
   "KVKKRedactIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 10000,
      "minLength": 1,
      "title": "Text"
     },
     "categories": {
      "anyOf": [
       {
        "items": {
         "type": "string"
        },
        "type": "array"
       },
       {
        "type": "null"
       }
      ],
      "title": "Categories"
     },
     "mask_char": {
      "type": "string",
      "title": "Mask Char",
      "default": "*"
     },
     "validate_strict": {
      "type": "boolean",
      "title": "Validate Strict",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "KVKKRedactIn"
   },
   "LexiconTermIn": {
    "properties": {
     "term": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Term"
     },
     "spoken": {
      "type": "string",
      "maxLength": 160,
      "minLength": 1,
      "title": "Spoken"
     },
     "category": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 50
       },
       {
        "type": "null"
       }
      ],
      "title": "Category",
      "default": "custom"
     }
    },
    "type": "object",
    "required": [
     "term",
     "spoken"
    ],
    "title": "LexiconTermIn"
   },
   "LiftAssignIn": {
    "properties": {
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     },
     "queue_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Queue Id"
     },
     "plate": {
      "type": "string",
      "maxLength": 32,
      "title": "Plate",
      "default": ""
     },
     "package_type": {
      "type": "string",
      "maxLength": 64,
      "title": "Package Type",
      "default": "standart_ekspertiz"
     }
    },
    "type": "object",
    "title": "LiftAssignIn"
   },
   "LiftIn": {
    "properties": {
     "name": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Name"
     },
     "lift_number": {
      "anyOf": [
       {
        "type": "integer",
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Lift Number"
     },
     "notes": {
      "type": "string",
      "maxLength": 500,
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "name"
    ],
    "title": "LiftIn"
   },
   "LiftStatusIn": {
    "properties": {
     "status": {
      "type": "string",
      "pattern": "^(idle|busy|maintenance)$",
      "title": "Status"
     },
     "notes": {
      "type": "string",
      "maxLength": 500,
      "title": "Notes",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "status"
    ],
    "title": "LiftStatusIn"
   },
   "MorphologicalCheckIn": {
    "properties": {
     "text": {
      "type": "string",
      "title": "Text"
     },
     "include_hints": {
      "type": "boolean",
      "title": "Include Hints",
      "default": true
     },
     "chunk_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Chunk Id",
      "default": "chunk_0"
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "MorphologicalCheckIn"
   },
   "OntologyEdge": {
    "properties": {
     "source": {
      "type": "string",
      "title": "Source"
     },
     "target": {
      "type": "string",
      "title": "Target"
     },
     "relation": {
      "$ref": "#/components/schemas/RelationType"
     },
     "description": {
      "type": "string",
      "title": "Description",
      "default": ""
     },
     "is_required": {
      "type": "boolean",
      "title": "Is Required",
      "default": false
     }
    },
    "type": "object",
    "required": [
     "source",
     "target",
     "relation"
    ],
    "title": "OntologyEdge"
   },
   "OntologyNode": {
    "properties": {
     "id": {
      "type": "string",
      "title": "Id"
     },
     "name": {
      "type": "string",
      "title": "Name"
     },
     "type": {
      "$ref": "#/components/schemas/OntologyNodeType"
     },
     "domain": {
      "type": "string",
      "title": "Domain",
      "default": "automotive"
     },
     "description": {
      "type": "string",
      "title": "Description"
     },
     "properties": {
      "additionalProperties": true,
      "type": "object",
      "title": "Properties"
     },
     "is_certified": {
      "type": "boolean",
      "title": "Is Certified",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "id",
     "name",
     "type",
     "description"
    ],
    "title": "OntologyNode"
   },
   "OntologyNodeType": {
    "type": "string",
    "enum": [
     "table",
     "concept",
     "metric",
     "rule"
    ],
    "title": "OntologyNodeType"
   },
   "OntologySchemaGraph": {
    "properties": {
     "version": {
      "type": "string",
      "title": "Version",
      "default": "1.0.0"
     },
     "generated_at": {
      "type": "string",
      "title": "Generated At"
     },
     "database_type": {
      "type": "string",
      "title": "Database Type",
      "default": "sqlite"
     },
     "table_count": {
      "type": "integer",
      "title": "Table Count"
     },
     "concept_count": {
      "type": "integer",
      "title": "Concept Count"
     },
     "nodes": {
      "items": {
       "$ref": "#/components/schemas/OntologyNode"
      },
      "type": "array",
      "title": "Nodes"
     },
     "edges": {
      "items": {
       "$ref": "#/components/schemas/OntologyEdge"
      },
      "type": "array",
      "title": "Edges"
     }
    },
    "type": "object",
    "required": [
     "generated_at",
     "table_count",
     "concept_count",
     "nodes",
     "edges"
    ],
    "title": "OntologySchemaGraph"
   },
   "OntologyValidationRequest": {
    "properties": {
     "action_type": {
      "type": "string",
      "title": "Action Type"
     },
     "payload": {
      "additionalProperties": true,
      "type": "object",
      "title": "Payload"
     },
     "strict_mode": {
      "type": "boolean",
      "title": "Strict Mode",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "action_type",
     "payload"
    ],
    "title": "OntologyValidationRequest"
   },
   "OntologyValidationResult": {
    "properties": {
     "valid": {
      "type": "boolean",
      "title": "Valid"
     },
     "action_type": {
      "type": "string",
      "title": "Action Type"
     },
     "errors": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Errors"
     },
     "warnings": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Warnings"
     },
     "certified_payload": {
      "additionalProperties": true,
      "type": "object",
      "title": "Certified Payload"
     },
     "policy_reference": {
      "type": "string",
      "title": "Policy Reference",
      "default": "Freya-Auto-Ontology-v1"
     }
    },
    "type": "object",
    "required": [
     "valid",
     "action_type"
    ],
    "title": "OntologyValidationResult"
   },
   "OperatorRegisterCallIn": {
    "properties": {
     "session_id": {
      "type": "string",
      "title": "Session Id"
     },
     "caller_id": {
      "type": "string",
      "title": "Caller Id"
     },
     "initial_turn_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Initial Turn Id"
     },
     "mos_score": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Mos Score"
     },
     "rtf": {
      "anyOf": [
       {
        "type": "number"
       },
       {
        "type": "null"
       }
      ],
      "title": "Rtf"
     }
    },
    "type": "object",
    "required": [
     "session_id",
     "caller_id"
    ],
    "title": "OperatorRegisterCallIn"
   },
   "OperatorReleaseIn": {
    "properties": {
     "session_id": {
      "type": "string",
      "title": "Session Id"
     },
     "operator_id": {
      "type": "string",
      "title": "Operator Id"
     }
    },
    "type": "object",
    "required": [
     "session_id",
     "operator_id"
    ],
    "title": "OperatorReleaseIn"
   },
   "OperatorTakeoverIn": {
    "properties": {
     "session_id": {
      "type": "string",
      "title": "Session Id"
     },
     "operator_id": {
      "type": "string",
      "title": "Operator Id"
     },
     "reason": {
      "type": "string",
      "title": "Reason",
      "default": "customer_request"
     }
    },
    "type": "object",
    "required": [
     "session_id",
     "operator_id"
    ],
    "title": "OperatorTakeoverIn"
   },
   "OperatorWhisperIn": {
    "properties": {
     "session_id": {
      "type": "string",
      "title": "Session Id"
     },
     "operator_id": {
      "type": "string",
      "title": "Operator Id"
     },
     "message": {
      "type": "string",
      "title": "Message"
     }
    },
    "type": "object",
    "required": [
     "session_id",
     "operator_id",
     "message"
    ],
    "title": "OperatorWhisperIn"
   },
   "OutboundCallIn": {
    "properties": {
     "appointment_id": {
      "type": "string",
      "title": "Appointment Id"
     },
     "phone": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 40
       },
       {
        "type": "null"
       }
      ],
      "title": "Phone"
     },
     "call_type": {
      "type": "string",
      "maxLength": 32,
      "title": "Call Type",
      "default": "reminder"
     }
    },
    "type": "object",
    "required": [
     "appointment_id"
    ],
    "title": "OutboundCallIn"
   },
   "PauseCleanIn": {
    "properties": {
     "audio_base64": {
      "type": "string",
      "maxLength": 34952536,
      "minLength": 4,
      "title": "Audio Base64"
     },
     "sample_rate": {
      "type": "integer",
      "maximum": 48000.0,
      "minimum": 8000.0,
      "title": "Sample Rate",
      "default": 8000
     },
     "fade_ms": {
      "type": "number",
      "maximum": 50.0,
      "minimum": 1.0,
      "title": "Fade Ms",
      "default": 12.0
     }
    },
    "type": "object",
    "required": [
     "audio_base64"
    ],
    "title": "PauseCleanIn"
   },
   "PaymentIn": {
    "properties": {
     "amount_kurus": {
      "type": "integer",
      "maximum": 1000000000000.0,
      "exclusiveMinimum": 0.0,
      "title": "Amount Kurus"
     },
     "description": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Description",
      "default": "Tahsilat / Ödeme"
     }
    },
    "type": "object",
    "required": [
     "amount_kurus"
    ],
    "title": "PaymentIn"
   },
   "PhoneticDecodeIn": {
    "properties": {
     "spoken_text": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 1,
      "title": "Spoken Text"
     }
    },
    "type": "object",
    "required": [
     "spoken_text"
    ],
    "title": "PhoneticDecodeIn"
   },
   "ProactiveActionIn": {
    "properties": {
     "phone": {
      "type": "string",
      "title": "Phone",
      "default": ""
     }
    },
    "type": "object",
    "title": "ProactiveActionIn"
   },
   "QAEvaluateVariantsIn": {
    "properties": {
     "samples": {
      "anyOf": [
       {
        "items": {
         "prefixItems": [
          {
           "type": "string"
          },
          {
           "type": "string"
          }
         ],
         "type": "array",
         "maxItems": 2,
         "minItems": 2
        },
        "type": "array"
       },
       {
        "type": "null"
       }
      ],
      "title": "Samples"
     }
    },
    "type": "object",
    "title": "QAEvaluateVariantsIn"
   },
   "QueueEntryIn": {
    "properties": {
     "plate": {
      "type": "string",
      "maxLength": 32,
      "minLength": 2,
      "title": "Plate"
     },
     "customer": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Customer"
     },
     "package_type": {
      "type": "string",
      "maxLength": 64,
      "title": "Package Type",
      "default": "standart_ekspertiz"
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     },
     "vehicle_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Vehicle Id"
     }
    },
    "type": "object",
    "required": [
     "plate",
     "customer"
    ],
    "title": "QueueEntryIn"
   },
   "QuoteIn": {
    "properties": {
     "vehicle_id": {
      "type": "string",
      "title": "Vehicle Id"
     },
     "amount_kurus": {
      "type": "integer",
      "maximum": 1000000000000.0,
      "exclusiveMinimum": 0.0,
      "title": "Amount Kurus"
     }
    },
    "type": "object",
    "required": [
     "vehicle_id",
     "amount_kurus"
    ],
    "title": "QuoteIn"
   },
   "RelationType": {
    "type": "string",
    "enum": [
     "foreign_key",
     "owns",
     "has_fault",
     "requires_package",
     "assigned_to",
     "defines_price",
     "validates_with",
     "constrained_by"
    ],
    "title": "RelationType"
   },
   "RescheduleIn": {
    "properties": {
     "target_slot_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Target Slot Id"
     },
     "new_starts_at": {
      "anyOf": [
       {
        "type": "string",
        "format": "date-time"
       },
       {
        "type": "null"
       }
      ],
      "title": "New Starts At"
     },
     "preview_version": {
      "anyOf": [
       {
        "type": "string",
        "pattern": "^[a-f0-9]{64}$"
       },
       {
        "type": "null"
       }
      ],
      "title": "Preview Version"
     }
    },
    "type": "object",
    "title": "RescheduleIn"
   },
   "ReviewIn": {
    "properties": {
     "annotation_id": {
      "type": "string",
      "maxLength": 128,
      "minLength": 1,
      "title": "Annotation Id"
     },
     "decision": {
      "type": "string",
      "title": "Decision"
     },
     "reviewer": {
      "type": "string",
      "maxLength": 48,
      "minLength": 1,
      "title": "Reviewer"
     },
     "reason_code": {
      "type": "string",
      "title": "Reason Code"
     }
    },
    "type": "object",
    "required": [
     "annotation_id",
     "decision",
     "reviewer",
     "reason_code"
    ],
    "title": "ReviewIn"
   },
   "RuhsatApplyIn": {
    "properties": {
     "scan_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Scan Id"
     },
     "plate": {
      "type": "string",
      "maxLength": 32,
      "minLength": 2,
      "title": "Plate"
     },
     "vin": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Vin"
     },
     "brand_model": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Brand Model"
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     }
    },
    "type": "object",
    "required": [
     "plate"
    ],
    "title": "RuhsatApplyIn"
   },
   "RuhsatTextDecodeIn": {
    "properties": {
     "ocr_text": {
      "type": "string",
      "maxLength": 5000,
      "minLength": 1,
      "title": "Ocr Text"
     }
    },
    "type": "object",
    "required": [
     "ocr_text"
    ],
    "title": "RuhsatTextDecodeIn"
   },
   "SFTConfigureIn": {
    "properties": {
     "learning_rate": {
      "type": "number",
      "maximum": 0.0001,
      "minimum": 1e-07,
      "title": "Learning Rate",
      "default": 2e-06
     },
     "min_steps": {
      "type": "integer",
      "maximum": 5000.0,
      "minimum": 10.0,
      "title": "Min Steps",
      "default": 75
     },
     "max_steps": {
      "type": "integer",
      "maximum": 20000.0,
      "minimum": 75.0,
      "title": "Max Steps",
      "default": 1000
     },
     "f0_max_drift_hz": {
      "type": "number",
      "maximum": 10.0,
      "minimum": 0.5,
      "title": "F0 Max Drift Hz",
      "default": 2.3
     }
    },
    "type": "object",
    "title": "SFTConfigureIn"
   },
   "SFTCorpusIn": {
    "properties": {
     "count": {
      "type": "integer",
      "maximum": 500.0,
      "minimum": 5.0,
      "title": "Count",
      "default": 50
     }
    },
    "type": "object",
    "title": "SFTCorpusIn"
   },
   "SFTLoRABenchmarkIn": {
    "properties": {
     "steps": {
      "type": "integer",
      "maximum": 20.0,
      "minimum": 1.0,
      "title": "Steps",
      "default": 5
     },
     "total_target_steps": {
      "type": "integer",
      "maximum": 10000.0,
      "minimum": 50.0,
      "title": "Total Target Steps",
      "default": 1000
     }
    },
    "type": "object",
    "title": "SFTLoRABenchmarkIn"
   },
   "SFTLoRAConfigureIn": {
    "properties": {
     "r": {
      "type": "integer",
      "maximum": 64.0,
      "minimum": 4.0,
      "title": "R",
      "default": 16
     },
     "lora_alpha": {
      "type": "integer",
      "maximum": 128.0,
      "minimum": 8.0,
      "title": "Lora Alpha",
      "default": 32
     },
     "lora_dropout": {
      "type": "number",
      "maximum": 0.5,
      "minimum": 0.0,
      "title": "Lora Dropout",
      "default": 0.05
     },
     "learning_rate": {
      "type": "number",
      "maximum": 0.0001,
      "minimum": 1e-06,
      "title": "Learning Rate",
      "default": 2e-05
     },
     "batch_size": {
      "type": "integer",
      "maximum": 4.0,
      "minimum": 1.0,
      "title": "Batch Size",
      "default": 1
     },
     "grad_accum": {
      "type": "integer",
      "maximum": 32.0,
      "minimum": 1.0,
      "title": "Grad Accum",
      "default": 8
     }
    },
    "type": "object",
    "title": "SFTLoRAConfigureIn"
   },
   "SFTTrainIn": {
    "properties": {
     "steps": {
      "type": "integer",
      "maximum": 200.0,
      "minimum": 1.0,
      "title": "Steps",
      "default": 10
     }
    },
    "type": "object",
    "title": "SFTTrainIn"
   },
   "SLAConfigureIn": {
    "properties": {
     "max_p95_latency_ms": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 2000.0,
        "minimum": 50.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Max P95 Latency Ms"
     },
     "min_call_answer_rate_pct": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 100.0,
        "minimum": 50.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Min Call Answer Rate Pct"
     },
     "min_mos_score": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 5.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Min Mos Score"
     },
     "max_packet_loss_pct": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 50.0,
        "minimum": 0.1
       },
       {
        "type": "null"
       }
      ],
      "title": "Max Packet Loss Pct"
     },
     "max_gpu_vram_pct": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 99.0,
        "minimum": 10.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Max Gpu Vram Pct"
     },
     "max_gpu_temp_c": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 100.0,
        "minimum": 40.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Max Gpu Temp C"
     },
     "max_queue_wait_sec": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 300.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Max Queue Wait Sec"
     }
    },
    "type": "object",
    "title": "SLAConfigureIn"
   },
   "SLARecordCallIn": {
    "properties": {
     "success": {
      "type": "boolean",
      "title": "Success",
      "default": true
     },
     "duration_sec": {
      "type": "number",
      "maximum": 7200.0,
      "minimum": 1.0,
      "title": "Duration Sec",
      "default": 60.0
     },
     "packet_loss_pct": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 100.0,
        "minimum": 0.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Packet Loss Pct"
     },
     "jitter_ms": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 1000.0,
        "minimum": 0.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Jitter Ms"
     },
     "csat_score": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 5.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Csat Score"
     },
     "queue_wait_sec": {
      "anyOf": [
       {
        "type": "number",
        "maximum": 3600.0,
        "minimum": 0.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Queue Wait Sec"
     },
     "converted_to_appointment": {
      "type": "boolean",
      "title": "Converted To Appointment",
      "default": false
     }
    },
    "type": "object",
    "title": "SLARecordCallIn"
   },
   "ServicePackageConcept": {
    "properties": {
     "package_id": {
      "type": "string",
      "title": "Package Id"
     },
     "name": {
      "type": "string",
      "title": "Name"
     },
     "price_tl": {
      "type": "integer",
      "title": "Price Tl"
     },
     "duration_min": {
      "type": "integer",
      "title": "Duration Min"
     },
     "description": {
      "type": "string",
      "title": "Description"
     },
     "included_checks": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Included Checks"
     },
     "recommended_for": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Recommended For"
     }
    },
    "type": "object",
    "required": [
     "package_id",
     "name",
     "price_tl",
     "duration_min",
     "description",
     "included_checks",
     "recommended_for"
    ],
    "title": "ServicePackageConcept"
   },
   "SimulateBargeInIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 1000,
      "title": "Text",
      "default": ""
     }
    },
    "type": "object",
    "title": "SimulateBargeInIn"
   },
   "SlotIn": {
    "properties": {
     "starts_at": {
      "type": "string",
      "format": "date-time",
      "title": "Starts At"
     },
     "duration_minutes": {
      "type": "integer",
      "maximum": 480.0,
      "minimum": 5.0,
      "title": "Duration Minutes",
      "default": 30
     }
    },
    "type": "object",
    "required": [
     "starts_at"
    ],
    "title": "SlotIn"
   },
   "SpokenValuationIn": {
    "properties": {
     "query_text": {
      "type": "string",
      "maxLength": 1000,
      "minLength": 1,
      "title": "Query Text"
     },
     "plate": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Plate"
     }
    },
    "type": "object",
    "required": [
     "query_text"
    ],
    "title": "SpokenValuationIn"
   },
   "TCKNValidateIn": {
    "properties": {
     "tckn": {
      "type": "string",
      "maxLength": 20,
      "minLength": 1,
      "title": "Tckn"
     }
    },
    "type": "object",
    "required": [
     "tckn"
    ],
    "title": "TCKNValidateIn"
   },
   "TechnicianStatusIn": {
    "properties": {
     "is_active": {
      "type": "boolean",
      "title": "Is Active"
     }
    },
    "type": "object",
    "required": [
     "is_active"
    ],
    "title": "TechnicianStatusIn"
   },
   "TelemetryIngestIn": {
    "properties": {
     "current_km": {
      "type": "integer",
      "minimum": 0.0,
      "title": "Current Km",
      "default": 0
     },
     "dtc_codes": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Dtc Codes"
     },
     "source": {
      "type": "string",
      "title": "Source",
      "default": "obd_dongle"
     },
     "owner_name": {
      "type": "string",
      "title": "Owner Name",
      "default": ""
     },
     "owner_phone": {
      "type": "string",
      "title": "Owner Phone",
      "default": ""
     }
    },
    "type": "object",
    "title": "TelemetryIngestIn"
   },
   "TestNotificationIn": {
    "properties": {
     "channel": {
      "type": "string",
      "pattern": "^(sms|whatsapp)$",
      "title": "Channel"
     },
     "recipient": {
      "type": "string",
      "maxLength": 40,
      "minLength": 7,
      "title": "Recipient"
     },
     "message": {
      "type": "string",
      "maxLength": 1000,
      "minLength": 1,
      "title": "Message"
     }
    },
    "type": "object",
    "required": [
     "channel",
     "recipient",
     "message"
    ],
    "title": "TestNotificationIn"
   },
   "TextIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 4000,
      "minLength": 1,
      "title": "Text"
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "TextIn"
   },
   "TranscriptRetentionPurgeIn": {
    "properties": {
     "dry_run": {
      "type": "boolean",
      "title": "Dry Run",
      "default": true
     },
     "target_date": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Target Date"
     },
     "retention_days": {
      "anyOf": [
       {
        "type": "integer",
        "maximum": 3650.0,
        "minimum": 1.0
       },
       {
        "type": "null"
       }
      ],
      "title": "Retention Days"
     }
    },
    "type": "object",
    "title": "TranscriptRetentionPurgeIn"
   },
   "TransferAcceptIn": {
    "properties": {
     "operator_channel": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Operator Channel"
     }
    },
    "type": "object",
    "title": "TransferAcceptIn"
   },
   "TransferDTMFIn": {
    "properties": {
     "digit": {
      "type": "string",
      "maxLength": 2,
      "minLength": 1,
      "title": "Digit"
     },
     "operator_channel": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Operator Channel"
     }
    },
    "type": "object",
    "required": [
     "digit"
    ],
    "title": "TransferDTMFIn"
   },
   "TransferDeclineIn": {
    "properties": {
     "reason": {
      "type": "string",
      "title": "Reason",
      "default": "declined"
     }
    },
    "type": "object",
    "title": "TransferDeclineIn"
   },
   "TransferInitiateIn": {
    "properties": {
     "conversation_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Conversation Id"
     },
     "caller_channel": {
      "type": "string",
      "title": "Caller Channel",
      "default": ""
     },
     "customer_name": {
      "type": "string",
      "title": "Customer Name",
      "default": ""
     },
     "vehicle_plate": {
      "type": "string",
      "title": "Vehicle Plate",
      "default": ""
     },
     "summary": {
      "type": "string",
      "title": "Summary",
      "default": ""
     },
     "intent": {
      "type": "string",
      "title": "Intent",
      "default": "operator_transfer"
     },
     "operator_extension": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Operator Extension"
     }
    },
    "type": "object",
    "title": "TransferInitiateIn"
   },
   "TrunkConfigIn": {
    "properties": {
     "trunk_id": {
      "type": "string",
      "maxLength": 64,
      "minLength": 2,
      "title": "Trunk Id"
     },
     "name": {
      "type": "string",
      "maxLength": 120,
      "minLength": 2,
      "title": "Name"
     },
     "host": {
      "type": "string",
      "maxLength": 120,
      "minLength": 3,
      "title": "Host"
     },
     "port": {
      "type": "integer",
      "maximum": 65535.0,
      "minimum": 1.0,
      "title": "Port",
      "default": 5060
     },
     "transport": {
      "type": "string",
      "pattern": "^(UDP|TCP|TLS)$",
      "title": "Transport",
      "default": "UDP"
     },
     "priority": {
      "type": "integer",
      "maximum": 10.0,
      "minimum": 1.0,
      "title": "Priority",
      "default": 1
     },
     "weight": {
      "type": "integer",
      "maximum": 100.0,
      "minimum": 1.0,
      "title": "Weight",
      "default": 50
     },
     "max_channels": {
      "type": "integer",
      "maximum": 1000.0,
      "minimum": 1.0,
      "title": "Max Channels",
      "default": 30
     }
    },
    "type": "object",
    "required": [
     "trunk_id",
     "name",
     "host"
    ],
    "title": "TrunkConfigIn"
   },
   "TrunkMaintenanceIn": {
    "properties": {
     "trunk_id": {
      "type": "string",
      "title": "Trunk Id"
     },
     "maintenance": {
      "type": "boolean",
      "title": "Maintenance",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "trunk_id"
    ],
    "title": "TrunkMaintenanceIn"
   },
   "TrunkSelectIn": {
    "properties": {
     "destination_phone": {
      "type": "string",
      "title": "Destination Phone",
      "default": ""
     },
     "force_priority": {
      "anyOf": [
       {
        "type": "integer"
       },
       {
        "type": "null"
       }
      ],
      "title": "Force Priority"
     },
     "exclude_trunks": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Exclude Trunks"
     }
    },
    "type": "object",
    "title": "TrunkSelectIn"
   },
   "TrunkSimulateIn": {
    "properties": {
     "trunk_id": {
      "type": "string",
      "title": "Trunk Id"
     },
     "outage": {
      "type": "boolean",
      "title": "Outage",
      "default": true
     }
    },
    "type": "object",
    "required": [
     "trunk_id"
    ],
    "title": "TrunkSimulateIn"
   },
   "TurnAnalyzeTextIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 1000,
      "title": "Text",
      "default": ""
     }
    },
    "type": "object",
    "title": "TurnAnalyzeTextIn"
   },
   "TurnEvaluateIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 1000,
      "title": "Text",
      "default": ""
     },
     "silence_duration_ms": {
      "type": "number",
      "maximum": 10000.0,
      "minimum": 0.0,
      "title": "Silence Duration Ms",
      "default": 300.0
     },
     "audio_base64": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 34952536
       },
       {
        "type": "null"
       }
      ],
      "title": "Audio Base64"
     },
     "sample_rate": {
      "type": "integer",
      "maximum": 48000.0,
      "minimum": 8000.0,
      "title": "Sample Rate",
      "default": 16000
     }
    },
    "type": "object",
    "title": "TurnEvaluateIn"
   },
   "ValidationError": {
    "properties": {
     "loc": {
      "items": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "integer"
        }
       ]
      },
      "type": "array",
      "title": "Location"
     },
     "msg": {
      "type": "string",
      "title": "Message"
     },
     "type": {
      "type": "string",
      "title": "Error Type"
     },
     "input": {
      "title": "Input"
     },
     "ctx": {
      "type": "object",
      "title": "Context"
     }
    },
    "type": "object",
    "required": [
     "loc",
     "msg",
     "type"
    ],
    "title": "ValidationError"
   },
   "VehicleConcept": {
    "properties": {
     "brand": {
      "type": "string",
      "title": "Brand"
     },
     "model": {
      "type": "string",
      "title": "Model"
     },
     "submodel": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Submodel"
     },
     "engine_type": {
      "type": "string",
      "title": "Engine Type",
      "default": "Benzin/Dizel"
     },
     "year_range": {
      "type": "string",
      "title": "Year Range",
      "default": "2010–2025"
     },
     "segment": {
      "type": "string",
      "title": "Segment",
      "default": "C"
     },
     "normalized_name": {
      "type": "string",
      "title": "Normalized Name"
     },
     "aliases": {
      "items": {
       "type": "string"
      },
      "type": "array",
      "title": "Aliases"
     }
    },
    "type": "object",
    "required": [
     "brand",
     "model",
     "normalized_name"
    ],
    "title": "VehicleConcept"
   },
   "VehicleIn": {
    "properties": {
     "description": {
      "type": "string",
      "maxLength": 200,
      "minLength": 2,
      "title": "Description"
     },
     "plate": {
      "type": "string",
      "maxLength": 20,
      "title": "Plate",
      "default": ""
     },
     "vin": {
      "type": "string",
      "maxLength": 17,
      "title": "Vin",
      "default": ""
     }
    },
    "type": "object",
    "required": [
     "description"
    ],
    "title": "VehicleIn"
   },
   "VehicleUpdateIn": {
    "properties": {
     "description": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 200,
        "minLength": 2
       },
       {
        "type": "null"
       }
      ],
      "title": "Description"
     },
     "plate": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 20
       },
       {
        "type": "null"
       }
      ],
      "title": "Plate"
     },
     "vin": {
      "anyOf": [
       {
        "type": "string",
        "maxLength": 17
       },
       {
        "type": "null"
       }
      ],
      "title": "Vin"
     }
    },
    "type": "object",
    "title": "VehicleUpdateIn"
   },
   "VehicleValuationIn": {
    "properties": {
     "brand": {
      "type": "string",
      "maxLength": 64,
      "minLength": 1,
      "title": "Brand"
     },
     "model": {
      "type": "string",
      "maxLength": 64,
      "minLength": 1,
      "title": "Model"
     },
     "model_year": {
      "type": "integer",
      "maximum": 2030.0,
      "minimum": 1990.0,
      "title": "Model Year"
     },
     "mileage_km": {
      "type": "integer",
      "maximum": 1000000.0,
      "minimum": 0.0,
      "title": "Mileage Km"
     },
     "body_panels": {
      "anyOf": [
       {
        "additionalProperties": {
         "type": "string"
        },
        "type": "object"
       },
       {
        "type": "null"
       }
      ],
      "title": "Body Panels"
     },
     "tramer_amount_tl": {
      "type": "number",
      "title": "Tramer Amount Tl",
      "default": 0.0
     },
     "is_heavy_damage": {
      "type": "boolean",
      "title": "Is Heavy Damage",
      "default": false
     },
     "plate": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Plate"
     },
     "conversation_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Conversation Id"
     },
     "appointment_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Appointment Id"
     }
    },
    "type": "object",
    "required": [
     "brand",
     "model",
     "model_year",
     "mileage_km"
    ],
    "title": "VehicleValuationIn"
   },
   "VoiceChatTurnIn": {
    "properties": {
     "text": {
      "type": "string",
      "maxLength": 4000,
      "minLength": 1,
      "title": "Text"
     },
     "session_id": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Session Id"
     },
     "reset": {
      "type": "boolean",
      "title": "Reset",
      "default": false
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "VoiceChatTurnIn"
   },
   "WhatsAppInboundIn": {
    "properties": {
     "from_phone": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "From Phone"
     },
     "phone": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Phone"
     },
     "text": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 1,
      "title": "Text"
     },
     "customer_name": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Customer Name"
     },
     "message_sid": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "title": "Message Sid"
     }
    },
    "type": "object",
    "required": [
     "text"
    ],
    "title": "WhatsAppInboundIn"
   }
  },
  "securitySchemes": {
   "HTTPBasic": {
    "type": "http",
    "scheme": "basic"
   }
  }
 }
}
```
