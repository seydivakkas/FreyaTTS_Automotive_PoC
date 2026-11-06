"""Conservative Turkish TTS normalizer (no audio, no guessed pronunciation).

Spoken output is separate from display text. No unreviewed lexicon candidate
can replace a brand. Ambiguous or invalid numeric tokens remain visible and
are flagged, not silently coerced.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import json
import re
import unicodedata
from .lexicon import AutomotiveLexicon

ONES = ('', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz')
TENS = ('', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan')
SCALES = ('', 'bin', 'milyon', 'milyar', 'trilyon')
MONTHS = ('', 'ocak', 'şubat', 'mart', 'nisan', 'mayıs', 'haziran',
          'temmuz', 'ağustos', 'eylül', 'ekim', 'kasım', 'aralık')
# All boundaries explicitly exclude partial alphanumeric model, VIN or telephone matches.
PRICE = re.compile(r'(?<![\w.,])(?P<val>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?P<currency>TL|TRY|₺|Türk\s+lirası)(?!\w)', re.I)
DATE_ISO = re.compile(r'(?<![\w\d])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\w\d])')
DATE_TR = re.compile(r'(?<![\w\d])(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})(?![\w\d])')
CLOCK = re.compile(r"(?<![\w\d])(?P<h>\d{1,2}):(?P<m>\d{2})(?P<suffix>['’](?:da|de|ta|te|a|e))?(?![\w\d])", re.I)
ENGINE = re.compile(r'(?<!\w)(?P<major>\d)[,.](?P<minor>\d)\s*(?P<unit>TSI|TDI|TFSI|TCe|dCi|CDI|HDI)(?!\w)', re.I)
KM = re.compile(r'(?<![\w\d])(?P<val>\d{1,3}(?:\.\d{3})+|\d+)\s*(?:km|kilometre)(?!\w)', re.I)
YEAR_MODEL = re.compile(r'(?<!\w)(?P<year>(?:19|20)\d{2})\s+model(?!\w)', re.I)
INVALID_DATELIKE = re.compile(r'(?<!\w)\d{1,2}/\d{1,2}/\d{4}(?!\w)')
DANGLING_DECIMAL = re.compile(r'(?<!\w)\d+(?:,\d{3,}|\.\d{1,2})(?![\d\w])')
# Standalone integers only. Do not rewrite identifiers, ranges, phone numbers,
# dates or units. Freya native may handle remaining forms later.
SINGLE_INTEGER = re.compile(r'(?<![\w\d.,:/+-])(?P<num>\d{1,15})(?![\w\d.,:/+-])')
WEIRD_CONTROL = {'\u200b', '\u200c', '\u200d', '\u202a', '\u202b', '\u202d', '\u202e', '\u2066', '\u2067', '\u2068', '\u2069'}


def int_to_tr(value: int) -> str:
    if type(value) is not int or not 0 <= value < 10**15:
        raise ValueError('number out of supported range')
    if value == 0:
        return 'sıfır'
    groups = []
    while value:
        groups.append(value % 1000)
        value //= 1000
    output = []
    for index in reversed(range(len(groups))):
        n = groups[index]
        if not n:
            continue
        words = []
        h, tens, unit = n // 100, n % 100 // 10, n % 10
        if h:
            if h > 1:
                words.append(ONES[h])
            words.append('yüz')
        if tens:
            words.append(TENS[tens])
        if unit:
            words.append(ONES[unit])
        if index == 1 and n == 1:
            words.clear()
        output.extend(words)
        if index:
            output.append(SCALES[index])
    return ' '.join(output)


def clock_locative(spoken: str) -> str:
    ending = spoken[-1]
    vowel = next((c for c in reversed(spoken) if c in 'aeıioöuü'), 'a')
    return ('t' if ending in 'fstkçşhp' else 'd') + ('a' if vowel in 'aıou' else 'e')


def clock_dative(spoken: str) -> str:
    ending = spoken[-1]
    vowel = next((c for c in reversed(spoken) if c in 'aeıioöuü'), 'a')
    return ('y' if ending in 'aeıioöuü' else '') + ('a' if vowel in 'aıou' else 'e')


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    display_text: str
    spoken_text: str
    rules_applied: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_chars: tuple[str, ...]
    review_required: bool
    # Do not send display_text/spoken_text to telemetry or event envelopes.

    def as_dict(self) -> dict:
        return {'display_text': self.display_text, 'spoken_text': self.spoken_text,
                'rules_applied': list(self.rules_applied), 'warnings': list(self.warnings),
                'unsupported_chars': list(self.unsupported_chars), 'review_required': self.review_required}


class TurkishAutomotiveNormalizer:
    def __init__(self, lexicon: AutomotiveLexicon | None = None, vocab_path: str | Path | None = None):
        self.lexicon = lexicon or AutomotiveLexicon()
        self.vocab = set(json.loads(Path(vocab_path).read_text(encoding='utf-8'))) if vocab_path else None

    def normalize(self, text: str, *, strict: bool = False) -> NormalizationResult:
        if not isinstance(text, str) or not text.strip():
            raise ValueError('nonempty text required')
        if len(text) > 5000:
            raise ValueError('text too long')
        display = unicodedata.normalize('NFC', text)
        warnings: list[str] = []
        rules: list[str] = []
        if any(c in WEIRD_CONTROL or (unicodedata.category(c) == 'Cc' and c not in '\n\t') for c in display):
            warnings.append('unsafe_control_characters')
        spoken = display

        def substitute(pattern, name, fn):
            nonlocal spoken
            def wrap(match):
                replacement = fn(match)
                if replacement != match.group():
                    rules.append(name)
                return replacement
            spoken = pattern.sub(wrap, spoken)

        def read_date(m):
            try:
                d = date(int(m['y']), int(m['m']), int(m['d']))
            except ValueError:
                warnings.append('invalid_date')
                return m.group()
            return f'{int_to_tr(d.day)} {MONTHS[d.month]} {int_to_tr(d.year)}'
        substitute(DATE_ISO, 'date_iso', read_date)
        substitute(DATE_TR, 'date_tr', read_date)
        if INVALID_DATELIKE.search(spoken):
            warnings.append('ambiguous_date_separator')

        def read_price(m):
            raw = m['val']
            integer, _, decimal = raw.partition(',')
            try:
                amount = int(integer.replace('.', ''))
                whole = int_to_tr(amount)
            except ValueError:
                warnings.append('price_out_of_range')
                return m.group()
            result = whole + ' Türk lirası'
            if decimal and int(decimal):
                result += ' ve ' + int_to_tr(int(decimal.ljust(2, '0'))) + ' kuruş'
            return result
        substitute(PRICE, 'currency', read_price)

        def read_clock(m):
            hour, minute = int(m['h']), int(m['m'])
            if hour > 23 or minute > 59:
                warnings.append('invalid_time')
                return m.group()
            spoken_clock = int_to_tr(hour) + (' ' + int_to_tr(minute) if minute else '')
            if m['suffix']:
                suffix = m['suffix'].lstrip("'’").lower()
                spoken_clock += clock_locative(spoken_clock) if suffix in ('da', 'de', 'ta', 'te') else clock_dative(spoken_clock)
            return spoken_clock
        substitute(CLOCK, 'clock', read_clock)

        def read_engine(m):
            return f"{int_to_tr(int(m['major']))} nokta {int_to_tr(int(m['minor']))} {m['unit']}"
        substitute(ENGINE, 'engine', read_engine)
        def read_km(m):
            try:
                return int_to_tr(int(m['val'].replace('.', ''))) + ' kilometre'
            except ValueError:
                warnings.append('distance_out_of_range')
                return m.group()
        substitute(KM, 'distance', read_km)
        substitute(YEAR_MODEL, 'model_year', lambda m: int_to_tr(int(m['year'])) + ' model')

        lex = self.lexicon.apply(spoken)
        spoken = lex.text
        if lex.hits:
            rules.extend('lexicon:' + term for term in lex.hits)
        warnings.extend(lex.review_required)

        # Only safe presentation punctuation. Never transliterate names here.
        spoken = spoken.replace('!', '.').replace('…', ',').replace('—', ',').replace('–', '-')
        spoken = re.sub(r'\s+', ' ', spoken).strip()
        if DANGLING_DECIMAL.search(spoken):
            warnings.append('ambiguous_numeric_notation')
        if any(c.isdigit() for c in spoken):
            warnings.append('unexpanded_numeric_token')
        unsupported = tuple(sorted(set(ch for ch in spoken if ch not in self.vocab))) if self.vocab is not None else ()
        if unsupported:
            warnings.append('unsupported_freya_characters')
        warnings = list(dict.fromkeys(warnings))
        review = bool(warnings)
        if strict and review:
            raise ValueError('normalization requires review: ' + ','.join(warnings))
        return NormalizationResult(display, spoken, tuple(rules), tuple(warnings), unsupported, review)
