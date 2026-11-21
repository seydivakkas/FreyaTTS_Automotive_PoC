# Brag Plan: FreyaTTS Automotive Cockpit

<!--
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
-->

## What is this app?
FreyaTTS Automotive Cockpit is Türkiye's first fully on-premise, voice-native automotive AI telephony & service assistant—featuring an ultra-fast F0–F6 neural DSP pipeline, Whisper ASR, Qwen2.5 LLM, and local CUDA-powered Leyla ODE speech synthesis with zero cloud audio dependency.

## The angle
High-performance automotive engineering meets real-time conversational AI: a 214ms time-to-first-audio latency, 280+ automotive phonetic lexicon mappings, and deterministic safety locks (M01–M11) running completely on edge hardware inside car dealerships and inspection centers.

## Hook (first 2-3 seconds)
An oscilloscope audio wave bursts to life against a deep slate dashboard: 
"Sesli yapay zekâ, otomotiv hızında."
Immediately cutting to a pulsing real-time latency readout: **TTFA: 214 ms**.

## Key moments (the middle)
- **Live Cockpit In Action:** SIP call connects (`SIP/6001`), customer requests periyodik bakım for a Peugeot 3008, and assistant Leyla responds fluently with Lift-2 appointment scheduling.
- **F0–F6 Neural Pipeline Telemetry:** Visual breakdown of the real-time pipeline—F0 DSP (+14.8dB SNR) → F2 Whisper (138ms) → F3 Qwen2.5 (176ms) → F4 Sezer (4ms) → F5 FreyaTTS ODE (194ms).
- **Deterministic Action & Safety:** Live JSON slot extraction locking in vehicle details, repair steps (`60k_periyodik`, `dsg_yag`), and price guarantee (`14.500 TRY M01 KİLİTLİ`).

## Outro / punchline
"Bulut yok. Gecikme yok. Sadece yerel yapay zekâ."
Logo resolves with "FreyaTTS Automotive Cockpit • Telif Hakkı (c) 2026 Seydi Eryılmaz".

## User flow worth showing
1. **Entry:** Müşteri çağrısı bağlanır (`SIP/6001 • Bağlandı`).
2. **Key Action:** Müşteri "Trabzon'da 61 TS 061 plakalı Peugeot 3008 aracım için periyodik bakım randevusu almak istiyorum" der; ses dalgası canlı akar ve F2-F5 anında tetiklenir.
3. **Result:** Asistan Leyla 214ms içinde randevuyu onaylar; ekranda Lift-2 istasyonu ve arıza kodları deterministik JSON olarak dökülür.

## Tone
- **Preset:** `polished`
- **Creative direction:** Sleek next-gen automotive AI cockpit reveal
- **Interpretation:** High precision, crisp technical typography, dark dashboard contrast, clean transitions timed to beats, zero generic fluff.

## Format: landscape — 1920x1080
## Duration: 20 seconds (30 fps = 600 frames)

## Visual identity (from the project)
- **Background:** `#090d16` (Deep Obsidian / Cockpit Dark)
- **Card Background:** `#0f172a` (Slate 900 with glass borders)
- **Accent Emerald:** `#10b981` (Online status & voice waveform)
- **Accent Cyan/Blue:** `#38bdf8` (Latency indicators & tech tags)
- **Accent Amber:** `#fbbf24` (Telemetry TTFA badge)
- **Text:** `#f8fafc` (Slate 50) & `#94a3b8` (Muted Slate)
- **Display font:** `Inter, system-ui, sans-serif`
- **Body font:** `JetBrains Mono, Menlo, monospace` for telemetry
- **Strongest visual element:** The live waveform equalizer, latency badge pills, and streaming message cards.

## Share copy (draft)
Otomotiv servisleri için geliştirdiğimiz yeni nesil yerel sesli yapay zekâ kokpiti FreyaTTS: 214ms ilk ses yanıtı, F0–F6 sinyal hattı ve sıfır bulut bağımlılığı. 🚗🎙️⚡

## Audio direction
- **Role:** Polished modern electronic tech bed with crisp transient kicks and subtle ambient sub-bass.
- **Music:** `happy-beats-business-moves-vol-1-by-ende-dot-app.mp3`
- **Music treatment:** Starts at 0s with clean beat entry; steady groove through middle scenes; gentle ducking during key reveals; clean resolution on final logo.
- **Music cue guidance:** Strong downbeats every ~2.0s; transitions cut precisely on beat drops.
- **Audio-reactive treatment:** Subtle border glow and equalizer bar height modulation aligned to the music energy.
- **SFX posture:** Subtle high-tech interface chimes, soft clicks for incoming dialogue bubbles, and a clean digital hit on the 214ms latency reveal.
- **Restraint rule:** No harsh whooshes or loud generic sweeps. Audio must feel like an in-cockpit luxury automotive system.

## Storyboard

### Scene 1 — The Hook (0.0s – 3.0s, duration: 3.0s)
- **Visuals:** Dark luxury automotive cockpit backdrop. Bold typography zooms in: "SESLİ YAPAY ZEKÂ. OTOMOTİV HIZINDA."
- **Centerpiece:** Pulsing audio waveform and glowing telemetry pill: `TTFA: 214 ms (CANLI)`.
- **Sequential:** Words hit on 0.4s, waveform activates on 1.0s, TTFA badge locks in at 1.8s.
- **Transition:** Quick camera wipe right to live cockpit.

### Scene 2 — Live Call Cockpit (3.0s – 9.0s, duration: 6.0s)
- **Visuals:** The full FreyaTTS Görüşme Kokpiti UI. Top bar with `[Görüşmeyi Bitir] SIP/6001 • 01:42`, live equalizer canvas.
- **Dialog Flow:**
  - Leyla (FreyaTTS): "Merhaba, Trabzon Otomotiv Yetkili Servisi'ne hoş geldiniz..."
  - Müşteri: "61 TS 061 plakalı Peugeot 3008 için periyodik bakım randevusu..."
  - Leyla: "Yarın saat 09:30 Lift-2 istasyonumuz uygundur. Onaylıyor musunuz?"
- **Right Panel:** Müşteri Profili & Otomatik Randevu Kartı (Ahmet Yılmaz, Lift-2, 14.500 TRY).
- **Sequential:** Customer bubble lands on 4.0s, Leyla bubble answers on 6.2s with `F3: 176ms | F5: 194ms`.
- **Transition:** Smooth slide into telemetry breakdown.

### Scene 3 — F0–F6 Neural Pipeline (9.0s – 15.0s, duration: 6.0s)
- **Visuals:** 5-stage architectural pipeline cards glowing sequentially from left to right:
  - `F0 Araç İçi DSP (+14.8dB SNR)`
  - `F2 Whisper ASR (138ms)`
  - `F3 Qwen2.5 LLM Niyet (176ms)`
  - `F4 Sezer Normalizasyon (4ms)`
  - `F5 FreyaTTS ODE Leyla (194ms)`
- **Highlight:** Real-time benchmark comparison showing "E2E: 214 ms vs Bulut: 1.800 ms (8.4x Daha Hızlı)".
- **Transition:** Focus snap to outro.

### Scene 4 — Punchline & Outro (15.0s – 20.0s, duration: 5.0s)
- **Visuals:** Center stage lockup:
  - Big headline: "Bulut Yok. Gecikme Yok. %100 Yerel."
  - Logo: `freya v3 • OTOMOTİV KOKPİTİ`
  - Subtitle: "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)"
  - URL / Repo indicator: `FreyaTTS_Automotive_PoC`
- **Audio:** Music resolves with warm sustained chord and soft sparkle.
