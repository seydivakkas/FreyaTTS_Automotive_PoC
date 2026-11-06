# Önerilen sade depo ağacı

```text
freya-automotive-agent/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/automotive_voice/
│   ├── core/                    # event schema, session state, cancellation
│   ├── domain/                  # otomotiv randevu policy, CRM tool interfaces
│   ├── text/                    # Türkçe normalization, lexicon, prosody
│   ├── media/                   # AudioFormat, resampling, playout queue
│   ├── ports/                   # STT, VAD, TTS, LLM, gateway protokolleri
│   ├── adapters/                # freya, whisper, fake, asterisk, CRM
│   ├── voiceops/                # A01-YT review, evidence, promotion
│   ├── api/                     # REST/WS endpoints
│   ├── security/                # permissions, PII masking, policies
│   └── telemetry/               # event logs / metrics
├── ui/                          # 3-panelli operatör ve lexicon review
├── contracts/                   # JSON schema + wire contracts
├── config/                      # dev, test, prod profile (secrets içermez)
├── data/fixtures/               # 320 golden örneğe referans
├── data/local/                  # Git dışı gerçek dosya (son aşama)
├── tests/                       # unit, contracts, integration mock, audio_final
├── docs/                        # master, ADR, backlog, acceptance
├── tools/                       # migration, manifest, mock CLI
├── infra/                       # Asterisk/WSL/Docker: ileriki faz
├── models/cache/                # checkpoint (Git dışı)
├── logs/                        # Git dışı çalışma zamanı
└── .github/workflows/           # isteğe bağlı Windows CI
```

`src/audio` ve `src/telephony/audio` gibi çift sahiplik yok; `media` codec/queue, `adapters/asterisk` PBX trafiği. `docs/` ve `tools/` yalnız bir kez bulunur. Geliştirmede ağır `infra/k8s/terraform/ansible` klasörleri ilk aşamada yaratılmaz.
