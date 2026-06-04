# modules/voice/voice_mode.py
# Voice mode controller — a state machine running on a worker thread that:
#   1. plays a beep,
#   2. records audio until silence (or timeout),
#   3. transcribes via Whisper,
#   4. either dispatches the resolved console command, asks for clarification,
#      or enters standby waiting for the "PROFM" wake word.
#
# Communication with the UI is push-only via callbacks supplied by the
# ConsoleWidget: `print_cb` for console output and `dispatch_cb` for
# executing resolved commands on the main thread.

import os
import threading
import time

from modules.io.playsound import play_sound
from modules.voice.beep import generate_beep, BEEP_PATH
from modules.voice.tts import VoiceTTS
from modules.voice.stt import WhisperSTT
from modules.voice.intent import IntentClassifier
from modules.voice import phrases as P


# ── Timing knobs ────────────────────────────────────────────────────────────

ACTIVE_LISTEN_DURATION = 10.0     # seconds of active listening per turn
STANDBY_LISTEN_DURATION = 15.0    # seconds per standby poll for wake word
MIC_CHECK_DURATION = 5.0          # seconds to wait for "yes" after "can you hear me"
CLARIFY_LISTEN_DURATION = 6.0     # seconds to wait for confirm/slot answer
INTER_TURN_PAUSE = 0.2            # brief gap between TTS-end and beep-start


