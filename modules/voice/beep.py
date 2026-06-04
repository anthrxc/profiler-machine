# modules/voice/beep.py
# Generates the half-second 1 kHz sine-wave tone played before PROFM listens.
# Saved to assets/audio/voice/beep.wav on first use, replayed thereafter.

import os
import wave
import numpy as np


BEEP_PATH = os.path.join('assets', 'audio', 'voice', 'beep.wav')


def generate_beep(
    path=BEEP_PATH,
    frequency=1000.0,
    duration=0.5,
    sample_rate=44100,
    amplitude=0.3,
    fade_ms=10.0,
):
    """Write a 1 kHz sine-wave tone to `path` as a 16-bit mono WAV.

    A short linear fade in/out removes the click at start/end. Skips work
    when the file already exists.
    """
    if os.path.exists(path):
        return path

    os.makedirs(os.path.dirname(path), exist_ok=True)

    total_samples = int(sample_rate * duration)
    t = np.arange(total_samples) / sample_rate
    samples = np.sin(2.0 * np.pi * frequency * t)

    # Fade in/out to suppress click artifacts.
    fade_samples = max(1, int(sample_rate * (fade_ms / 1000.0)))
    if fade_samples * 2 < total_samples:
        fade_in = np.linspace(0.0, 1.0, fade_samples)
        fade_out = np.linspace(1.0, 0.0, fade_samples)
        samples[:fade_samples] *= fade_in
        samples[-fade_samples:] *= fade_out

    pcm = (samples * amplitude * 32767.0).astype(np.int16)

    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

    return path
