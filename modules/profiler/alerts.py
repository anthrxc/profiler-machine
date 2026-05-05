# modules/profiler/alerts.py
# Alert rules engine — evaluates conditions against live detection results
# and fires console messages, sounds, and feed overlay cards.

import sqlite3
import os
import threading
import time
import queue

DB_PATH          = os.path.join('database', 'profm.sqlite')
ALERT_SOUND_PATH = os.path.join('assets', 'audio', 'alert.wav')
ALERT_COOLDOWN   = 30.0   # seconds before the same rule can fire again
EVAL_INTERVAL    = 0.5    # seconds between evaluation cycles


# ─────────────────────────────────────────────────────────────────────────────
# Condition types
# ─────────────────────────────────────────────────────────────────────────────

class Condition:
    """Base class for all alert conditions."""
    def describe(self) -> str:
        raise NotImplementedError

    def evaluate(self, feed_results: dict, db) -> list:
        """
        feed_results: {feed_id: [result_dicts]}
        Returns list of (feed_id, [trigger_ssns]) for every feed where the
        condition is met, or [] if not triggered anywhere.
        """
        raise NotImplementedError


class DesignationCondition(Condition):
    """Fires when any face with a given designation is present in any feed."""
    def __init__(self, designation: str):
        self.designation = designation

    def describe(self):
        return f"designation:{self.designation}"

    def evaluate(self, feed_results, db):
        hits = []
        for feed_id, results in feed_results.items():
            ssns = [r['ssn'] for r in results
                    if r.get('ssn') and r.get('designation') == self.designation]
            if ssns:
                hits.append((feed_id, ssns))
        return hits


class CoPresenceCondition(Condition):
    """Fires when two designations appear together in the SAME feed."""
    def __init__(self, designation_a: str, designation_b: str):
        self.designation_a = designation_a
        self.designation_b = designation_b

    def describe(self):
        return f"co-presence:{self.designation_a}+{self.designation_b}"

    def evaluate(self, feed_results, db):
        hits = []
        for feed_id, results in feed_results.items():
            desigs = {r.get('designation') for r in results if r.get('ssn')}
            if self.designation_a in desigs and self.designation_b in desigs:
                ssns = [r['ssn'] for r in results
                        if r.get('ssn') and r.get('designation')
                        in (self.designation_a, self.designation_b)]
                hits.append((feed_id, ssns))
        return hits


class SSNCondition(Condition):
    """Fires when a specific SSN is detected in any feed."""
    def __init__(self, ssn: str):
        self.ssn = ssn

    def describe(self):
        return f"ssn:{self.ssn}"

    def evaluate(self, feed_results, db):
        hits = []
        for feed_id, results in feed_results.items():
            ssns = [r['ssn'] for r in results if r.get('ssn') == self.ssn]
            if ssns:
                hits.append((feed_id, ssns))
        return hits


def parse_condition(parts: list):
    """
    Parse a condition from console tokens.
    Supported syntax:
      designation <desig>
      co-presence <desig_a> <desig_b>
      ssn <SSN>
    Returns a Condition or raises ValueError.
    """
    if not parts:
        raise ValueError("No condition specified.")

    kind = parts[0].lower()

    if kind == 'designation':
        if len(parts) < 2:
            raise ValueError("Usage: alert add designation <designation>")
        return DesignationCondition(parts[1].lower())

    elif kind == 'co-presence':
        if len(parts) < 3:
            raise ValueError("Usage: alert add co-presence <designation_a> <designation_b>")
        return CoPresenceCondition(parts[1].lower(), parts[2].lower())

    elif kind == 'ssn':
        if len(parts) < 2:
            raise ValueError("Usage: alert add ssn <SSN>")
        return SSNCondition(parts[1])

    else:
        raise ValueError(
            f"Unknown condition type '{kind}'. "
            "Use: designation / co-presence / ssn"
        )


