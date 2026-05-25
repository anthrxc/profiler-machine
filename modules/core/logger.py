# modules/core/logger.py
# Global application logger — thread-safe in-memory log store with stdout intercept
# and continuous persistence to logs/profiler_machine.log.

import sys
import os
import time
import threading
import re
from collections import deque

# ── Constants ────────────────────────────────────────────────────────────────

LEVELS  = ['debug', 'info', 'warning', 'error']
MODULES = ['system', 'feeds', 'recognition', 'alerts', 'antispoof', 'console', 'ui', 'auth']

MAX_ENTRIES  = 5000   # in-memory cap
MAX_LOAD     = 5000   # lines to load from file on startup

# Map normalised [Prefix] tag → module bucket
_PREFIX_MAP = {
    'feedmanager':   'feeds',
    'feedsconfig':   'feeds',
    'videostream':   'feeds',
    'designator':    'recognition',
    'recognition':   'recognition',
    'bodydetector':  'recognition',
    'antispoof':     'antispoof',
    'alertengine':   'alerts',
    'profilerpanel': 'ui',
    'mainwindow':    'ui',
    'startup':       'system',
    'console':       'console',
    'auth':          'auth',
}

_PREFIX_RE = re.compile(r'^\[([^\]]+)\]\s*')

# Persistent file line format (pipe-separated, message last so | inside is safe):
#   {epoch:.3f}|{level}|{module}|{message}
_SEP = '|'


# ── Singleton ────────────────────────────────────────────────────────────────

class AppLogger:
    """Thread-safe singleton logger with stdout intercept and file persistence."""

    _instance    = None
    _class_lock  = threading.Lock()

    def __new__(cls):
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._entries              = deque(maxlen=MAX_ENTRIES)
                inst._lock                 = threading.Lock()
                inst._real_out             = sys.stdout
                inst._real_err             = sys.stderr
                inst._intercept_installed  = False
                inst._log_file             = None
                inst._write_count          = 0
                cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------ intercept

    def install_intercept(self):
        """Redirect stdout/stderr so all print() output is captured.
        Safe to call multiple times — only installs once.
        """
        if self._intercept_installed:
            return

        logger = self

        class _Stream:
            def __init__(self, real, default_level):
                self._real  = real
                self._level = default_level
                self._buf   = ''

            def write(self, text):
                self._real.write(text)
                self._buf += text
                while '\n' in self._buf:
                    line, self._buf = self._buf.split('\n', 1)
                    line = line.rstrip('\r')
                    if line.strip():
                        logger._ingest(line, self._level)

            def flush(self):
                self._real.flush()

            def fileno(self):
                try:   return self._real.fileno()
                except Exception: return -1

            def isatty(self):
                try:   return self._real.isatty()
                except Exception: return False

        sys.stdout = _Stream(self._real_out, 'info')
        sys.stderr = _Stream(self._real_err, 'error')
        self._intercept_installed = True

    # ------------------------------------------------------------------ file persistence

    def open_log_file(self, path):
        """Open (or create) the persistent log file and load previous entries.
        Call once in main.py after install_intercept().
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._load_from_file(path)
            self._log_file = open(path, 'a', encoding='utf-8', buffering=1)
        except Exception as e:
            # Non-fatal — logging still works in-memory
            print(f"[Logger] Could not open log file '{path}': {e}")

    def _load_from_file(self, path):
        """Parse the persistent log file and populate the in-memory deque."""
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            # Load only the last MAX_LOAD lines to avoid memory bloat
            for raw in lines[-MAX_LOAD:]:
                raw = raw.rstrip('\n\r')
                if not raw or raw.startswith('#'):
                    continue
                parts = raw.split(_SEP, 3)
                if len(parts) != 4:
                    continue
                ts_str, level, module, message = parts
                try:
                    ts = float(ts_str)
                except ValueError:
                    continue
                entry = {
                    'ts':       ts,
                    'time_str': time.strftime('%H:%M:%S', time.localtime(ts)),
                    'level':    level,
                    'module':   module,
                    'message':  message,
                }
                with self._lock:
                    self._entries.append(entry)
        except Exception as e:
            print(f"[Logger] Failed to load log file: {e}")

    def _write_to_file(self, entry):
        """Write one entry to the persistent log file (called under no lock)."""
        if self._log_file is None:
            return
        try:
            line = (
                f"{entry['ts']:.3f}{_SEP}"
                f"{entry['level']}{_SEP}"
                f"{entry['module']}{_SEP}"
                f"{entry['message']}\n"
            )
            self._log_file.write(line)
            self._write_count += 1
            if self._write_count % 20 == 0:
                self._log_file.flush()
        except Exception:
            pass

    # ------------------------------------------------------------------ ingest

    def _ingest(self, text, default_level='info'):
        """Parse a raw print line and store with inferred level/module."""
        level  = default_level
        module = 'system'

        m = _PREFIX_RE.match(text)
        if m:
            tag = m.group(1).lower().replace(' ', '').replace('_', '').replace('.', '')
            module = _PREFIX_MAP.get(tag, 'system')

        if default_level == 'info':
            lower = text.lower()
            if any(k in lower for k in ('error', 'failed', 'exception', 'traceback')):
                level = 'error'
            elif any(k in lower for k in ('warning', 'warn')):
                level = 'warning'
            elif '[debug]' in lower:
                level = 'debug'

        self._store(text, level, module)

    # ------------------------------------------------------------------ public API

    def log(self, message, level='info', module='system'):
        """Structured log call — bypasses stdout intercept (no terminal echo)."""
        self._store(message, level, module)

    def get_entries(self, level=None, module=None, since_ts=None):
        """Return a filtered snapshot list (oldest first)."""
        with self._lock:
            entries = list(self._entries)
        if since_ts:
            entries = [e for e in entries if e['ts'] >= since_ts]
        if level and level != 'all':
            entries = [e for e in entries if e['level'] == level]
        if module and module != 'all':
            entries = [e for e in entries if e['module'] == module]
        return entries

    def get_known_modules(self):
        """Modules that have actually produced at least one entry."""
        with self._lock:
            return sorted(set(e['module'] for e in self._entries))

    def export(self, path):
        """Write all in-memory entries to a human-readable log file."""
        entries = self.get_entries()
        with open(path, 'w', encoding='utf-8') as f:
            f.write("# PROFILER MACHINE — SYSTEM LOG\n")
            f.write(f"# Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Entries:  {len(entries)}\n\n")
            for e in entries:
                f.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts']))}] "
                    f"[{e['level'].upper():<7}] "
                    f"[{e['module']:<12}] "
                    f"{e['message']}\n"
                )

    def close(self):
        """Flush and close the persistent log file."""
        if self._log_file:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    # ------------------------------------------------------------------ private

    def _store(self, message, level, module):
        entry = {
            'ts':       time.time(),
            'time_str': time.strftime('%H:%M:%S'),
            'level':    level,
            'module':   module,
            'message':  message,
        }
        with self._lock:
            self._entries.append(entry)
        self._write_to_file(entry)


def get_logger() -> AppLogger:
    return AppLogger()