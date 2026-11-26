# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz
import importlib.metadata

import numpy as np
import pytest

from backend.models import Models, SharedVadPool


class FakeStatefulVad:
    """Sentetik recurrent state; in-place changes expose aliasing errors."""
    def __init__(self):
        self.reset_count = 0
        self.reset_states()

    def reset_states(self):
        self.reset_count += 1
        self._state = np.zeros(1, dtype=np.float32)
        self._context = np.zeros(1, dtype=np.float32)
        self._last_sr = 0
        self._last_batch_size = 0

    def __call__(self, samples, rate):
        self._state[0] += float(samples[0])
        self._context[0] = float(samples[0])
        self._last_sr = rate
        self._last_batch_size = 1
        if samples[0] < 0:
            raise ValueError("synthetic VAD failure")
        return float(self._state[0])


def test_HF07_shared_weights_keep_independent_state_and_recover_on_error():
    raw = FakeStatefulVad()
    models = Models()
    models.vad = SharedVadPool(raw)
    initial_resets = raw.reset_count
    a = models.new_vad_session()
    assert a([1], 16000) == 1
    b = models.new_vad_session()
    assert raw.reset_count == initial_resets
    assert b([10], 16000) == 10
    assert a([2], 16000) == 3
    with pytest.raises(ValueError, match="synthetic"):
        b([-100], 16000)
    assert b([1], 16000) == 11
    assert a([1], 16000) == 4
    assert raw._state[0] == 0
    assert raw._context[0] == 0
    assert raw._last_sr == 0
    assert raw._last_batch_size == 0
    assert a.pool.model is b.pool.model is raw


def test_HF07_unsupported_streaming_state_is_not_shared():
    class Unsupported:
        def reset_states(self):
            pass

    with pytest.raises(RuntimeError, match="durum sözleşmesi"):
        SharedVadPool(Unsupported())


@pytest.mark.gpu
def test_HF07_real_installed_silero_jit_interleaved_parity():
    """Uses only the already installed pinned model; no download or live audio."""
    torch = pytest.importorskip("torch")
    silero = pytest.importorskip("silero_vad")
    assert importlib.metadata.version("silero-vad") == "6.2.3"
    raw = silero.load_silero_vad()
    torch_gen = torch.Generator().manual_seed(711)
    a_blocks = [torch.randn(512, generator=torch_gen) * 0.03 for _ in range(8)]
    b_blocks = [torch.randn(512, generator=torch_gen) * 0.01 for _ in range(8)]
    with torch.inference_mode():
        # Compare against stock streaming inference, not another pool session.
        raw.reset_states()
        expected_a = [float(raw(x, 16000)) for x in a_blocks]
        raw.reset_states()
        expected_b = [float(raw(x, 16000)) for x in b_blocks]
        pool = SharedVadPool(raw)
        a = pool.new_session()
        actual_a = [float(a(a_blocks[0], 16000))]
        b = pool.new_session()
        actual_b = []
        for i in range(len(b_blocks)):
            actual_b.append(float(b(b_blocks[i], 16000)))
            if i + 1 < len(a_blocks):
                actual_a.append(float(a(a_blocks[i + 1], 16000)))
    np.testing.assert_allclose(actual_a, expected_a, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(actual_b, expected_b, rtol=1e-5, atol=1e-6)