def condition_from_db(ctype: str, cvalue: str) -> Condition:
    """Reconstruct a Condition from its DB-stored type/value strings."""
    if ctype == 'designation':
        return DesignationCondition(cvalue)
    elif ctype == 'co-presence':
        a, b = cvalue.split('+', 1)
        return CoPresenceCondition(a, b)
    elif ctype == 'ssn':
        return SSNCondition(cvalue)
    raise ValueError(f"Unknown condition type in DB: {ctype}")


def condition_to_db(cond: Condition):
    """Return (ctype, cvalue) strings for DB storage."""
    desc = cond.describe()
    ctype, cvalue = desc.split(':', 1)
    return ctype, cvalue


# ─────────────────────────────────────────────────────────────────────────────
# AlertRule
# ─────────────────────────────────────────────────────────────────────────────

class AlertRule:
    def __init__(self, rule_id: int, condition: Condition,
                 sound_path: str = ALERT_SOUND_PATH, muted: bool = False,
                 created_by: str | None = None):
        self.rule_id    = rule_id
        self.condition  = condition
        self.sound_path = sound_path
        self.muted      = muted
        self.created_by = created_by
        self._last_fired = {}   # {feed_id: timestamp}

    def is_cooled_down(self, feed_id) -> bool:
        last = self._last_fired.get(feed_id, 0)
        return time.time() - last >= ALERT_COOLDOWN

    def mark_fired(self, feed_id):
        self._last_fired[feed_id] = time.time()

    def cooldown_remaining(self, feed_id) -> float:
        last = self._last_fired.get(feed_id, 0)
        return max(0.0, ALERT_COOLDOWN - (time.time() - last))


# ─────────────────────────────────────────────────────────────────────────────
# Active alert (overlay state)
# ─────────────────────────────────────────────────────────────────────────────

ALERT_DISPLAY_SECONDS = 5.0

class ActiveAlert:
    """Tracks a live overlay alert on a specific feed."""
    def __init__(self, rule: AlertRule, feed_id: int, trigger_ssns: list,
                 db, label: str):
        self.rule         = rule
        self.feed_id      = feed_id
        self.trigger_ssns = trigger_ssns
        self.label        = label
        self.born_at      = time.time()

        # Resolve detected subjects from DB. main_window.py expects:
        #   alert.subjects -> [(name, ssn, designation), ...]
        self.names = []
        self.subjects = []
        for ssn in trigger_ssns:
            person = db.get_by_ssn(ssn)
            if person:
                name = person[2] or ssn
                designation = person[3] or "unknown"
            else:
                name = ssn
                designation = "unknown"

            self.names.append(name)
            self.subjects.append((name, ssn, designation))

        # Resolve the operator who created the rule. main_window.py expects:
        #   alert.created_by_name
        self.created_by_name = "UNKNOWN"
        if rule.created_by:
            creator = db.get_by_ssn(rule.created_by)
            if creator:
                self.created_by_name = creator[2] or rule.created_by
            else:
                self.created_by_name = rule.created_by

    @property
    def alpha(self) -> float:
        """0.0 → 1.0, fades out in last 2 seconds."""
        age = time.time() - self.born_at
        if age >= ALERT_DISPLAY_SECONDS:
            return 0.0
        fade_start = ALERT_DISPLAY_SECONDS - 2.0
        if age > fade_start:
            return 1.0 - (age - fade_start) / 2.0
        return 1.0

    @property
    def expired(self) -> bool:
        return time.time() - self.born_at >= ALERT_DISPLAY_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
