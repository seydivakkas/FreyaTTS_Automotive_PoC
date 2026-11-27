"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.morphology.syllabifier import BACK_VOWELS, VOWELS, TurkishSyllabifier
from backend.shared_lexicon.contracts import (
    AliasEntry,
    CanonicalEntity,
    EntityCategory,
    LexiconSnapshot,
    PronunciationVariant,
    TechnicalTerm,
    make_safe_id,
)
from backend.shared_lexicon.unicode_normalizer import normalize_matching_key

DEFAULT_COMPILED_LEXICON_PATH = Path("config/freyatts_automotive_lexicon.json")
DEFAULT_FOREIGN_LEXICON_PATH = Path("config/automotive_foreign_lexicon.json")
DEFAULT_VOCAB_PATH = Path("config/freya_vocab.json")


def load_vocab_chars(vocab_path: Path | str | None = DEFAULT_VOCAB_PATH) -> frozenset[str]:
    """Loads FreyaTTS vocabulary character set read-only without mutating files."""
    if vocab_path is not None:
        p = Path(vocab_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, Mapping):
                return frozenset(str(k) for k in data.keys())
    return frozenset()


def _is_vocab_valid(spoken_text: str, vocab_chars: frozenset[str]) -> bool:
    if not vocab_chars:
        return False
    check = spoken_text.replace("Ğ", "ğ")
    return len(set(check) - vocab_chars) == 0


def _build_pronunciation(
    *,
    canonical_entity_id: str,
    surface_key: str,
    spoken_text: str,
    profile: str,
    vocab_chars: frozenset[str],
    priority: int,
    phonetic_syllables: Sequence[str] = (),
    stress_syllable_idx: int | None = None,
    ends_with_consonant: bool | None = None,
    last_vowel_backness: str | None = None,
) -> PronunciationVariant:
    cleaned_spoken = spoken_text.strip()
    syllables = tuple(str(s) for s in phonetic_syllables if str(s))
    if not syllables:
        compact = normalize_matching_key(cleaned_spoken).replace(" ", "")
        if compact:
            syllables = tuple(TurkishSyllabifier.syllabify(compact) or [compact])
    if stress_syllable_idx is None and syllables:
        stress_syllable_idx = max(0, len(syllables) - 1)
    if ends_with_consonant is None and syllables:
        last_char = syllables[-1][-1]
        ends_with_consonant = last_char not in VOWELS
    if last_vowel_backness is None and syllables:
        joined = "".join(syllables)
        last_vowel = next((ch for ch in reversed(joined) if ch in VOWELS), "e")
        last_vowel_backness = "back" if last_vowel in BACK_VOWELS else "front"

    vid = make_safe_id("pron", f"{canonical_entity_id}:{profile}:{surface_key}")
    return PronunciationVariant(
        variant_id=vid,
        canonical_entity_id=canonical_entity_id,
        surface_key=surface_key,
        spoken_text=cleaned_spoken,
        profile=profile,
        phonetic_syllables=syllables,
        stress_syllable_idx=stress_syllable_idx,
        ends_with_consonant=ends_with_consonant,
        last_vowel_backness=last_vowel_backness,
        vocab_validated=_is_vocab_valid(cleaned_spoken, vocab_chars),
        priority=priority,
    )


