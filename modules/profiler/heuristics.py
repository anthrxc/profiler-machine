# modules/profiler/heuristics.py
# Generates fake-but-consistent ML heuristic metrics per subject.
# Values are seeded by SSN for determinism; a slow sinusoidal jitter
# makes them flicker as if produced by a live inference pipeline.

import hashlib
import math
import random
import time


BEHAVIORAL_TAGS = [
    "COUNTER-SURVEILLANCE",
    "LOITERING",
    "RAPID BEARING CHANGE",
    "DEAD DROP INDICATOR",
    "PERIMETER FIXATION",
    "CONCEALMENT POSTURE",
    "PATTERN DEVIATION",
    "OVERWATCH BEHAVIOR",
    "CONTACT AVOIDANCE",
    "STRESS MARKERS",
    "PHONE FIXATION",
    "ERRATIC GAIT",
]


def _seed(ssn: str) -> int:
    return int(hashlib.md5(ssn.encode()).hexdigest()[:8], 16)


def generate(ssn: str, designation: str) -> dict:
    """
    Generate a heuristic profile for a subject.

    Returns a dict with:
        bri         — Behavioral Risk Index, 0-99
        micro       — Micro-expression anomaly score, 0-99
        gait        — 'LOW' | 'MODERATE' | 'HIGH'
        network     — int, number of flagged network associates
        tag         — str or None, primary behavioral flag
        xref        — int, cross-reference hit count
    """
    s = _seed(ssn)
    rng = random.Random(s)
    t = time.time()

    # ── Behavioral Risk Index ─────────────────────────────────────────────────
    base_bri = {
        'root':        rng.randint(2,  10),
        'admin':       rng.randint(8,  22),
        'irrelevant':  rng.randint(3,  16),
        'victim':      rng.randint(28, 46),
        'perpetrator': rng.randint(62, 80),
        'threat':      rng.randint(80, 95),
    }.get(designation, rng.randint(5, 20))

    # Slow sinusoidal jitter (±4) — looks like live model output
    bri_jitter = int(math.sin(t * 0.23 + s % 97) * 4)
    bri = max(0, min(99, base_bri + bri_jitter))

    # ── Micro-expression anomaly ──────────────────────────────────────────────
    micro_base = {
        'threat':       rng.randint(62, 88),
        'perpetrator':  rng.randint(44, 68),
        'victim':       rng.randint(22, 50),
        'irrelevant':   rng.randint(3,  20),
        'admin':        rng.randint(6,  26),
        'root':         rng.randint(1,  12),
    }.get(designation, rng.randint(5, 25))
    micro_jitter = int(math.sin(t * 0.17 + (s >> 4) % 100) * 3)
    micro = max(0, min(99, micro_base + micro_jitter))

    # ── Gait deviation ────────────────────────────────────────────────────────
    gait_r = rng.randint(0, 99)
    if designation in ('threat', 'perpetrator'):
        gait_r = max(gait_r, rng.randint(40, 85))
    elif designation in ('root', 'admin', 'irrelevant'):
        gait_r = min(gait_r, rng.randint(0, 28))
    gait = 'LOW' if gait_r < 34 else 'MODERATE' if gait_r < 67 else 'HIGH'

    # ── Network degree ────────────────────────────────────────────────────────
    network = {
        'threat':       rng.randint(6,  20),
        'perpetrator':  rng.randint(3,  14),
        'victim':       rng.randint(1,   8),
        'irrelevant':   rng.randint(0,   4),
        'admin':        rng.randint(4,  12),
        'root':         rng.randint(0,   3),
    }.get(designation, rng.randint(0, 5))

    # ── Behavioral tag ────────────────────────────────────────────────────────
    tag = rng.choice(BEHAVIORAL_TAGS) if bri > 22 else None

    # ── Cross-reference hits ──────────────────────────────────────────────────
    xref = (rng.randint(0, 3)
            if designation in ('irrelevant', 'root')
            else rng.randint(1, 9))

    return {
        'bri':     bri,
        'micro':   micro,
        'gait':    gait,
        'network': network,
        'tag':     tag,
        'xref':    xref,
    }


def bri_rgb(bri: int) -> tuple:
    """Return an (R, G, B) color for a BRI value."""
    if bri < 30:
        return (60, 200, 80)
    elif bri < 60:
        return (220, 165, 30)
    else:
        return (220, 55, 55)


# ── Neutralization monitor ────────────────────────────────────────────────────

NEUTRALIZABLE   = {'threat', 'victim', 'perpetrator'}
BRI_THRESHOLD   = 25     # BRI must stay below this
SUSTAIN_SECS    = 30     # for this many consecutive seconds


class NeutralizationMonitor:
    """
    Accumulates in-frame seconds where BRI < threshold.

    Clock rules:
      - In frame + BRI low  -> clock runs
      - Out of frame         -> clock pauses
      - Out of frame > OUT_RESET_SECS -> full reset (subject went cold)
      - BRI rises above threshold -> full reset

    Fires True exactly once when accumulated in-frame seconds >= SUSTAIN_SECS.
    Call reset(ssn) after operator confirms to re-arm for future detections.
    """

    OUT_RESET_SECS = 300   # 5 minutes absent = forget the clock

    def __init__(self):
        self._accum:      dict = {}   # ssn -> accumulated in-frame seconds below threshold
        self._in_since:   dict = {}   # ssn -> wall-clock time subject entered current in-frame stretch
        self._out_since:  dict = {}   # ssn -> wall-clock time subject left frame
        self._suggested:  set  = set()

    def check(self, ssn: str, designation: str, bri: int, in_frame: bool) -> bool:
        if designation not in NEUTRALIZABLE:
            self._clear(ssn)
            return False
        if ssn in self._suggested:
            return False

        now = time.time()

        # Check long absence reset
        if ssn in self._out_since:
            if now - self._out_since[ssn] >= self.OUT_RESET_SECS:
                self._clear(ssn)
                return False

        # BRI rose above threshold -- full reset
        if bri >= BRI_THRESHOLD:
            self._clear(ssn)
            return False

        # BRI is low -- handle presence transitions
        if in_frame:
            if ssn in self._out_since:
                # Returning to frame -- resume clock, discard out timestamp
                del self._out_since[ssn]

            if ssn not in self._in_since:
                # Fresh or resumed stretch
                self._in_since[ssn] = now
                if ssn not in self._accum:
                    self._accum[ssn] = 0.0

            # Accumulate elapsed time in this stretch
            elapsed = now - self._in_since[ssn]
            total   = self._accum.get(ssn, 0.0) + elapsed
            self._in_since[ssn] = now   # advance window

            if total >= SUSTAIN_SECS:
                self._suggested.add(ssn)
                self._clear(ssn)
                return True

            self._accum[ssn] = total

        else:
            # Left frame -- pause clock
            if ssn in self._in_since:
                elapsed = now - self._in_since[ssn]
                self._accum[ssn] = self._accum.get(ssn, 0.0) + elapsed
                del self._in_since[ssn]
            if ssn not in self._out_since and ssn in self._accum:
                self._out_since[ssn] = now

        return False

    def _clear(self, ssn: str):
        self._accum.pop(ssn, None)
        self._in_since.pop(ssn, None)
        self._out_since.pop(ssn, None)

    def reset(self, ssn: str):
        """Re-arm after operator neutralizes."""
        self._suggested.discard(ssn)
        self._clear(ssn)