class VoiceMode:
    """Voice mode state machine.

    Lifecycle:
        vm = VoiceMode(print_cb, dispatch_cb, on_stopped_cb)
        vm.start()  # spins up worker thread, returns immediately
        ...
        vm.stop()   # cooperative shutdown — thread exits within ~100 ms
    """

    def __init__(self, print_cb, dispatch_cb, on_stopped_cb=None,
                 whisper_model='base.en', device_id=None):
        """
        print_cb(text, ok=True)
            Thread-safe console print. Echoes voice events into the console.
        dispatch_cb(text)
            Thread-safe submission of a console command. Returns when the
            command is queued for execution on the main thread.
        on_stopped_cb()
            Optional. Called from the worker thread once it exits — lets the
            main window update its `_voice_mode` reference / status.
        whisper_model
            Whisper model name. "base.en" is the default sweet spot.
        device_id
            Microphone device index (from sounddevice.query_devices()).
            None = system default. Use 11 for Camo WASAPI on your system.
        """
        self._print = print_cb
        self._dispatch = dispatch_cb
        self._on_stopped = on_stopped_cb

        self._tts = None
        self._stt = None
        self._intents = None

        self._whisper_model = whisper_model
        self._device_id = device_id

        self._running = False
        self._thread = None
        self._beep_path = None
        self._init_error = None

    # ── public lifecycle ───────────────────────────────────────────────────

    def is_active(self):
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_active():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="VoiceMode")
        self._thread.start()

    def stop(self):
        self._running = False
        # Don't join — caller may be on the UI thread and the worker may be
        # mid-utterance. The next is_running() check in the worker will
        # break the loop. The thread is daemon, so process exit is safe.

    # ── core run loop ──────────────────────────────────────────────────────

    def _run(self):
        # Initialize COM apartment for this thread on Windows.
        # pyttsx3 (SAPI5) requires CoInitialize() on every thread that
        # calls into COM. Without this, pyttsx3.init() raises a hard crash.
        _com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_initialized = True
        except ImportError:
            pass

        try:
            self._initialize()
        except Exception as e:
            self._init_error = e
            self._print(f"Voice mode failed to initialize: {e}", ok=False)
            self._running = False
            if self._on_stopped:
                self._on_stopped()
            return
        finally:
            pass  # keep COM alive for the rest of the loop

        if not self._running:
            self._cleanup()
            return

        # Microphone presence check before any audio I/O.
        if not WhisperSTT.microphone_available():
            err = WhisperSTT.import_error()
            msg = f"No microphone available." + (f" ({err})" if err else "")
            self._print(msg, ok=False)
            self._running = False
            if self._on_stopped:
                self._on_stopped()
            return

        # "Can you hear me?" handshake.
        if not self._mic_handshake():
            self._running = False
            if self._on_stopped:
                self._on_stopped()
            return

        # Main listening loop.
        in_standby = False
        try:
            while self._running:
                if in_standby:
                    in_standby = self._standby_step()
                else:
                    in_standby = self._active_step()
        except Exception as e:
            self._print(f"Voice mode crashed: {e}", ok=False)
        finally:
            self._cleanup()
            self._running = False
            if _com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            if self._on_stopped:
                self._on_stopped()

    # ── initialization ─────────────────────────────────────────────────────

    def _initialize(self):
        """Build the beep, load TTS, load Whisper, build the intent classifier."""
        self._print("Voice mode: generating beep...")
        self._beep_path = generate_beep()

        self._print("Voice mode: loading TTS engine...")
        self._tts = VoiceTTS()
        self._print(f"Voice mode: {self._tts.voice_count} system voice(s) available.")

        self._print("Voice mode: pre-warming response cache (one-time)...")
        # Warm the cache on a background thread so model load can overlap.
        warm_thread = threading.Thread(
            target=self._tts.prewarm,
            args=(P.all_response_words(),),
            kwargs={'is_running': self._is_running},
            daemon=True,
        )
        warm_thread.start()

        self._print(f"Voice mode: loading Whisper model '{self._whisper_model}'...")
        if self._device_id is not None:
            self._print(f"Voice mode: using microphone device {self._device_id}")
        self._stt = WhisperSTT(model_name=self._whisper_model, device_id=self._device_id)
        self._stt.load()

        self._print("Voice mode: building intent classifier...")
        self._intents = IntentClassifier()

        warm_thread.join(timeout=30.0)
        self._print("Voice mode: ready.", ok=True)

    def _cleanup(self):
        # Nothing to release beyond letting daemon thread die.
        pass

    def _is_running(self):
        return self._running

    # ── audio helpers ──────────────────────────────────────────────────────

    def _beep(self):
        if not self._running:
            return
        if not self._beep_path or not os.path.exists(self._beep_path):
            return
        try:
            play_sound(self._beep_path)
        except Exception as e:
            print(f"[VoiceMode] beep playback failed: {e}")

    def _speak(self, sentence):
        if not self._running or not sentence:
            return
        # Echo to console so the operator sees what PROFM is saying even
        # when audio output is muted or unclear.
        self._print(f"⟨PROFM⟩ {sentence}")
        self._tts.speak(sentence, is_running=self._is_running)
        time.sleep(INTER_TURN_PAUSE)

    def _listen(self, duration):
        """Beep, then listen for `duration` seconds (or until silence)."""
        if not self._running:
            return ""
        self._beep()
        text = self._stt.listen(
            max_duration=duration,
            is_running=self._is_running,
        )
        if text:
            self._print(f"🎤 {text}")
        return text

    # ── handshake ──────────────────────────────────────────────────────────

    def _mic_handshake(self):
        """Verify microphone is working before entering the listen loop.

        Asks "Can you hear me?" and waits for any audible reply. Any non-empty
        transcription is accepted — the goal is to confirm the mic captures
        audio, not to parse what was said. Strict affirmation checking caused
        consistent failures because Whisper phrases short replies unpredictably.
        """
        self._speak(P.MIC_CHECK_PROMPT)
        reply = self._listen(MIC_CHECK_DURATION)
        if not self._running:
            return False
        if reply:
            self._speak(P.MIC_CHECK_OK)
            return True
        self._speak(P.MIC_CHECK_FAIL)
        return False

    # ── states ─────────────────────────────────────────────────────────────

    def _active_step(self):
        """One iteration of active listening. Returns True if transitioning to standby."""
        utterance = self._listen(ACTIVE_LISTEN_DURATION)
        if not self._running:
            return False

        if not utterance:
            # Silence → standby.
            self._speak(P.pick(P.STANDBY))
            return True

        # Negation alone (after "anything else?") → standby.
        if P.is_negation(utterance) and not P.has_wake_word(utterance):
            self._speak(P.pick(P.STANDBY))
            return True

        # If the wake word is in there, strip it; if it's the ONLY thing,
        # speak the wake prompt and loop without going to standby.
        text_for_intent = utterance
        if P.has_wake_word(utterance):
            stripped = P.strip_wake_word(utterance)
            if not stripped:
                self._speak(P.pick(P.WAKE_PROMPT))
                # Loop straight back into active listening — same state.
                follow = self._listen(ACTIVE_LISTEN_DURATION)
                if not self._running or not follow:
                    return False
                text_for_intent = follow
            else:
                text_for_intent = stripped

        # Direct console-mode escape hatch.
        if text_for_intent.strip().lower() in ('voice off', 'voice mode off',
                                                'exit voice', 'exit voice mode'):
            self._speak(P.VOICE_OFF)
            self._running = False
            return False

        self._process_utterance(text_for_intent)
        if not self._running:
            return False

        # "Anything else?" follow-up.
        self._speak(P.pick(P.ASK_AGAIN))
        return False

    def _standby_step(self):
        """Listen for the wake word. Returns True to stay in standby."""
        # No beep in standby — the system is "sleeping" and a beep would
        # imply it's actively listening for commands.
        text = self._stt.listen(
            max_duration=STANDBY_LISTEN_DURATION,
            is_running=self._is_running,
        )
        if not self._running:
            return True
        if not text:
            return True  # remain in standby on silence

        if not P.has_wake_word(text):
            return True  # heard speech, but no wake word — stay asleep

        self._print(f"🎤 {text}")
        cmd_text = P.strip_wake_word(text)

        if not cmd_text:
            # Wake word alone — prompt and go active.
            self._speak(P.pick(P.WAKE_PROMPT))
            return False

        # Wake word + command in one utterance.
        self._process_utterance(cmd_text)
        if not self._running:
            return True
        self._speak(P.pick(P.ASK_AGAIN))
        return False

    # ── intent processing ─────────────────────────────────────────────────

    def _process_utterance(self, text):
        """Classify `text` and dispatch — handling confirm/clarify branches."""
        result = self._intents.classify(text)

        if result.status == "unclear":
            self._speak(P.pick(P.UNRECOGNIZED))
            return

        if result.status == "ok":
            self._execute(result.command)
            return

        if result.status == "needs_slot":
            self._handle_missing_slot(result)
            return

        if result.status == "confirm":
            self._handle_confirmation(result, text)
            return

    def _handle_confirmation(self, result, original_text):
        """Mid-confidence: ask 'did you mean X?' and reclassify the answer."""
        prompt = f"Did you mean: {result.intent['describe']}"
        self._speak(prompt)
        reply = self._listen(CLARIFY_LISTEN_DURATION)
        if not self._running:
            return
        if reply and P.is_affirmation(reply):
            if result.needs_slot is not None:
                # We confirmed the intent but still need the slot value.
                self._prompt_for_slot(result.intent, result.needs_slot, original_text)
                return
            self._execute(result.command)
        else:
            self._speak(P.pick(P.UNRECOGNIZED))

    def _handle_missing_slot(self, result):
        """High-confidence intent but the number/SSN was absent."""
        self._prompt_for_slot(result.intent, result.needs_slot, original_text=None)

    def _prompt_for_slot(self, intent, slot_kind, original_text):
        """Ask for a missing slot value, parse the reply, then dispatch."""
        if slot_kind == "number":
            self._speak(P.CLARIFY_NUMBER)
        elif slot_kind == "ssn":
            self._speak(P.CLARIFY_SSN)
        else:
            return

        reply = self._listen(CLARIFY_LISTEN_DURATION)
        if not self._running or not reply:
            return

        # Combine original text + reply so the slot extractor can read
        # numbers from either side ("focus feed" + "four").
        combined = (original_text or "") + " " + reply
        command = self._intents.complete_with_slot(intent, combined)
        if command is None:
            self._speak(P.pick(P.UNRECOGNIZED))
            return
        self._execute(command)

    def _execute(self, command):
        """Speak an acknowledgement and dispatch the command to the console."""
        if not command:
            return
        self._speak(P.pick(P.ACKNOWLEDGE))
        try:
            self._dispatch(command)
        except Exception as e:
            self._print(f"Voice command dispatch failed: {e}", ok=False)
            self._speak(P.pick(P.ERROR))