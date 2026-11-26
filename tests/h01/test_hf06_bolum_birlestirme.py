# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from backend import session as module


@pytest.mark.asyncio
async def test_HF06_two_segments_before_f3_reach_one_dialogue_turn(monkeypatch):
    """İlk ASR beklerken ikinci segment gelir: iki bölüm F3'e tek tur gider."""
    session = module.VoiceSession.__new__(module.VoiceSession)
    session.id = "synthetic-hf06"
    session.closed = False
    session.task = None
    session.generation = 0
    session.playing = False
    session.paused = False
    session.supervisor = None
    session.bargein_controller = None
    session._pending_audio = None
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    received = []
    first = np.full(512, 0.1, dtype=np.float32)
    second = np.full(512, 0.2, dtype=np.float32)

    async def transcribe(audio):
        received.append(audio.copy())
        if len(received) == 1:
            first_started.set()
            await release_first.wait()
            return "Benim aracım"
        np.testing.assert_array_equal(audio, np.concatenate((first, second)))
        return "Benim aracım 2021 model Passat"

    answers = []

    async def answer(text):
        answers.append(text)
        return "Tamam"

    async def noop(*args, **kwargs):
        pass

    session.emit = noop
    session.reply = noop
    session.save = lambda *args, **kwargs: None
    session.control = SimpleNamespace(move=noop)
    session.dialogue = SimpleNamespace(answer=answer, awaiting=False, done=False)
    monkeypatch.setattr(module.models, "transcribe", transcribe)
    session._schedule_utterance(first, None)
    task = session.task
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        session._schedule_utterance(second, None)
        assert session.task is task
        assert not task.cancelled()
        release_first.set()
        await asyncio.wait_for(task, timeout=1)
        assert answers == ["Benim aracım 2021 model Passat"]
        assert len(received) == 2
        assert session._pending_audio is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
