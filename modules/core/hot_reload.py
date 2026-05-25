# modules/core/hot_reload.py
# Hot-reload support for safe, stateless modules.

import importlib
import sys
import os

# Dotted module paths for importlib
RELOAD_TARGETS = {
    'infocard':   'modules.profiler.infocard',
    'heuristics': 'modules.profiler.heuristics',
    'antispoof':  'modules.profiler.antispoof',
}


def reload_module(name):
    """Reload a single module by short name. Returns (success: bool, message: str)."""
    mod_path = RELOAD_TARGETS.get(name)
    if not mod_path or mod_path not in sys.modules:
        return False, f"[RELOAD] {name} → not loaded"
    try:
        importlib.reload(sys.modules[mod_path])
        return True, f"[RELOAD] {name} → ok"
    except Exception as e:
        return False, f"[RELOAD] {name} → FAILED: {e}"


def scan_new_modules(root='modules'):
    """Walk modules/ and return dotted names of .py files not yet in sys.modules."""
    new = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if fname.endswith('.py') and not fname.startswith('_'):
                rel = os.path.join(dirpath, fname)
                mod_name = rel.replace(os.sep, '.').replace('/', '.').removesuffix('.py')
                if mod_name not in sys.modules:
                    new.append(mod_name)
    return new