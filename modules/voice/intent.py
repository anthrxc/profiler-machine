# modules/voice/intent.py
# Maps free-form voice utterances onto the canonical console-command vocabulary.
#
# Approach: each console command is registered with a small bag of example
# phrases. We TF-IDF-vectorize all examples (uni- and bi-grams) and resolve
# an utterance to the nearest neighbor by cosine similarity. Slot extraction
# (feed numbers, SSNs) is regex-based after intent resolution. The classifier
# returns one of three outcomes:
#
#   HIGH confidence  → execute directly
#   MID  confidence  → ask the user "did you mean X?" and reclassify their answer
#   LOW  confidence  → reject and ask for repetition
#
# Slot-missing cases (intent matched but no number/SSN found) are surfaced
# separately so voice_mode can prompt for the missing value.

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# Confidence bands
HIGH_THRESHOLD = 0.45
LOW_THRESHOLD = 0.18


# ── Intent registry ─────────────────────────────────────────────────────────
#
# Each intent is a dict:
#   id        : stable identifier for logging
#   command   : canonical console command, possibly with {n} or {ssn} slots
#   phrases   : example utterances used for nearest-neighbor matching
#   describe  : short human-readable name for "did you mean X?" prompts
#   extract   : None | "number" | "ssn"
#   requires_admin : True if the command is gated behind admin/root login
#
# IMPORTANT: keep phrases short and natural. Long example phrases hurt TF-IDF
# similarity because each non-overlapping token dilutes the cosine score.

