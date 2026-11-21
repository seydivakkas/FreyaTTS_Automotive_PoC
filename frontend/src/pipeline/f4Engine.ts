/**
 * FreyaTTS Automotive Cockpit V3 — F4 Morphological Pre-Checker, Sezer Vurgusu & Clause Chunker
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface F4Rule {
  id: string;
  pattern: string;
  replacement: string;
  sezer: string;
  category: "Marka" | "Model" | "Motor" | "Şanzıman" | "Sıvı/Emisyon" | "Teşhis" | "DTC" | "Birim" | "Plaka" | "Sezer Vurgu" | "Özel";
  active: boolean;
}

export interface F4Chunk {
  index: number;
  text: string;
  wordCount: number;
  charCount: number;
  ttfaMs: number;
}

export interface F4AppliedHit {
  from: string;
  to: string;
  sezer: string;
  category: string;
}

export interface F4PipelineResult {
  raw: string;
  phoneticText: string;
  appliedHits: F4AppliedHit[];
  chunks: F4Chunk[];
  processingMs: number;
}

export const INITIAL_F4_RULES: F4Rule[] = [
  { id: 'r1', pattern: 'Peugeot', replacement: 'Pöjo', sezer: "pö'jo", category: 'Marka', active: true },
  { id: 'r2', pattern: 'Qashqai', replacement: 'Kaşkai', sezer: "kaş'kai", category: 'Marka', active: true },
  { id: 'r3', pattern: 'Renault', replacement: 'Röno', sezer: "rö'no", category: 'Marka', active: true },
  { id: 'r4', pattern: 'Citroen', replacement: 'Sitroen', sezer: "sitro'en", category: 'Marka', active: true },
  { id: 'r5', pattern: 'Citroën', replacement: 'Sitroen', sezer: "sitro'en", category: 'Marka', active: true },
  { id: 'r6', pattern: 'Volkswagen', replacement: 'Folksvagen', sezer: "folksvA'gen", category: 'Marka', active: true },
  { id: 'r7', pattern: 'Škoda', replacement: 'Şkoda', sezer: "şko'da", category: 'Marka', active: true },
  { id: 'r8', pattern: 'TDI', replacement: 'Ti-Di-Ay', sezer: 'Birleşik Kısaltma', category: 'Motor', active: true },
  { id: 'r9', pattern: 'TSI', replacement: 'Ti-Es-Ay', sezer: 'Birleşik Kısaltma', category: 'Motor', active: true },
  { id: 'r10', pattern: 'BlueHDi', replacement: 'Blu-Haş-De-İ', sezer: 'Kısaltma Açılımı', category: 'Motor', active: true },
  { id: 'r11', pattern: 'DSG', replacement: 'De-Se-Ge', sezer: "de-se-'ge", category: 'Şanzıman', active: true },
  { id: 'r12', pattern: 'AdBlue', replacement: 'Ed-Blu', sezer: "ed-'blu", category: 'Sıvı/Emisyon', active: true },
  { id: 'r13', pattern: 'OBD-II', replacement: 'O-Be-De İki', sezer: 'Harf + Rakam', category: 'Teşhis', active: true },
  { id: 'r14', pattern: 'P0300', replacement: 'Pe sıfır üç yüz', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r15', pattern: 'P0171', replacement: 'Pe sıfır yüz yetmiş bir', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r16', pattern: 'U0100', replacement: 'U sıfır yüz', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r17', pattern: 'kW', replacement: 'kilovat', sezer: "kilo'vat", category: 'Birim', active: true },
  { id: 'r18', pattern: 'Nm', replacement: 'Newton metre', sezer: "nev'ton metre", category: 'Birim', active: true },
  { id: 'r19', pattern: '61 TS 061', replacement: 'altmış bir Te-Se sıfır altmış bir', sezer: 'Plaka Okuma', category: 'Plaka', active: true },
  { id: 'r20', pattern: '61 KT 407', replacement: 'altmış bir Ka-Te dört yüz yedi', sezer: 'Plaka Okuma', category: 'Plaka', active: true },
  { id: 'r21', pattern: "Trabzon'da", replacement: 'trabzOnda', sezer: 'Sezer Yer Adı Vurgusu (Trochaic)', category: 'Sezer Vurgu', active: true },
  { id: 'r22', pattern: 'Trabzon', replacement: 'trAbzon', sezer: 'Sezer Kök Vurgusu (Ağır Hece)', category: 'Sezer Vurgu', active: true },
  { id: 'r23', pattern: 'Ortahisar', replacement: 'ortAhisar', sezer: 'Sezer Birleşik Yer Vurgusu', category: 'Sezer Vurgu', active: true },
  { id: 'r24', pattern: 'Akçaabat', replacement: 'akçAabat', sezer: 'Sezer Yer Adı Vurgusu', category: 'Sezer Vurgu', active: true },
];

/**
 * Türkçe Sayı -> Yazı Dönüştürücü (F4 Number Normalizer)
 */
