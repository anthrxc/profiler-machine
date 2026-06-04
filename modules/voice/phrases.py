# modules/voice/phrases.py
# Response phrase pools and natural-language pattern detectors used by
# the voice mode controller. Phrases are kept short — every utterance is
# synthesized word-by-word and longer ones drag.

import random
import re


# ── Response pools ──────────────────────────────────────────────────────────

ACKNOWLEDGE = [
    "Processing",
    "Right away",
    "Working on it",
    "Acknowledged",
    "Confirmed",
    "Stand by",
    "On it",
    "Affirmative",
]

ASK_AGAIN = [
    "Anything else",
    "Awaiting next command",
    "Standing by",
    "Ready for more",
    "What else",
    "Continue",
]

WAKE_PROMPT = [
    "What are your commands",
    "I am listening",
    "Awaiting input",
    "Ready",
    "Speak",
]

STANDBY = [
    "Going to standby",
    "Entering standby",
    "Dismissed",
    "Standing down",
    "Awaiting wake word",
]

UNRECOGNIZED = [
    "Command unclear",
    "I did not understand",
    "Please clarify",
    "Repeat that",
]

EXECUTED = [
    "Done",
    "Complete",
    "Finished",
    "Executed",
]

ERROR = [
    "An error occurred",
    "Command failed",
    "Unable to comply",
]


# ── Fixed prompts ───────────────────────────────────────────────────────────

MIC_CHECK_PROMPT = "Can you hear me"
MIC_CHECK_FAIL = "I can not hear you. Disabling voice mode."
MIC_CHECK_OK = "Voice mode online"

CLARIFY_NUMBER = "Which one"
CLARIFY_SSN = "Provide the identification number"

VOICE_OFF = "Voice mode off"


# ── Pre-warm word list ──────────────────────────────────────────────────────

# All distinct words used in the fixed prompts and response pools above.
# Prewarming these on first voice-mode activation eliminates audible
# cache-miss latency in the first few utterances.

def all_response_words():
    pools = [
        ACKNOWLEDGE, ASK_AGAIN, WAKE_PROMPT, STANDBY,
        UNRECOGNIZED, EXECUTED, ERROR,
    ]
    fixed = [
        MIC_CHECK_PROMPT, MIC_CHECK_FAIL, MIC_CHECK_OK,
        CLARIFY_NUMBER, CLARIFY_SSN, VOICE_OFF,
    ]
    words = set()

    def add(phrase):
        for w in phrase.split():
            # Match the normalization used by VoiceTTS so the cache keys align.
            clean = re.sub(r"[^a-z0-9\-']", '', w.lower())
            if clean:
                words.add(clean)

    for pool in pools:
        for phrase in pool:
            add(phrase)
    for phrase in fixed:
        add(phrase)
    # Include the common confirm/deny tokens used in clarification dialogs.
    for extra in ('yes', 'no', 'did', 'you', 'mean'):
        words.add(extra)
    return sorted(words)


# ── Pickers ─────────────────────────────────────────────────────────────────

def pick(pool):
    return random.choice(pool)


# ── Lightweight intent detectors used by voice_mode ────────────────────────

_AFFIRM_TOKENS = {
    'yes', 'yeah', 'yep', 'yup', 'affirmative', 'sure', 'absolutely',
    'correct', 'right', 'okay', 'ok', 'go', 'proceed', 'confirm',
}
_NEGATE_TOKENS = {
    'no', 'nope', 'negative', 'cancel', 'stop', 'nah', 'nevermind',
    'never', 'incorrect', 'wrong',
}


def _tokens(text):
    return re.findall(r"[a-z']+", text.lower())


def is_affirmation(text):
    toks = _tokens(text)
    if not toks:
        return False
    # First token must be affirmative — "are you sure" should NOT count as
    # affirmation even though "sure" is in the affirm set.
    return toks[0] in _AFFIRM_TOKENS


def is_negation(text):
    toks = _tokens(text)
    if not toks:
        return False
    return toks[0] in _NEGATE_TOKENS


# ── Wake-word detection ──────────────────────────────────────────────────────
#
# Wake word: "Machine" — fits the POI theme and Whisper transcribes it
# reliably. Common mishearings/variants are listed below.

_WAKE_WORD = 'machine'

_WAKE_VARIANTS_EXACT = {
    'machine', 'the machine', 'machines',
}

# Single-token variants Whisper occasionally produces
_WAKE_VARIANTS_TOKEN = {
    'machine', 'machines',
}


def _levenshtein(a, b, cap=3):
    """Bounded Levenshtein. Returns cap+1 when distance exceeds cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
            row_min = min(row_min, cur[j])
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def has_wake_word(text):
    """True if `text` likely contains the wake word."""
    if not text:
        return False
    lowered = re.sub(r"[^a-z\s]", ' ', text.lower())
    for variant in _WAKE_VARIANTS_EXACT:
        if variant in lowered:
            return True
    for token in lowered.split():
        if token in _WAKE_VARIANTS_TOKEN:
            return True
        if _levenshtein(token, _WAKE_WORD, cap=2) <= 2:
            return True
    return False


def strip_wake_word(text):
    """Remove the leading wake-word occurrence so only the command remains."""
    if not text:
        return ""
    lowered = text.lower()
    for variant in sorted(_WAKE_VARIANTS_EXACT, key=len, reverse=True):
        idx = lowered.find(variant)
        if idx != -1:
            after = text[idx + len(variant):]
            return re.sub(r"^[\s,.;:!?-]+", "", after).strip()
    parts = text.split(None, 1)
    if parts and _levenshtein(re.sub(r"[^a-z]", "", parts[0].lower()), _WAKE_WORD, cap=2) <= 2:
        return parts[1] if len(parts) > 1 else ""
    return text.strip()