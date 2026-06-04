# modules/voice/tts.py
# Word-by-word TTS with per-word voice assignment and WAV cache.
#
# Each normalized word is deterministically mapped to one of the installed
# system voices via md5(word) % num_voices. On cache miss the word is
# synthesized once with pyttsx3 and written to:
#   assets/audio/voice/voice_<idx>/<word>.wav
#
# speak() collects all word WAVs for a sentence, resamples them to a common
# format, concatenates into a single in-memory buffer, and plays once — this
# eliminates the inter-word gap that per-call playback overhead introduces.
# The per-word voice rotation (different voice per word) is fully preserved.

import io
import os
import re
import hashlib
import struct
import threading
import time
import wave

import numpy as np

from modules.io.playsound import play_sound


VOICE_CACHE_DIR = os.path.join('assets', 'audio', 'voice')

# Target format for the concatenated output WAV.
# All per-word WAVs are resampled to this before joining.
TARGET_RATE     = 22050
TARGET_CHANNELS = 1
TARGET_WIDTH    = 2   # 16-bit

# Tiny silence pad inserted between words (in samples at TARGET_RATE).
# ~25 ms — just enough to prevent phonemes clipping into each other
# while keeping speech tight.
INTER_WORD_PAD_SAMPLES = int(TARGET_RATE * 0.025)


def _normalize_word(word):
    """Lowercase, strip punctuation but keep apostrophe + hyphen."""
    return re.sub(r"[^a-z0-9\-']", '', word.lower())


def _safe_filename(word):
    """Filesystem-safe variant of a normalized word."""
    return re.sub(r"[^a-z0-9\-_]", '_', word.lower())


def _read_wav_samples(path):
    """Read a WAV file and return (samples_int16_ndarray, sample_rate, n_channels).

    Returns (None, 0, 0) on failure.
    """
    try:
        with wave.open(path, 'rb') as wf:
            n_channels  = wf.getnchannels()
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            n_frames    = wf.getnframes()
            raw         = wf.readframes(n_frames)
    except Exception as e:
        print(f"[VoiceTTS] Failed to read {path}: {e}")
        return None, 0, 0

    # Parse raw bytes → int16 samples.
    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16)
    elif sample_width == 1:
        # 8-bit unsigned — convert to signed 16-bit.
        u8 = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        samples = ((u8 - 128.0) * 256.0).astype(np.int16)
    elif sample_width == 4:
        s32 = np.frombuffer(raw, dtype=np.int32).astype(np.float32)
        samples = (s32 / 65536.0).astype(np.int16)
    else:
        return None, 0, 0

    return samples, sample_rate, n_channels


def _to_mono(samples, n_channels):
    """Mix down to mono if needed."""
    if n_channels == 1 or samples is None:
        return samples
    reshaped = samples.reshape(-1, n_channels).astype(np.float32)
    return reshaped.mean(axis=1).astype(np.int16)


def _resample(samples, src_rate, dst_rate):
    """Naive linear interpolation resample. Good enough for speech."""
    if src_rate == dst_rate or samples is None or len(samples) == 0:
        return samples
    ratio = dst_rate / src_rate
    new_len = max(1, int(len(samples) * ratio))
    old_indices = np.linspace(0, len(samples) - 1, new_len)
    floor_idx = np.floor(old_indices).astype(int)
    ceil_idx  = np.minimum(floor_idx + 1, len(samples) - 1)
    frac      = (old_indices - floor_idx).astype(np.float32)
    s = samples.astype(np.float32)
    resampled = s[floor_idx] + frac * (s[ceil_idx] - s[floor_idx])
    return resampled.astype(np.int16)


def _normalise_wav(path):
    """Load WAV at `path` and return samples normalised to TARGET format."""
    samples, rate, channels = _read_wav_samples(path)
    if samples is None:
        return None
    samples = _to_mono(samples, channels)
    samples = _resample(samples, rate, TARGET_RATE)
    return samples