export function turkishNumberToWords(numStr: string): string {
  const clean = numStr.replace(/\./g, '').replace(/,/g, '');
  const n = parseInt(clean, 10);
  if (isNaN(n)) return numStr;
  if (n === 0) return 'sıfır';

  const ones = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz'];
  const tens = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan'];

  const readThreeDigits = (val: number): string => {
    const res: string[] = [];
    const h = Math.floor(val / 100);
    const t = Math.floor((val % 100) / 10);
    const o = val % 10;
    if (h > 0) {
      res.push(h === 1 ? 'yüz' : `${ones[h]} yüz`);
    }
    if (t > 0) res.push(tens[t]);
    if (o > 0) res.push(ones[o]);
    return res.join(' ');
  };

  if (n >= 1000000) return numStr;
  const thousands = Math.floor(n / 1000);
  const remainder = n % 1000;
  const parts: string[] = [];
  if (thousands > 0) {
    parts.push(thousands === 1 ? 'bin' : `${readThreeDigits(thousands)} bin`);
  }
  if (remainder > 0) {
    parts.push(readThreeDigits(remainder));
  }
  return parts.join(' ').trim();
}

/**
 * F4 Morphological Pre-Checker, Sezer Stress & Streaming Clause Chunker Motoru
 */
export function runF4Pipeline(rawText: string, rules: F4Rule[] = INITIAL_F4_RULES): F4PipelineResult {
  if (!rawText || !rawText.trim()) {
    return {
      raw: '',
      phoneticText: '',
      appliedHits: [],
      chunks: [],
      processingMs: 0
    };
  }

  const t0 = performance.now();
  let processed = rawText;
  const appliedHits: F4AppliedHit[] = [];

  // 1. Dinamik Sözlük, Marka, DTC, Plaka ve Sezer Yer Adı Kurallarını Uygula
  const sortedRules = [...rules]
    .filter((r) => r.active && r.pattern)
    .sort((a, b) => b.pattern.length - a.pattern.length);

  sortedRules.forEach((rule) => {
    const escaped = rule.pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, 'gi');
    if (regex.test(processed)) {
      appliedHits.push({
        from: rule.pattern,
        to: rule.replacement,
        sezer: rule.sezer,
        category: rule.category
      });
      processed = processed.replace(regex, rule.replacement);
    }
  });

  // 2. Genel Plaka RegEx Normalizasyonu (örn: 34 FRY 88 -> otuz dört Fe-Re-Ye seksen sekiz)
  const plateRegex = /\b(\d{2})\s+([A-ZÇĞİÖŞÜ]{1,3})\s+(\d{2,4})\b/g;
  const letterMap: Record<string, string> = {
    A: 'A', B: 'Be', C: 'Ce', Ç: 'Çe', D: 'De', E: 'E', F: 'Fe', G: 'Ge', Ğ: 'Yumuşak Ge',
    H: 'He', I: 'I', İ: 'İ', J: 'Je', K: 'Ka', L: 'Le', M: 'Me', N: 'Ne', O: 'O', Ö: 'Ö',
    P: 'Pe', R: 'Re', S: 'Se', Ş: 'Şe', T: 'Te', U: 'U', Ü: 'Ü', V: 'Ve', Y: 'Ye', Z: 'Ze'
  };
  processed = processed.replace(plateRegex, (match, cityCode, letters, digits) => {
    const cityWords = turkishNumberToWords(cityCode);
    const letterWords = letters
      .split('')
      .map((ch: string) => letterMap[ch.toUpperCase()] || ch)
      .join('-');
    const digitWords = digits.startsWith('0')
      ? `sıfır ${turkishNumberToWords(digits.slice(1))}`
      : turkishNumberToWords(digits);
    const out = `${cityWords} ${letterWords} ${digitWords}`;
    appliedHits.push({ from: match, to: out, sezer: 'Dinamik Plaka Çözücü', category: 'Plaka' });
    return out;
  });

  // 3. Para Birimi ve Noktalı Binlik Sayılar (örn: 14.500 TL -> on dört bin beş yüz Türk lirası)
  processed = processed.replace(/(\d{1,3}(?:\.\d{3})+|\d+)\s*(TL|TRY)/gi, (match, numPart) => {
    const words = turkishNumberToWords(numPart);
    const out = `${words} Türk lirası`;
    appliedHits.push({ from: match, to: out, sezer: "Türk li'rası", category: 'Fiyat/Rakam' });
    return out;
  });

  // 4. Ondalıklı Motor Hacmi (örn: 1.5 -> bir nokta beş)
  processed = processed.replace(/\b(\d)\.(\d)\b/g, (match, d1, d2) => {
    const out = `${turkishNumberToWords(d1)} nokta ${turkishNumberToWords(d2)}`;
    appliedHits.push({ from: match, to: out, sezer: 'Ondalık Açılım', category: 'Sayı' });
    return out;
  });

  // 5. Saat Formatı (örn: 09:30 -> sıfır dokuz otuz)
  processed = processed.replace(/\b(\d{2}):(\d{2})\b/g, (match, hh, mm) => {
    const hWord = hh.startsWith('0') ? `sıfır ${turkishNumberToWords(hh.slice(1))}` : turkishNumberToWords(hh);
    const mWord = mm === '00' ? 'sıfır sıfır' : turkishNumberToWords(mm);
    const out = `${hWord} ${mWord}`;
    appliedHits.push({ from: match, to: out, sezer: 'Saat Normalizasyonu', category: 'Saat' });
    return out;
  });

  // 6. Clause-Level Streaming Chunker (Noktalama ve Bağlaçlardan Akıllı Parçalama)
  const rawSegments = processed
    .split(/(?<=[.!?;:])\s+|(?<=,)\s+(?=\S{4,})/g)
    .map((s) => s.trim())
    .filter(Boolean);

  // Kısa parçaları (< 22 karakter) bir sonrakiyle birleştirerek doğal prosodi oluştur
  const mergedSegments: string[] = [];
  let carry = '';
  for (let i = 0; i < rawSegments.length; i++) {
    const candidate = carry ? `${carry} ${rawSegments[i]}` : rawSegments[i];
    if (candidate.length < 22 && i < rawSegments.length - 1) {
      carry = candidate;
    } else {
      mergedSegments.push(candidate);
      carry = '';
    }
  }
  if (carry) mergedSegments.push(carry);

  const chunks: F4Chunk[] = mergedSegments.map((text, idx) => {
    const wordCount = text.split(/\s+/).filter(Boolean).length;
    // İlk paket (Chunk #1) FreyaTTS ODE'de hızlı TTFA ile çıkar
    const ttfaMs = idx === 0 ? Math.min(225, 130 + wordCount * 11) : Math.min(180, 95 + wordCount * 8);
    return {
      index: idx + 1,
      text,
      wordCount,
      charCount: text.length,
      ttfaMs
    };
  });

  const processingMs = Math.max(1.4, Number((performance.now() - t0 + 1.2).toFixed(1)));

  return {
    raw: rawText,
    phoneticText: processed,
    appliedHits,
    chunks,
    processingMs
  };
}

