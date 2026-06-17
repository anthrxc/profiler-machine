# modules/io/playsound.py
# Blocking sound playback, cross-platform.
#
# On Windows the original `playsound` library is used (matches the friend's
# setup). On Linux/macOS the `playsound` library relies on GStreamer/PyGObject,
# which isn't available inside an isolated venv, so we shell out to whatever
# common CLI player is installed instead. play_sound() blocks until the clip
# finishes; callers that want async playback already wrap it in a thread.

import os
import shutil
import subprocess

# CLI players tried in order on non-Windows platforms. ffplay (ffmpeg) handles
# every format and is the most likely to be present; the rest are fallbacks.
_NIX_PLAYERS = (
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ["paplay"],
    ["aplay", "-q"],
    ["afplay"],  # macOS
)


def _play_with_library(file_path):
    """Fall back to the playsound library if it's importable and working."""
    try:
        from playsound import playsound as ps
        ps(file_path)
        return True
    except Exception:
        return False


def play_sound(file_path):
    if os.name == "nt":
        if not _play_with_library(file_path):
            try:
                import winsound
                winsound.PlaySound(file_path, winsound.SND_FILENAME)
            except Exception:
                pass
        return

    for player in _NIX_PLAYERS:
        if shutil.which(player[0]):
            try:
                subprocess.run(
                    [*player, file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return
            except Exception:
                continue

    # No CLI player found — last resort is the library (may be a no-op).
    _play_with_library(file_path)