INTENTS = [
    # ── always-allowed ─────────────────────────────────────────────────────
    {
        "id": "help",
        "command": "help",
        "phrases": [
            "help", "show help", "help me", "list commands",
            "what can you do", "what commands are available",
            "show the commands", "command reference",
        ],
        "describe": "show help",
        "extract": None,
        "requires_admin": False,
    },
    {
        "id": "quit",
        "command": "quit",
        "phrases": [
            "quit", "shut down", "shutdown", "turn off", "exit",
            "close program", "end session", "power off", "kill the system",
        ],
        "describe": "shut down the application",
        "extract": None,
        "requires_admin": False,
    },
    {
        "id": "fullscreen",
        "command": "fullscreen",
        "phrases": [
            "fullscreen", "full screen", "enter fullscreen",
            "go fullscreen", "make it fullscreen", "maximize the window",
            "exit fullscreen", "leave fullscreen",
        ],
        "describe": "toggle fullscreen",
        "extract": None,
        "requires_admin": False,
    },
    {
        "id": "logs",
        "command": "logs",
        "phrases": [
            "show logs", "open log viewer", "view logs", "toggle logs",
            "open the logs", "show me the logs",
        ],
        "describe": "toggle the log viewer",
        "extract": None,
        "requires_admin": False,
    },
    {
        "id": "voice_off",
        "command": "voice off",
        "phrases": [
            "voice off", "disable voice", "turn off voice", "exit voice mode",
            "stop listening", "go quiet", "shut up", "be quiet",
            "deactivate voice", "leave voice mode",
        ],
        "describe": "disable voice mode",
        "extract": None,
        "requires_admin": False,
    },

    # ── tracking ───────────────────────────────────────────────────────────
    {
        "id": "track",
        "command": "track {ssn}",
        "phrases": [
            "track", "follow person", "track subject", "start tracking",
            "begin tracking", "follow this subject", "lock on to",
        ],
        "describe": "track a subject",
        "extract": "ssn",
        "requires_admin": True,
    },
    {
        "id": "untrack",
        "command": "untrack",
        "phrases": [
            "untrack", "stop tracking", "clear tracking", "stop following",
            "release subject", "drop the target",
        ],
        "describe": "stop tracking",
        "extract": None,
        "requires_admin": True,
    },

    # ── overlay debug ──────────────────────────────────────────────────────
    {
        "id": "overlay_threat",
        "command": "overlay threat",
        "phrases": [
            "overlay threat", "show threat overlay", "threat designation",
            "show as threat",
        ],
        "describe": "set debug overlay to threat",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "overlay_victim",
        "command": "overlay victim",
        "phrases": [
            "overlay victim", "show victim overlay", "victim designation",
            "show as victim",
        ],
        "describe": "set debug overlay to victim",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "overlay_perpetrator",
        "command": "overlay perpetrator",
        "phrases": [
            "overlay perpetrator", "show perpetrator overlay",
            "perpetrator designation", "show as perpetrator",
        ],
        "describe": "set debug overlay to perpetrator",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "overlay_irrelevant",
        "command": "overlay irrelevant",
        "phrases": [
            "overlay irrelevant", "show irrelevant overlay", "clear overlay",
            "reset overlay",
        ],
        "describe": "set debug overlay to irrelevant",
        "extract": None,
        "requires_admin": True,
    },

    # ── feed commands ──────────────────────────────────────────────────────
    {
        "id": "feed_focus",
        "command": "feed focus {n}",
        "phrases": [
            "focus feed", "focus on feed", "zoom in on feed", "zoom into feed",
            "show feed", "go to feed", "switch to feed", "open feed",
        ],
        "describe": "focus a feed",
        "extract": "number",
        "requires_admin": True,
    },
    {
        "id": "feed_remove",
        "command": "feed remove {n}",
        "phrases": [
            "remove feed", "delete feed", "close feed", "drop feed",
            "disconnect feed",
        ],
        "describe": "remove a feed",
        "extract": "number",
        "requires_admin": True,
    },
    {
        "id": "feed_grid",
        "command": "feed grid",
        "phrases": [
            "feed grid", "show the grid", "back to grid", "grid view",
            "show all feeds", "return to grid", "exit focus",
        ],
        "describe": "return to grid view",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "feed_list",
        "command": "feed list",
        "phrases": [
            "feed list", "list feeds", "list all feeds", "show me the feeds",
            "what feeds are active", "show active feeds",
        ],
        "describe": "list active feeds",
        "extract": None,
        "requires_admin": True,
    },

    # ── profiler database commands ─────────────────────────────────────────
    {
        "id": "profiler_list",
        "command": "profiler list",
        "phrases": [
            "profiler list", "list everyone profiled", "show me everyone",
            "show all profiles", "list all people", "who is profiled",
            "show the list of people", "list the database",
        ],
        "describe": "list everyone in the database",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "profiler_info",
        "command": "profiler info {ssn}",
        "phrases": [
            "profiler info", "tell me about", "info on", "show details for",
            "information about", "details on",
        ],
        "describe": "show profile details",
        "extract": "ssn",
        "requires_admin": True,
    },
    {
        "id": "profiler_show",
        "command": "profiler show {ssn}",
        "phrases": [
            "profiler show", "show profile", "display profile", "open profile",
            "pull up profile for", "show me profile",
        ],
        "describe": "open a profile in the panel",
        "extract": "ssn",
        "requires_admin": True,
    },
    {
        "id": "profiler_toggle",
        "command": "profiler toggle",
        "phrases": [
            "profiler toggle", "toggle profiler panel", "open profiler panel",
            "hide profiler", "close profiler", "show profiler panel",
        ],
        "describe": "toggle the profiler panel",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "profiler_start",
        "command": "profiler start",
        "phrases": [
            "profiler start", "start the profiler", "begin profiling",
            "activate profiler", "start scanning faces",
        ],
        "describe": "start the profiler",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "profiler_stop",
        "command": "profiler stop",
        "phrases": [
            "profiler stop", "stop the profiler", "deactivate profiler",
            "pause profiler", "stop scanning",
        ],
        "describe": "stop the profiler",
        "extract": None,
        "requires_admin": True,
    },

    # ── alert engine ───────────────────────────────────────────────────────
    {
        "id": "alert_list",
        "command": "alert list",
        "phrases": [
            "alert list", "list alerts", "show alerts", "list all alerts",
            "what alerts are active", "show the alert rules",
        ],
        "describe": "list alert rules",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "alert_mute_all",
        "command": "alert mute",
        "phrases": [
            "mute all alerts", "silence alerts", "mute alerts",
            "stop alerts", "disable alerts",
        ],
        "describe": "mute all alerts",
        "extract": None,
        "requires_admin": True,
    },
    {
        "id": "alert_unmute_all",
        "command": "alert unmute",
        "phrases": [
            "unmute alerts", "unmute all alerts", "enable alerts",
            "restore alerts",
        ],
        "describe": "unmute all alerts",
        "extract": None,
        "requires_admin": True,
    },
]


# ── Slot extractors ─────────────────────────────────────────────────────────

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def extract_number(text):
    """First digit-string OR number-word found in `text`, else None."""
    if not text:
        return None
    m = re.search(r"\b(\d{1,4})\b", text)
    if m:
        return int(m.group(1))
    for word, num in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            return num
    return None


