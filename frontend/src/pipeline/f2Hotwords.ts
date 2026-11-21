/**
 * FreyaTTS Automotive Cockpit V3 — F2 Automotive Hotword Booster & ASR Model Definitions
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface F2Hotword {
  id: string;
  wrong: string;
  canonical: string;
  weight: number;
  category: "Marka" | "Model" | "Şanzıman" | "Teşhis" | "DTC Kod" | "Plaka" | "Motor" | "Emisyon" | "Genel";
}

export interface F2AsrModel {
  id: string;
  name: string;
  wer: string;
  baseMs: number;
  beamDefault: number;
  desc: string;
}

export interface F2AppliedFix {
  from: string;
  to: string;
  weight: number;
  category: string;
}

export interface F2BoosterResult {
  raw: string;
  corrected: string;
  appliedFixes: F2AppliedFix[];
  confidenceGain: number;
}

export const INITIAL_F2_HOTWORDS: F2Hotword[] = [
  { id: 'hw1', wrong: 'pejo|pöjo|pežo|peugeot', canonical: 'Peugeot', weight: 4.5, category: 'Marka' },
  { id: 'hw2', wrong: 'kaşkay|kaşkai|kaskai', canonical: 'Qashqai', weight: 4.8, category: 'Model' },
  { id: 'hw3', wrong: 'de se ge|desege|d s g', canonical: 'DSG', weight: 4.2, category: 'Şanzıman' },
  { id: 'hw4', wrong: 'o be de|obd 2|obd iki|o b d', canonical: 'OBD-II', weight: 4.5, category: 'Teşhis' },
  { id: 'hw5', wrong: 'p 0 300|pe sıfır üç yüz|p0 300|p sıfır üç yüz', canonical: 'P0300', weight: 5.0, category: 'DTC Kod' },
  { id: 'hw6', wrong: 'p 0 171|pe sıfır yüz yetmiş bir', canonical: 'P0171', weight: 4.6, category: 'DTC Kod' },
  { id: 'hw7', wrong: 'altmış bir te se sıfır altmış bir|61 ts 61|61 t s 061', canonical: '61 TS 061', weight: 5.0, category: 'Plaka' },
  { id: 'hw8', wrong: 'blu haş de i|blue hdi|mavi hdi', canonical: 'BlueHDi', weight: 4.0, category: 'Motor' },
  { id: 'hw9', wrong: 'ti es ay|t s i', canonical: 'TSI', weight: 3.8, category: 'Motor' },
  { id: 'hw10', wrong: 'ed blu|ad blue|et blu', canonical: 'AdBlue', weight: 4.1, category: 'Emisyon' }
];

export const F2_ASR_MODELS: F2AsrModel[] = [
  {
    id: 'whisper_turbo',
    name: 'faster-whisper-large-v3-turbo (INT8 + F1 Hard Gate)',
    wer: '%2.8 WER',
    baseMs: 140,
    beamDefault: 2,
    desc: 'En yüksek Türkçe otomotiv doğruluğu, gürültülü atölye ve kabin ortamı için önerilen ana model.'
  },
  {
    id: 'distil_tr',
    name: 'distil-whisper-tr-automotive (FP16 Hızlı)',
    wer: '%4.4 WER',
    baseMs: 102,
    beamDefault: 1,
    desc: 'Düşük gecikme odaklı damıtılmış Türkçe model; hızlı randevu ve plaka yakalama için optimize.'
  },
  {
    id: 'conformer_8k',
    name: 'conformer-ctc-tr-8khz (SIP/ Dar Bant)',
    wer: '%5.9 WER',
    baseMs: 84,
    beamDefault: 3,
    desc: '8 kHz klasik PSTN/GSM hatları için ultra hafif CTC akustik model.'
  }
];

export function runF2DomainBooster(
  rawTranscript: string,
  hotwords: F2Hotword[] = INITIAL_F2_HOTWORDS,
  enabled: boolean = true,
  boostWeight: number = 4.0
): F2BoosterResult {
  if (!rawTranscript || !rawTranscript.trim()) {
    return { raw: '', corrected: '', appliedFixes: [], confidenceGain: 0 };
  }
  if (!enabled || boostWeight <= 0.5) {
    return { raw: rawTranscript, corrected: rawTranscript, appliedFixes: [], confidenceGain: 0 };
  }

  let corrected = rawTranscript;
  const appliedFixes: F2AppliedFix[] = [];

  hotwords.forEach((hw) => {
    const variants = hw.wrong.split('|').map((v) => v.trim()).filter(Boolean);
    variants.forEach((variant) => {
      const escaped = variant.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`\\b${escaped}\\b`, 'gi');
      if (regex.test(corrected)) {
        corrected = corrected.replace(regex, (match) => {
          if (match !== hw.canonical) {
            appliedFixes.push({
              from: match,
              to: hw.canonical,
              weight: Number(((hw.weight * boostWeight) / 4).toFixed(1)),
              category: hw.category
            });
          }
          return hw.canonical;
        });
      }
    });
  });

  const confidenceGain = appliedFixes.length > 0
    ? Number(Math.min(18.5, appliedFixes.length * (boostWeight * 1.15)).toFixed(1))
    : 0;

  return {
    raw: rawTranscript,
    corrected,
    appliedFixes,
    confidenceGain
  };
}