def _write_wav_bytes(samples):
    """Encode int16 samples into an in-memory WAV and return the bytes."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(TARGET_CHANNELS)
        wf.setsampwidth(TARGET_WIDTH)
        wf.setframerate(TARGET_RATE)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


class VoiceTTS:
    """Per-word voice-rotation TTS with a persistent WAV cache.

    Thread-safety: pyttsx3 engines are not reentrant. We init a fresh engine
    inside the lock on each synthesis call because long-lived engines on
    macOS/Linux get into a bad state after repeated save_to_file/runAndWait
    cycles. Cache hits skip the lock entirely.
    """

    def __init__(self):
        # COM must be initialized on the worker thread before pyttsx3 touches SAPI.
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        import pyttsx3
        # Probe installed voices ONCE so cache layout is stable.
        probe = pyttsx3.init()
        self._voice_ids = [v.id for v in probe.getProperty('voices')]
        try:
            probe.stop()
        except Exception:
            pass
        del probe

        self._num_voices = max(1, len(self._voice_ids))
        self._lock = threading.Lock()

        # Build cache directories upfront.
        os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
        for i in range(self._num_voices):
            os.makedirs(os.path.join(VOICE_CACHE_DIR, f"voice_{i}"), exist_ok=True)

        # Temp file for the concatenated sentence WAV.
        self._concat_path = os.path.join(VOICE_CACHE_DIR, '_sentence.wav')

    @property
    def voice_count(self):
        return self._num_voices

    def _voice_for_word(self, normalized_word):
        """Hash → consistent voice index for the same word every time."""
        digest = hashlib.md5(normalized_word.encode('utf-8')).hexdigest()
        return int(digest, 16) % self._num_voices

    def _word_path(self, normalized_word, voice_idx):
        safe = _safe_filename(normalized_word) or '_'
        return os.path.join(VOICE_CACHE_DIR, f"voice_{voice_idx}", f"{safe}.wav")

    def _synthesize_word(self, normalized_word, voice_idx, path):
        """Synthesize one word with the chosen voice. Returns True on success."""
        with self._lock:
            try:
                import pyttsx3
                engine = pyttsx3.init()
                if voice_idx < len(self._voice_ids):
                    try:
                        engine.setProperty('voice', self._voice_ids[voice_idx])
                    except Exception:
                        pass
                engine.save_to_file(normalized_word, path)
                engine.runAndWait()
                try:
                    engine.stop()
                except Exception:
                    pass
                del engine
            except Exception as e:
                print(f"[VoiceTTS] Synthesis failed for '{normalized_word}': {e}")
                return False
        # save_to_file writes asynchronously on some backends — poll briefly.
        for _ in range(20):
            if os.path.exists(path) and os.path.getsize(path) > 44:
                return True
            time.sleep(0.05)
        return os.path.exists(path)

    def _ensure_word(self, word):
        """Synthesize-if-needed and return (path, normalized). Returns (None, '') on failure."""
        normalized = _normalize_word(word)
        if not normalized:
            return None, ''
        voice_idx = self._voice_for_word(normalized)
        path = self._word_path(normalized, voice_idx)
        if not os.path.exists(path) or os.path.getsize(path) <= 44:
            ok = self._synthesize_word(normalized, voice_idx, path)
            if not ok:
                return None, normalized
        return path, normalized

    def speak(self, sentence, is_running=None):
        """Synthesize all words in `sentence`, concatenate, and play once.

        Eliminates inter-word playback gaps by joining all word WAVs into a
        single buffer before handing off to the audio backend.
        `is_running` may abort synthesis mid-sentence when voice mode stops.
        """
        if not sentence:
            return

        silence = np.zeros(INTER_WORD_PAD_SAMPLES, dtype=np.int16)
        chunks = []

        for word in sentence.split():
            if is_running is not None and not is_running():
                return
            path, _ = self._ensure_word(word)
            if path is None:
                continue
            samples = _normalise_wav(path)
            if samples is None or len(samples) == 0:
                continue
            chunks.append(samples)
            chunks.append(silence)

        if not chunks:
            return

        # Drop the trailing silence pad.
        if len(chunks) > 1 and np.all(chunks[-1] == 0):
            chunks.pop()

        combined = np.concatenate(chunks)
        wav_bytes = _write_wav_bytes(combined)

        # Write to temp file then play.
        try:
            with open(self._concat_path, 'wb') as f:
                f.write(wav_bytes)
            play_sound(self._concat_path)
        except Exception as e:
            print(f"[VoiceTTS] Playback failed: {e}")

    def prewarm(self, words, is_running=None):
        """Pre-synthesize a list of words without playing them."""
        for word in words:
            if is_running is not None and not is_running():
                return
            normalized = _normalize_word(word)
            if not normalized:
                continue
            voice_idx = self._voice_for_word(normalized)
            path = self._word_path(normalized, voice_idx)
            if not os.path.exists(path) or os.path.getsize(path) <= 44:
                self._synthesize_word(normalized, voice_idx, path)