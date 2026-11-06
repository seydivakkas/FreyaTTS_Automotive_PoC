import asyncio
import time
import numpy as np
from scipy.signal import resample_poly
from backend.dsp import (
    apply_fade_and_comfort_noise as apply_fade_and_comfort_noise,
    apply_telephony_eq_and_downsample_8k as apply_telephony_eq_and_downsample_8k,
)
from math import gcd


def resample(samples, source, target=16000):
    g = gcd(source, target)
    return resample_poly(samples, target // g, source // g).astype(np.float32)


def pcm(samples):
    return (np.clip(samples, -1, 1) * 32767).round().astype("<i2").tobytes()


def frames(data, size=320):
    for i in range(0, len(data), size):
        yield data[i : i + size].ljust(size, b"\0")


async def pace(data, send, cancelled, clock=time.monotonic, sleep=asyncio.sleep):
    deadline = clock()
    for frame in frames(data):
        if cancelled():
            return
        await send(frame)
        deadline += 0.02
        if deadline < clock():
            deadline = clock() + 0.02
        await sleep(max(0, deadline - clock()))


class Endpoint:
    def __init__(self, model):
        self.model = model
        self.pending = np.zeros(0, np.float32)
        self.pre = []
        self.speech = []
        self.silence = 0
        self.active = False
        self.last_voice_at = None

    def feed(self, samples):
        import torch

        self.pending = np.concatenate((self.pending, samples))
        results = []
        started = False
        while len(self.pending) >= 512:
            block, self.pending = self.pending[:512], self.pending[512:]
            with torch.inference_mode():
                voiced = float(self.model(torch.from_numpy(block), 16000)) > 0.55
            if voiced:
                self.last_voice_at = time.monotonic()
            if voiced and not self.active:
                self.active = True
                self.speech = self.pre.copy()
                self.silence = 0
                started = True
            if self.active:
                self.speech.append(block)
                self.silence = 0 if voiced else self.silence + 512
                if self.silence >= 4800 or len(self.speech) >= 625:
                    results.append(np.concatenate(self.speech))
                    self.active = False
                    self.speech = []
            self.pre = (self.pre + [block])[-10:]
        return started, results