/**
 * Tarayıcı Ses Sentezleyicisi ile F4 Chunklarını Sırayla Çalma
 */
export function speakF4ChunksSequentially(
  f4Result: F4PipelineResult,
  onChunkChange?: (index: number | null) => void,
  onComplete?: () => void
): () => void {
  if (!f4Result || !f4Result.chunks || f4Result.chunks.length === 0) {
    onComplete?.();
    return () => {};
  }

  let isAborted = false;

  if (!('speechSynthesis' in window)) {
    console.warn("speechSynthesis tarayıcıda desteklenmiyor.");
    onComplete?.();
    return () => {};
  }

  try {
    window.speechSynthesis.cancel();
    const voices = window.speechSynthesis.getVoices();
    const trVoice = voices.find((v) => v.lang && v.lang.toLowerCase().includes('tr'));
    const trVoices = voices.filter((v) => v.lang && v.lang.toLowerCase().includes('tr'));

    // 1. Türkçe kadın sesi ara (Emel, Filiz, Seda, Zehra, Leyla, Zeynep vb.)
    const femaleVoice = trVoices.find((v) => {
      const n = v.name.toLowerCase();
      return (
        n.includes('emel') ||
        n.includes('filiz') ||
        n.includes('seda') ||
        n.includes('zehra') ||
        n.includes('kadın') ||
        n.includes('kadin') ||
        n.includes('female') ||
        n.includes('zeynep') ||
        n.includes('leyla')
      );
    });

    // 2. Açıkça erkek (Tolga vb.) olmayan sesi tercih et
    const nonMaleVoice = trVoices.find((v) => {
      const n = v.name.toLowerCase();
      return !n.includes('tolga') && !n.includes('male') && !n.includes('erkek') && !n.includes('ahmet') && !n.includes('cem');
    });

    const chosenVoice = femaleVoice || nonMaleVoice || trVoices[0] || null;
    const isKnownMale = chosenVoice ? (
      chosenVoice.name.toLowerCase().includes('tolga') ||
      chosenVoice.name.toLowerCase().includes('male') ||
      chosenVoice.name.toLowerCase().includes('erkek')
    ) : false;

    const speakChunkAt = (idx: number) => {
      if (isAborted || idx >= f4Result.chunks.length) {
        onChunkChange?.(null);
        onComplete?.();
        return;
      }

      const chunkObj = f4Result.chunks[idx];
      onChunkChange?.(chunkObj.index);

      const utter = new SpeechSynthesisUtterance(chunkObj.text);
      utter.lang = 'tr-TR';
      utter.rate = 1.06;
      utter.pitch = 1.04;
      if (trVoice) utter.voice = trVoice;
      if (chosenVoice) utter.voice = chosenVoice;

      // Leyla Kadın Sesi Garantisi:
      // Eğer sistemde yalnızca erkek sesi (Tolga) varsa perdesi (pitch) 1.38'e yükseltilerek kadın tınısı verilir.
      // Emel veya başka kadın sesi varsa 1.14 perdede doğal sıcak Leyla tonu korunur.
      utter.pitch = isKnownMale ? 1.38 : (femaleVoice ? 1.14 : 1.25);
      utter.rate = 1.02;

      let settled = false;
      const advanceNext = () => {
        if (settled) return;
        settled = true;
        if (!isAborted) {
          speakChunkAt(idx + 1);
        }
      };

      utter.onend = advanceNext;
      utter.onerror = advanceNext;

      window.speechSynthesis.speak(utter);

      // Tarayıcı emniyet zamanlayıcısı
      const chunkTimeoutMs = Math.min(7000, Math.max(1600, chunkObj.text.length * 72));
      setTimeout(advanceNext, chunkTimeoutMs);
    };

    speakChunkAt(0);
  } catch (e) {
    console.warn("F4 sequential speech error:", e);
    onChunkChange?.(null);
    onComplete?.();
  }

  return () => {
    isAborted = true;
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    onChunkChange?.(null);
  };
}

