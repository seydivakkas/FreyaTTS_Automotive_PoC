"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from backend.core.adapters.legacy_asr import asr_result_from_legacy_text, asr_result_to_legacy_text
from backend.core.adapters.legacy_audio import audio_frame_from_legacy_pcm, audio_frame_to_legacy_pcm
from backend.core.adapters.legacy_dialogue import dialogue_response_from_legacy, tool_receipt_from_legacy_outcome
from backend.core.adapters.legacy_playback import playback_event_from_legacy, rendered_frame_from_legacy_pcm
from backend.core.adapters.legacy_synthesis import audio_chunk_from_legacy_waveform, synthesis_plan_from_legacy

__all__ = [
    "asr_result_from_legacy_text",
    "asr_result_to_legacy_text",
    "audio_chunk_from_legacy_waveform",
    "audio_frame_from_legacy_pcm",
    "audio_frame_to_legacy_pcm",
    "dialogue_response_from_legacy",
    "playback_event_from_legacy",
    "rendered_frame_from_legacy_pcm",
    "synthesis_plan_from_legacy",
    "tool_receipt_from_legacy_outcome",
]
