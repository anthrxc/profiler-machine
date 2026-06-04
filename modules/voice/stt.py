# modules/voice/stt.py
# Whisper-based offline speech-to-text with chunked listening + RMS-based
# silence detection. Records at the device's native sample rate (to avoid
# PaErrorCode -9997 on WASAPI devices) then resamples to 16 kHz for Whisper.

import threading

import numpy as np

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception as e:
    _SD_AVAILABLE = False
    _SD_IMPORT_ERR = e


WHISPER_RATE   = 16000  # Whisper expects 16 kHz mono
CHUNK_DURATION = 0.1    # seconds per read — keeps abort-latency under 100 ms


def _resample(samples, src_rate, dst_rate):
    """Linear interpolation resample. Good enough for speech."""
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    new_len = max(1, int(len(samples) * dst_rate / src_rate))
    old_idx = np.linspace(0, len(samples) - 1, new_len)
    fi = np.floor(old_idx).astype(int)
    ci = np.minimum(fi + 1, len(samples) - 1)
    frac = (old_idx - fi).astype(np.float32)
    return (samples[fi] + frac * (samples[ci] - samples[fi])).astype(np.float32)


def _device_native_rate(device_id):
    """Return the default sample rate for `device_id`, falling back to 44100."""
    try:
        info = sd.query_devices(device_id)
        rate = int(info.get('default_samplerate', 44100))
        return rate if rate > 0 else 44100
    except Exception:
        return 44100


class WhisperSTT:
    """Offline Whisper transcriber.

    The model is loaded lazily inside `load()` so callers can show progress
    feedback during the (potentially slow) first-time download.
    """

    def __init__(self, model_name='base.en', device_id=None):
        self._model_name = model_name
        self._model = None
        self._load_lock = threading.Lock()
        self._device_id = device_id  # None = system default; int for explicit device

    @staticmethod
    def microphone_available():
        """Return True iff sounddevice imported AND at least one input device exists."""
        if not _SD_AVAILABLE:
            return False
        try:
            for d in sd.query_devices():
                if d.get('max_input_channels', 0) > 0:
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def import_error():
        """Return the underlying import error if sounddevice failed to load."""
        return None if _SD_AVAILABLE else _SD_IMPORT_ERR

    def load(self):
        """Load the Whisper model (downloads on first run). Idempotent."""
        with self._load_lock:
            if self._model is not None:
                return
            import whisper
            self._model = whisper.load_model(self._model_name)

    def listen(
        self,
        max_duration=10.0,
        silence_threshold=0.008,
        silence_duration=1.2,
        min_speech_duration=0.3,
        is_running=None,
    ):
        """Record from the microphone until silence or `max_duration`.

        Records at the device's native sample rate, then resamples to
        16 kHz for Whisper. Returns transcribed text (possibly empty).
        Aborts cleanly and returns "" when `is_running()` flips to False.
        """
        if not _SD_AVAILABLE or self._model is None:
            return ""

        native_rate = _device_native_rate(self._device_id)
        chunk_samples = int(CHUNK_DURATION * native_rate)
        max_chunks = int(max_duration / CHUNK_DURATION)
        silence_chunks_needed = max(1, int(silence_duration / CHUNK_DURATION))
        min_speech_chunks = max(1, int(min_speech_duration / CHUNK_DURATION))

        chunks = []
        silent_run = 0
        speech_chunks = 0
        heard_speech = False

        try:
            stream = sd.InputStream(
                samplerate=native_rate,
                channels=1,
                dtype='float32',
                blocksize=chunk_samples,
                device=self._device_id,
            )
            stream.start()
        except Exception as e:
            print(f"[WhisperSTT] Failed to open microphone (device {self._device_id}): {e}")
            return ""

        try:
            for _ in range(max_chunks):
                if is_running is not None and not is_running():
                    return ""

                try:
                    chunk, _overflow = stream.read(chunk_samples)
                except Exception as e:
                    print(f"[WhisperSTT] Stream read failed: {e}")
                    break

                samples = chunk.flatten()
                chunks.append(samples)

                rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
                if rms < silence_threshold:
                    silent_run += 1
                    if heard_speech and silent_run >= silence_chunks_needed:
                        break
                else:
                    silent_run = 0
                    speech_chunks += 1
                    if speech_chunks >= min_speech_chunks:
                        heard_speech = True
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not heard_speech or not chunks:
            return ""

        audio = np.concatenate(chunks).astype(np.float32)

        if native_rate != WHISPER_RATE:
            audio = _resample(audio, native_rate, WHISPER_RATE)

        try:
            result = self._model.transcribe(audio, language='en', fp16=False)
            return (result.get('text') or "").strip()
        except Exception as e:
            print(f"[WhisperSTT] Transcription failed: {e}")
            return ""