def extract_ssn(text):
    """Match SSN-shaped substring in any of: 123-45-6789, 123 45 6789, 123456789."""
    if not text:
        return None
    m = re.search(r"\b(\d{3})[-\s]?(\d{2})[-\s]?(\d{4})\b", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


# ── Classifier ──────────────────────────────────────────────────────────────

class ClassifyResult:
    """Outcome of a single classification attempt."""

    __slots__ = ('intent', 'command', 'confidence', 'status', 'needs_slot')

    # status values:
    #   "ok"            → command is final, dispatch it
    #   "confirm"       → mid-confidence: ask "did you mean X?"
    #   "needs_slot"    → high-confidence but slot missing; needs_slot is
    #                     "number" or "ssn"
    #   "unclear"       → below low threshold; reject and ask for repeat

    def __init__(self, intent=None, command=None, confidence=0.0,
                 status="unclear", needs_slot=None):
        self.intent = intent
        self.command = command
        self.confidence = confidence
        self.status = status
        self.needs_slot = needs_slot


class IntentClassifier:
    """TF-IDF + cosine-similarity intent matcher over `INTENTS`."""

    def __init__(self):
        self._intents = INTENTS
        self._phrases = []
        self._phrase_to_idx = []  # parallel: phrase i → intents[idx]
        for i, intent in enumerate(self._intents):
            for phrase in intent["phrases"]:
                self._phrases.append(phrase)
                self._phrase_to_idx.append(i)

        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            token_pattern=r"\b[a-z]+\b",
        )
        self._matrix = self._vectorizer.fit_transform(self._phrases)

    def _resolve_slot(self, intent, command, text):
        """Fill {n}/{ssn} placeholders in `command` using `text`. Returns
        (filled_command, missing_slot_or_None)."""
        slot = intent.get("extract")
        if slot is None:
            return command, None
        if slot == "number":
            n = extract_number(text)
            if n is None:
                return None, "number"
            return command.replace("{n}", str(n)), None
        if slot == "ssn":
            ssn = extract_ssn(text)
            if ssn is None:
                return None, "ssn"
            return command.replace("{ssn}", ssn), None
        return command, None

    def classify(self, text):
        """Classify `text` to a console command. Returns a ClassifyResult."""
        if not text or not text.strip():
            return ClassifyResult(status="unclear")

        vec = self._vectorizer.transform([text.lower()])
        scores = cosine_similarity(vec, self._matrix).flatten()

        # Aggregate scores per intent — take the best example phrase from
        # each intent rather than letting one intent's many phrases drown
        # out another's single strong match.
        best_per_intent = {}
        for phrase_i, intent_i in enumerate(self._phrase_to_idx):
            s = float(scores[phrase_i])
            if s > best_per_intent.get(intent_i, -1.0):
                best_per_intent[intent_i] = s

        if not best_per_intent:
            return ClassifyResult(status="unclear")

        # Sort intents by best-phrase score, descending.
        ranked = sorted(best_per_intent.items(), key=lambda kv: kv[1], reverse=True)
        top_idx, top_score = ranked[0]
        top_intent = self._intents[top_idx]

        if top_score < LOW_THRESHOLD:
            return ClassifyResult(
                intent=top_intent,
                confidence=top_score,
                status="unclear",
            )

        filled, missing_slot = self._resolve_slot(top_intent, top_intent["command"], text)

        if top_score >= HIGH_THRESHOLD:
            if missing_slot is not None:
                return ClassifyResult(
                    intent=top_intent,
                    confidence=top_score,
                    status="needs_slot",
                    needs_slot=missing_slot,
                )
            return ClassifyResult(
                intent=top_intent,
                command=filled,
                confidence=top_score,
                status="ok",
            )

        # Mid-band → ask for confirmation. We still record the candidate
        # command and slot status so voice_mode can complete it on "yes".
        return ClassifyResult(
            intent=top_intent,
            command=filled,
            confidence=top_score,
            status="confirm",
            needs_slot=missing_slot,
        )

    def complete_with_slot(self, intent, slot_text):
        """Given a previously-matched intent and the user's reply to a
        clarifying slot prompt, return the filled command or None."""
        if intent is None:
            return None
        filled, missing = self._resolve_slot(intent, intent["command"], slot_text)
        if missing is not None:
            return None
        return filled
