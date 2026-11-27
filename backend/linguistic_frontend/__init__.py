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

from backend.linguistic_frontend.chunking_adapter import (
    ChunkCandidate,
    ChunkingResult,
    chunk_normalized_text,
)
from backend.linguistic_frontend.f4_b_morphology import (
    F4B_ALGORITHM_REVISION,
    G2P_ALPHABET_ID,
    AnalysisStatus,
    F4BMorphologyBundle,
    G2PGuidance,
    G2PStatus,
    MorphologicalAnalysis,
    PronunciationBasis,
    RealizationDecision,
    RealizationDecisionKind,
    SuffixPart,
    analyze_f4b_morphology,
    resolve_vowel_harmony,
)
from backend.linguistic_frontend.f4_c_prosody import (
    F4C_RULE_REVISION,
    CapabilitySupportStatus,
    CliticLink,
    CliticType,
    ControlDisposition,
    ControlOwner,
    F4CProsodyBundle,
    LiaisonHint,
    PauseIntent,
    ProsodyTarget,
    StressAssessment,
    StressRuleClass,
    SyllabificationResult,
    SyllableUnit,
    SyllableWeight,
    plan_f4c_prosody_and_chunks,
)
from backend.linguistic_frontend.config_adapter import (
    PinnedFrontendSnapshot,
    SnapshotPinResult,
    pin_frontend_snapshot,
)
from backend.linguistic_frontend.turkish_datetime_phone import (
    format_turkish_phone,
    format_turkish_time,
)
from backend.linguistic_frontend.freya_adapter import (
    FreyaVocabularyValidator,
    VocabularyCheck,
    VocabularyStatus,
)
from backend.linguistic_frontend.input_validator import (
    AdmittedResponse,
    InputValidationResult,
    PlanningOutcome,
    ResponseDedupLedger,
    validate_dialogue_response,
)
from backend.linguistic_frontend.legacy_adapter import (
    LegacyPreparedPayload,
    PreparedPlanHandoff,
    ProvenanceClass,
    accept_prepared_plan,
    legacy_clauses,
    legacy_normalize,
    legacy_prepare_tts_clause,
    wrap_legacy_string,
)
from backend.linguistic_frontend.lexicon_adapter import (
    ApprovedPronunciationMatch,
    LexiconAdapter,
    VariantGovernanceStatus,
)
from backend.linguistic_frontend.lifecycle import (
    LifecycleDeliveryResult,
    LinguisticPreparationCoordinator,
)
from backend.linguistic_frontend.morphology_adapter import (
    MorphologyAnalysisResult,
    analyze_morphology_readonly,
)
from backend.linguistic_frontend.pipeline import (
    LinguisticFrontendPipeline,
    PreparationResult,
    ShadowComparisonResult,
)
from backend.linguistic_frontend.plan_builder import build_synthesis_plan, make_plan_id
from backend.linguistic_frontend.protected_atoms import (
    AtomKind,
    ProtectedAtom,
    ProtectedAtomScanResult,
    scan_protected_atoms,
)
from backend.linguistic_frontend.quality_gate import QualityGateResult, validate_plan_quality
from backend.linguistic_frontend.semantic_tokenizer import (
    SemanticTokenizationResult,
    tokenize_semantic_atoms,
)
from backend.linguistic_frontend.telemetry import F4TelemetrySnapshot, LinguisticTelemetry
from backend.linguistic_frontend.text_mapping import (
    NormalizationTrace,
    SpanMappingEntry,
    TextMapping,
    build_text_mapping,
)
from backend.linguistic_frontend.text_normalizer import (
    RULESET_REVISION,
    SinglePassNormalizationResult,
    run_single_normalization_pass,
)
from backend.linguistic_frontend.intent_prosody import (
    IntentProsodySpec,
    INTENT_PROSODY_TABLE,
    PRIORITY_ORDER,
    resolve_intent_prosody,
)

__all__ = [
    "AdmittedResponse",
    "AnalysisStatus",
    "ApprovedPronunciationMatch",
    "AtomKind",
    "CapabilitySupportStatus",
    "ChunkCandidate",
    "ChunkingResult",
    "CliticLink",
    "CliticType",
    "ControlDisposition",
    "ControlOwner",
    "F4BMorphologyBundle",
    "F4B_ALGORITHM_REVISION",
    "F4CProsodyBundle",
    "F4C_RULE_REVISION",
    "F4TelemetrySnapshot",
    "FreyaVocabularyValidator",
    "G2PGuidance",
    "G2PStatus",
    "G2P_ALPHABET_ID",
    "InputValidationResult",
    "LegacyPreparedPayload",
    "LexiconAdapter",
    "LiaisonHint",
    "LifecycleDeliveryResult",
    "LinguisticFrontendPipeline",
    "LinguisticPreparationCoordinator",
    "LinguisticTelemetry",
    "MorphologicalAnalysis",
    "MorphologyAnalysisResult",
    "NormalizationTrace",
    "PauseIntent",
    "PinnedFrontendSnapshot",
    "PlanningOutcome",
    "PreparationResult",
    "PreparedPlanHandoff",
    "PronunciationBasis",
    "ProsodyTarget",
    "ProtectedAtom",
    "ProtectedAtomScanResult",
    "ProvenanceClass",
    "QualityGateResult",
    "RULESET_REVISION",
    "RealizationDecision",
    "RealizationDecisionKind",
    "ResponseDedupLedger",
    "SemanticTokenizationResult",
    "ShadowComparisonResult",
    "SinglePassNormalizationResult",
    "SnapshotPinResult",
    "SpanMappingEntry",
    "StressAssessment",
    "StressRuleClass",
    "SuffixPart",
    "SyllabificationResult",
    "SyllableUnit",
    "SyllableWeight",
    "TextMapping",
    "VariantGovernanceStatus",
    "VocabularyCheck",
    "VocabularyStatus",
    "accept_prepared_plan",
    "analyze_f4b_morphology",
    "analyze_morphology_readonly",
    "build_synthesis_plan",
    "build_text_mapping",
    "chunk_normalized_text",
    "legacy_clauses",
    "legacy_normalize",
    "legacy_prepare_tts_clause",
    "make_plan_id",
    "pin_frontend_snapshot",
    "plan_f4c_prosody_and_chunks",
    "resolve_vowel_harmony",
    "run_single_normalization_pass",
    "scan_protected_atoms",
    "tokenize_semantic_atoms",
    "validate_dialogue_response",
    "validate_plan_quality",
    "wrap_legacy_string",
    # intent prosody
    "IntentProsodySpec",
    "INTENT_PROSODY_TABLE",
    "PRIORITY_ORDER",
    "resolve_intent_prosody",
    # ADR-F4-02 & ADR-F4-03
    "format_turkish_phone",
    "format_turkish_time",
]