def load_lexicon_snapshot(
    *,
    compiled_lexicon_path: Path | str | None = DEFAULT_COMPILED_LEXICON_PATH,
    foreign_lexicon_path: Path | str | None = DEFAULT_FOREIGN_LEXICON_PATH,
    vocab_path: Path | str | None = DEFAULT_VOCAB_PATH,
    include_python_rules: bool = True,
    extra_entities: Sequence[CanonicalEntity] = (),
    extra_aliases: Sequence[AliasEntry] = (),
    extra_pronunciations: Sequence[PronunciationVariant] = (),
    extra_technical_terms: Sequence[TechnicalTerm] = (),
) -> LexiconSnapshot:
    """Reads compiled lexicon JSON and Python rule modules read-only into an immutable LexiconSnapshot."""
    vocab_chars = load_vocab_chars(vocab_path)

    entities_by_id: dict[str, CanonicalEntity] = {}
    alias_acc: dict[tuple[str, str], AliasEntry] = {}
    prons_by_id: dict[str, PronunciationVariant] = {}
    terms_by_id: dict[str, TechnicalTerm] = {}
    source_version = "2026.1"
    meta_summary: dict[str, Any] = {}

    def _find_existing_entity(canonical_name: str, preferred_prefix: str) -> CanonicalEntity | None:
        norm_key = normalize_matching_key(canonical_name)
        preferred_id = make_safe_id(preferred_prefix, norm_key)
        if preferred_id in entities_by_id:
            return entities_by_id[preferred_id]
        for candidate_prefix in ("brand", "model", "tech", "dtc"):
            cid = make_safe_id(candidate_prefix, norm_key)
            if cid in entities_by_id:
                return entities_by_id[cid]
        return None

    def _register_entity(
        *,
        prefix: str,
        canonical_name: str,
        category: EntityCategory,
        brand_name: str | None = None,
        model_name: str | None = None,
        aliases: Sequence[str] = (),
        priority: int = 30,
        metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalEntity:
        norm_key = normalize_matching_key(canonical_name)
        existing = _find_existing_entity(canonical_name, prefix)
        eid = existing.entity_id if existing is not None else make_safe_id(prefix, norm_key)
        merged_aliases = tuple(dict.fromkeys((*(existing.aliases if existing else ()), *(a.strip() for a in aliases if a and a.strip()))))
        if existing is not None:
            merged_meta = {**dict(existing.metadata), **dict(metadata or {})}
            ent = CanonicalEntity(
                entity_id=eid,
                canonical_name=existing.canonical_name,
                category=existing.category,
                normalized_key=existing.normalized_key,
                brand_name=existing.brand_name or brand_name,
                model_name=existing.model_name or model_name,
                aliases=merged_aliases,
                priority=min(existing.priority, priority),
                metadata=merged_meta,
            )
        else:
            ent = CanonicalEntity(
                entity_id=eid,
                canonical_name=canonical_name.strip(),
                category=category,
                normalized_key=norm_key,
                brand_name=brand_name,
                model_name=model_name,
                aliases=merged_aliases,
                priority=priority,
                metadata=dict(metadata or {}),
            )
        entities_by_id[eid] = ent
        return ent

    def _register_alias(
        *,
        alias_text: str,
        entity: CanonicalEntity,
        priority: int,
        source: str,
    ) -> None:
        clean_alias = alias_text.strip()
        if not clean_alias:
            return
        norm_key = normalize_matching_key(clean_alias)
        if not norm_key:
            return
        aid = make_safe_id("alias", f"{norm_key}->{entity.entity_id}")
        dedup_key = (norm_key, entity.entity_id)
        existing = alias_acc.get(dedup_key)
        if existing is None or priority < existing.priority:
            alias_acc[dedup_key] = AliasEntry(
                alias_id=aid,
                alias_text=clean_alias,
                normalized_key=norm_key,
                canonical_entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                category=entity.category,
                priority=priority,
                source=source,
            )

    def _register_pron(pron: PronunciationVariant) -> None:
        existing = prons_by_id.get(pron.variant_id)
        if existing is None or pron.priority < existing.priority:
            prons_by_id[pron.variant_id] = pron

    # 1. Read compiled lexicon JSON read-only
    if compiled_lexicon_path is not None:
        cp = Path(compiled_lexicon_path)
        if cp.exists():
            data = json.loads(cp.read_text(encoding="utf-8"))
            meta = data.get("metadata") or {}
            source_version = str(meta.get("version") or source_version)
            meta_summary["compiled_version"] = source_version
            meta_summary["engine"] = str(meta.get("engine") or "FreyaTTS")

            # Brands
            for item in data.get("brands", []):
                canon = (item.get("canonical") or item.get("source") or "").strip()
                if not canon:
                    continue
                priority = int(item.get("priority", 30))
                raw_aliases = list(item.get("asr_variants") or []) + list(item.get("aliases") or [])
                ent = _register_entity(
                    prefix="brand",
                    canonical_name=canon,
                    category=EntityCategory.BRAND,
                    brand_name=canon,
                    aliases=raw_aliases,
                    priority=priority,
                    metadata={"origin": str(item.get("origin") or "compiled")},
                )
                for a in raw_aliases:
                    _register_alias(alias_text=a, entity=ent, priority=priority, source="compiled:brands")
                for profile_key in ("tts_2026", "tts_sezer", "spoken"):
                    spk = (item.get(profile_key) or "").strip()
                    if spk:
                        _register_pron(
                            _build_pronunciation(
                                canonical_entity_id=ent.entity_id,
                                surface_key=ent.normalized_key,
                                spoken_text=spk,
                                profile=profile_key,
                                vocab_chars=vocab_chars,
                                priority=priority,
                            )
                        )

            # Full models
            for item in data.get("full_models", []):
                canon = (item.get("canonical") or item.get("source") or "").strip()
                if not canon:
                    continue
                priority = int(item.get("priority", 10))
                brand = (item.get("brand") or "").strip() or None
                model = (item.get("model") or "").strip() or None
                ent = _register_entity(
                    prefix="model",
                    canonical_name=canon,
                    category=EntityCategory.MODEL,
                    brand_name=brand,
                    model_name=model,
                    priority=priority,
                    metadata={"origin": str(item.get("origin") or "compiled")},
                )
                for profile_key in ("tts_2026", "tts_sezer", "spoken"):
                    spk = (item.get(profile_key) or "").strip()
                    if spk:
                        _register_pron(
                            _build_pronunciation(
                                canonical_entity_id=ent.entity_id,
                                surface_key=ent.normalized_key,
                                spoken_text=spk,
                                profile=profile_key,
                                vocab_chars=vocab_chars,
                                priority=priority,
                            )
                        )

            # Standalone models (including genuine multi-brand ambiguity!)
            for item in data.get("standalone_models", []):
                model_name = (item.get("model") or item.get("source") or "").strip()
                if not model_name:
                    continue
                priority = int(item.get("priority", 20))
                raw_brands = list(item.get("by_brand") or [])
                if not raw_brands and item.get("brand"):
                    raw_brands = [item["brand"]]
                # Deduplicate brand names differing only by case (e.g., CUPRA vs Cupra)
                dedup_brands: list[str] = []
                seen_brand_keys: set[str] = set()
                for b in raw_brands:
                    b_clean = str(b).strip()
                    bk = normalize_matching_key(b_clean)
                    if bk and bk not in seen_brand_keys:
                        seen_brand_keys.add(bk)
                        dedup_brands.append(b_clean)

                if len(dedup_brands) > 1:
                    # Link standalone model alias to EVERY distinct brand-model entity so ambiguity is preserved
                    for brand_name in dedup_brands:
                        full_name = f"{brand_name} {model_name}"
                        ent = _register_entity(
                            prefix="model",
                            canonical_name=full_name,
                            category=EntityCategory.MODEL,
                            brand_name=brand_name,
                            model_name=model_name,
                            aliases=(model_name,),
                            priority=priority,
                            metadata={"origin": str(item.get("origin") or "compiled_standalone")},
                        )
                        _register_alias(
                            alias_text=model_name,
                            entity=ent,
                            priority=priority,
                            source="compiled:standalone_multi",
                        )
                        for profile_key in ("tts_2026", "tts_sezer", "spoken"):
                            spk = (item.get(profile_key) or "").strip()
                            if spk:
                                _register_pron(
                                    _build_pronunciation(
                                        canonical_entity_id=ent.entity_id,
                                        surface_key=normalize_matching_key(model_name),
                                        spoken_text=spk,
                                        profile=profile_key,
                                        vocab_chars=vocab_chars,
                                        priority=priority,
                                    )
                                )
                else:
                    brand_name = dedup_brands[0] if dedup_brands else None
                    canon_name = f"{brand_name} {model_name}" if brand_name else model_name
                    ent = _register_entity(
                        prefix="model",
                        canonical_name=canon_name,
                        category=EntityCategory.MODEL,
                        brand_name=brand_name,
                        model_name=model_name,
                        aliases=(model_name,),
                        priority=priority,
                        metadata={"origin": str(item.get("origin") or "compiled_standalone")},
                    )
                    if normalize_matching_key(model_name) != ent.normalized_key:
                        _register_alias(
                            alias_text=model_name,
                            entity=ent,
                            priority=priority,
                            source="compiled:standalone",
                        )
                    for profile_key in ("tts_2026", "tts_sezer", "spoken"):
                        spk = (item.get(profile_key) or "").strip()
                        if spk:
                            _register_pron(
                                _build_pronunciation(
                                    canonical_entity_id=ent.entity_id,
                                    surface_key=normalize_matching_key(model_name),
                                    spoken_text=spk,
                                    profile=profile_key,
                                    vocab_chars=vocab_chars,
                                    priority=priority,
                                )
                            )

            # ASR mappings
            for item in data.get("asr_mappings", []):
                var = (item.get("variant") or "").strip()
                canon = (item.get("canonical") or "").strip()
                if not var or not canon:
                    continue
                priority = int(item.get("priority", 30))
                alias_type = str(item.get("alias_type") or "")
                existing_ent = _find_existing_entity(canon, "brand" if "marka" in alias_type.lower() else "model")
                if existing_ent is not None:
                    cat = existing_ent.category
                    prefix = existing_ent.entity_id.split(":", 1)[0]
                else:
                    cat = EntityCategory.BRAND if alias_type in {"Marka", "Marka takma adı"} else EntityCategory.MODEL
                    prefix = "brand" if cat == EntityCategory.BRAND else "model"
                ent = _register_entity(
                    prefix=prefix,
                    canonical_name=canon,
                    category=cat,
                    aliases=(var,),
                    priority=priority,
                )
                _register_alias(alias_text=var, entity=ent, priority=priority, source="compiled:asr_mappings")
                spk = (item.get("spoken") or "").strip()
                if spk:
                    _register_pron(
                        _build_pronunciation(
                            canonical_entity_id=ent.entity_id,
                            surface_key=normalize_matching_key(var),
                            spoken_text=spk,
                            profile="spoken",
                            vocab_chars=vocab_chars,
                            priority=priority,
                        )
                    )

            # Abbreviations and technical terms
            for item in data.get("abbreviations_and_terms", []):
                term_name = (item.get("term") or item.get("source") or "").strip()
                if not term_name:
                    continue
                priority = int(item.get("priority", 40))
                term_cat = str(item.get("category") or "technical")
                norm_key = normalize_matching_key(term_name)
                ent = _register_entity(
                    prefix="tech",
                    canonical_name=term_name,
                    category=EntityCategory.TECHNICAL,
                    priority=priority,
                    metadata={"term_category": term_cat},
                )
                tid = make_safe_id("term", norm_key)
                spoken_primary = (item.get("tts_2026") or item.get("spoken_2026") or item.get("spoken") or "").strip() or None
                terms_by_id[tid] = TechnicalTerm(
                    term_id=tid,
                    canonical_name=term_name,
                    normalized_key=norm_key,
                    category=term_cat,
                    spoken_text=spoken_primary,
                    priority=priority,
                )
                for profile_key in ("tts_2026", "tts_sezer", "spoken"):
                    spk = (item.get(profile_key) or "").strip()
                    if spk:
                        _register_pron(
                            _build_pronunciation(
                                canonical_entity_id=ent.entity_id,
                                surface_key=norm_key,
                                spoken_text=spk,
                                profile=profile_key,
                                vocab_chars=vocab_chars,
                                priority=priority,
                            )
                        )

            # Apostrophe inflections
            for item in data.get("apostrophe_inflections", []):
                canon = (item.get("canonical") or "").strip()
                if not canon:
                    continue
                priority = int(item.get("priority", 5))
                ent = _register_entity(
                    prefix="model" if " " in canon else "brand",
                    canonical_name=canon,
                    category=EntityCategory.MODEL if " " in canon else EntityCategory.BRAND,
                    priority=priority,
                )
                for src_field in ("source", "source_alt"):
                    surf = (item.get(src_field) or "").strip()
                    if not surf:
                        continue
                    _register_alias(alias_text=surf, entity=ent, priority=priority, source="compiled:inflection")
                    for profile_key in ("tts_2026", "tts_sezer"):
                        spk = (item.get(profile_key) or "").strip()
                        if spk:
                            _register_pron(
                                _build_pronunciation(
                                    canonical_entity_id=ent.entity_id,
                                    surface_key=normalize_matching_key(surf),
                                    spoken_text=spk,
                                    profile=profile_key,
                                    vocab_chars=vocab_chars,
                                    priority=priority,
                                )
                            )

    # 2. Read Python BASE_AUTOMOTIVE_LEXICON & CORE_ASR_PHONETIC_ALIASES read-only
    if include_python_rules:
        from backend.automotive_terminology import CORE_ASR_PHONETIC_ALIASES
        from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON, BASE_CATEGORIES

        for raw_term, spoken_val in BASE_AUTOMOTIVE_LEXICON.items():
            cat_str = BASE_CATEGORIES.get(raw_term, "technical")
            cat = {
                "brand": EntityCategory.BRAND,
                "model": EntityCategory.MODEL,
                "technical": EntityCategory.TECHNICAL,
            }.get(cat_str, EntityCategory.TECHNICAL)
            prefix = "brand" if cat == EntityCategory.BRAND else ("model" if cat == EntityCategory.MODEL else "tech")
            disp = raw_term.upper() if cat == EntityCategory.TECHNICAL and len(raw_term) <= 4 else raw_term.title()
            norm_key = normalize_matching_key(raw_term)
            ent = _register_entity(
                prefix=prefix,
                canonical_name=disp,
                category=cat,
                priority=25 if cat != EntityCategory.TECHNICAL else 35,
            )
            _register_alias(alias_text=raw_term, entity=ent, priority=25, source="python:base_rules")
            _register_pron(
                _build_pronunciation(
                    canonical_entity_id=ent.entity_id,
                    surface_key=norm_key,
                    spoken_text=spoken_val,
                    profile="base",
                    vocab_chars=vocab_chars,
                    priority=25,
                )
            )
            if cat == EntityCategory.TECHNICAL:
                tid = make_safe_id("term", norm_key)
                if tid not in terms_by_id:
                    terms_by_id[tid] = TechnicalTerm(
                        term_id=tid,
                        canonical_name=disp,
                        normalized_key=norm_key,
                        category=cat_str,
                        spoken_text=spoken_val,
                        priority=35,
                    )

        for variant, (canon, cat_str) in CORE_ASR_PHONETIC_ALIASES.items():
            cat = {
                "brand": EntityCategory.BRAND,
                "model": EntityCategory.MODEL,
                "technical": EntityCategory.TECHNICAL,
                "dtc": EntityCategory.DTC,
            }.get(cat_str, EntityCategory.TECHNICAL)
            prefix = {
                EntityCategory.BRAND: "brand",
                EntityCategory.MODEL: "model",
                EntityCategory.TECHNICAL: "tech",
                EntityCategory.DTC: "dtc",
            }[cat]
            ent = _register_entity(
                prefix=prefix,
                canonical_name=canon,
                category=cat,
                aliases=(variant,),
                priority=15,
            )
            _register_alias(alias_text=variant, entity=ent, priority=15, source="python:core_asr")
            if cat in {EntityCategory.TECHNICAL, EntityCategory.DTC}:
                norm_canon = normalize_matching_key(canon)
                tid = make_safe_id("term", norm_canon)
                existing_term = terms_by_id.get(tid)
                merged_aliases = (*(existing_term.aliases if existing_term else ()), variant)
                terms_by_id[tid] = TechnicalTerm(
                    term_id=tid,
                    canonical_name=canon,
                    normalized_key=norm_canon,
                    category=cat_str,
                    spoken_text=existing_term.spoken_text if existing_term else None,
                    aliases=merged_aliases,
                    priority=15,
                )

    # 3. Read foreign morphological lexicon JSON read-only
    if foreign_lexicon_path is not None:
        fp = Path(foreign_lexicon_path)
        if fp.exists():
            fdata = json.loads(fp.read_text(encoding="utf-8"))
            for key, val in fdata.items():
                if not isinstance(val, Mapping):
                    continue
                spoken = str(val.get("spoken") or "").strip()
                if not spoken:
                    continue
                norm_key = normalize_matching_key(str(key))
                cat_str = str(val.get("category") or "technical")
                cat = {
                    "brand": EntityCategory.BRAND,
                    "model": EntityCategory.MODEL,
                }.get(cat_str, EntityCategory.TECHNICAL)
                prefix = "brand" if cat == EntityCategory.BRAND else ("model" if cat == EntityCategory.MODEL else "tech")
                ent = _register_entity(
                    prefix=prefix,
                    canonical_name=str(val.get("canonical_stem") or key).strip(),
                    category=cat,
                    priority=20,
                )
                _register_pron(
                    _build_pronunciation(
                        canonical_entity_id=ent.entity_id,
                        surface_key=norm_key,
                        spoken_text=spoken,
                        profile="foreign",
                        vocab_chars=vocab_chars,
                        priority=20,
                        phonetic_syllables=val.get("phonetic_syllables") or (),
                        stress_syllable_idx=val.get("stress_syllable_idx"),
                        ends_with_consonant=val.get("ends_with_consonant"),
                        last_vowel_backness=val.get("last_vowel_backness"),
                    )
                )

    # 4. Merge any caller-supplied in-memory extensions (used in tests/overlays)
    for ent in extra_entities:
        entities_by_id[ent.entity_id] = ent
    for al in extra_aliases:
        alias_acc[(al.normalized_key, al.canonical_entity_id)] = al
    for pr in extra_pronunciations:
        prons_by_id[pr.variant_id] = pr
    for tm in extra_technical_terms:
        terms_by_id[tm.term_id] = tm

    return LexiconSnapshot(
        entities=tuple(entities_by_id.values()),
        aliases=tuple(alias_acc.values()),
        pronunciations=tuple(prons_by_id.values()),
        technical_terms=tuple(terms_by_id.values()),
        vocab_chars=vocab_chars,
        source_version=source_version,
        source_metadata=meta_summary,
    )