# AlertEngine
# ─────────────────────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Owns alert rules and runs a background evaluation loop.
    Plugs into Designator's _latest_results and FeedManager's console callback.
    """

    def __init__(self, db, designator, console_cb, play_sound_cb):
        """
        db            — RecognitionDB instance
        designator    — Designator instance (for _latest_results)
        console_cb    — callable(str, ok=True) to print to the console
        play_sound_cb — callable(path) to play a sound file
        """
        self._db           = db
        self._designator   = designator
        self._console_cb   = console_cb
        self._play_sound   = play_sound_cb

        self._rules        = []          # list[AlertRule]
        self._rules_lock   = threading.Lock()

        self._active_alerts = []         # list[ActiveAlert]
        self._alerts_lock   = threading.Lock()

        self._muted_global  = False
        self._next_id       = 1
        self._conn          = None
        self._console_queue = queue.Queue()

        self._running = True
        self._thread  = threading.Thread(target=self._eval_loop, daemon=True)

    def start(self):
        self._connect_db()
        self._load_rules()
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ DB

    def _connect_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS alert_rules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ctype       TEXT NOT NULL,
                cvalue      TEXT NOT NULL,
                sound_path  TEXT,
                muted       INTEGER NOT NULL DEFAULT 0,
                created_by  TEXT
            )
        ''')
        # Migrate existing tables that predate the created_by column
        cols = {row[1] for row in self._conn.execute('PRAGMA table_info(alert_rules)')}
        if 'created_by' not in cols:
            self._conn.execute('ALTER TABLE alert_rules ADD COLUMN created_by TEXT')
        self._conn.commit()

    def _load_rules(self):
        rows = self._conn.execute(
            'SELECT id, ctype, cvalue, sound_path, muted, created_by FROM alert_rules ORDER BY id'
        ).fetchall()
        rules = []
        for row in rows:
            rid, ctype, cvalue, sound_path, muted, created_by = row
            try:
                cond = condition_from_db(ctype, cvalue)
                rules.append(AlertRule(rid, cond,
                                       sound_path or ALERT_SOUND_PATH,
                                       bool(muted), created_by))
                self._next_id = max(self._next_id, rid + 1)
            except Exception as e:
                print(f"[AlertEngine] Failed to load rule {rid}: {e}")
        with self._rules_lock:
            self._rules = sorted(rules, key=lambda r: r.rule_id)
        self.reorder_rules()

    def _save_rule(self, rule: AlertRule) -> int:
        ctype, cvalue = condition_to_db(rule.condition)
        cur = self._conn.execute(
            'INSERT INTO alert_rules (id, ctype, cvalue, sound_path, muted, created_by) VALUES (?,?,?,?,?,?)',
            (rule.rule_id, ctype, cvalue, rule.sound_path, int(rule.muted), rule.created_by)
        )
        self._conn.commit()
        return rule.rule_id

    def _delete_rule_db(self, rule_id: int):
        self._conn.execute('DELETE FROM alert_rules WHERE id=?', (rule_id,))
        self._conn.commit()

    def _update_muted_db(self, rule_id: int, muted: bool):
        self._conn.execute('UPDATE alert_rules SET muted=? WHERE id=?',
                           (int(muted), rule_id))
        self._conn.commit()

    # ------------------------------------------------------------------ API

    def add_rule(self, condition: Condition,
                 sound_path: str = ALERT_SOUND_PATH,
                 created_by: str | None = None) -> AlertRule:
        self.reorder_rules()
        rule = AlertRule(self._next_id, condition, sound_path, created_by=created_by)
        rid  = self._save_rule(rule)
        rule.rule_id = rid
        with self._rules_lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.rule_id)
            self._next_id = len(self._rules) + 1
        return rule

    def reorder_rules(self) -> list:
        """
        Renumber all rules sequentially (1, 2, 3, ...) in memory and in the DB.
        Returns list of (old_id, new_id) pairs for confirmation output.
        """
        with self._rules_lock:
            self._rules.sort(key=lambda r: r.rule_id)
            mapping = []

            for new_id, rule in enumerate(self._rules, start=1):
                old_id = rule.rule_id
                if old_id != new_id:
                    mapping.append((old_id, new_id))
                    self._conn.execute(
                        'UPDATE alert_rules SET id=? WHERE id=?',
                        (-old_id, old_id)
                    )

            for old_id, new_id in mapping:
                self._conn.execute(
                    'UPDATE alert_rules SET id=? WHERE id=?',
                    (new_id, -old_id)
                )

            for new_id, rule in enumerate(self._rules, start=1):
                rule.rule_id = new_id

            try:
                self._conn.execute(
                    "UPDATE sqlite_sequence SET seq=? WHERE name='alert_rules'",
                    (len(self._rules),)
                )
            except sqlite3.OperationalError:
                pass
            self._conn.commit()
            self._next_id = len(self._rules) + 1
        return mapping

    def remove_rule(self, rule_id: int) -> bool:
        with self._rules_lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.rule_id != rule_id]
            removed = len(self._rules) < before
        if removed:
            self._delete_rule_db(rule_id)
            self.reorder_rules()
        return removed

    def list_rules(self) -> list:
        with self._rules_lock:
            return list(self._rules)

    def mute_rule(self, rule_id: int) -> bool:
        return self._set_muted(rule_id, True)

    def unmute_rule(self, rule_id: int) -> bool:
        return self._set_muted(rule_id, False)

    def mute_all(self):
        self._muted_global = True

    def unmute_all(self):
        self._muted_global = False

    def _set_muted(self, rule_id: int, muted: bool) -> bool:
        with self._rules_lock:
            for rule in self._rules:
                if rule.rule_id == rule_id:
                    rule.muted = muted
                    self._update_muted_db(rule_id, muted)
                    return True
        return False

    def get_active_alerts(self, feed_id: int) -> list:
        """Return current non-expired ActiveAlerts for a given feed."""
        with self._alerts_lock:
            return [a for a in self._active_alerts
                    if a.feed_id == feed_id and not a.expired]

    def flush_console_queue(self):
        """Flush alert console messages on the UI/main thread."""
        while True:
            try:
                text, ok = self._console_queue.get_nowait()
            except queue.Empty:
                break
            self._console_cb(text, ok=ok)

    # ------------------------------------------------------------------ loop

    def _eval_loop(self):
        while self._running:
            try:
                self._evaluate()
            except Exception as e:
                print(f"[AlertEngine] Eval error: {e}")

            # Prune expired alerts
            with self._alerts_lock:
                self._active_alerts = [a for a in self._active_alerts
                                       if not a.expired]

            time.sleep(EVAL_INTERVAL)

    def _evaluate(self):
        # Snapshot current results per feed
        with self._designator._lock:
            feed_results = {fid: list(results)
                            for fid, results in self._designator._latest_results.items()}

        if not feed_results:
            return

        with self._rules_lock:
            rules = list(self._rules)

        for rule in rules:
            hits = rule.condition.evaluate(feed_results, self._db)
            for feed_id, trigger_ssns in hits:
                if not rule.is_cooled_down(feed_id):
                    continue

                rule.mark_fired(feed_id)

                # Build human-readable label
                label = self._build_label(rule.condition, trigger_ssns)
                self._console_queue.put((
                    f"⚠ ALERT  [Rule {rule.rule_id}]  Feed {feed_id}  —  {label}",
                    False
                ))

                # Sound
                if not rule.muted and not self._muted_global:
                    if os.path.exists(rule.sound_path):
                        import threading as _t
                        _t.Thread(
                            target=self._play_sound,
                            args=(rule.sound_path,),
                            daemon=True
                        ).start()

                # Queue overlay alert
                alert = ActiveAlert(rule, feed_id, trigger_ssns,
                                    self._db, label)
                with self._alerts_lock:
                    self._active_alerts.append(alert)

    def _build_label(self, condition: Condition, trigger_ssns: list) -> str:
        names = []
        for ssn in trigger_ssns[:3]:
            person = self._db.get_by_ssn(ssn)
            names.append((person[2] or ssn).upper() if person else ssn)
        suffix = f"  [{', '.join(names)}]" if names else ""

        if isinstance(condition, DesignationCondition):
            return f"{condition.designation.upper()} DETECTED{suffix}"
        elif isinstance(condition, CoPresenceCondition):
            return (f"{condition.designation_a.upper()} + "
                    f"{condition.designation_b.upper()} CO-PRESENT{suffix}")
        elif isinstance(condition, SSNCondition):
            return f"SUBJECT {condition.ssn} IN FRAME{suffix}"
        return condition.describe()