# modules/core/device_enumerator.py
# Scans for available video input devices by probing cv2 indices.
# Stops after MAX_CONSECUTIVE_FAILURES unopenable devices in a row.
# Best-effort device name detection on Windows via PowerShell PnP query.

import cv2
import subprocess
import sys


MAX_CONSECUTIVE_FAILURES = 3


def _try_get_windows_names():
    """Query Windows PnP for camera device friendly names.

    Returns a dict of {ordinal_index: name} where ordinal_index is the
    zero-based position in the enumerated camera list — which usually
    matches the DirectShow capture index, though not guaranteed.
    """
    if sys.platform != 'win32':
        return {}
    try:
        result = subprocess.run(
            [
                'powershell', '-NoProfile', '-NonInteractive', '-Command',
                'Get-PnpDevice -Class Camera -Status OK '
                '| Sort-Object FriendlyName '
                '| Select-Object -ExpandProperty FriendlyName',
            ],
            capture_output=True, text=True, timeout=6,
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        return {i: name for i, name in enumerate(lines)}
    except Exception:
        return {}


def enumerate_devices():
    """Probe cv2 device indices until MAX_CONSECUTIVE_FAILURES in a row.

    Returns a list of dicts:
        {
            'index':  int,     # cv2 capture index
            'width':  int,     # native capture width
            'height': int,     # native capture height
            'name':   str,     # friendly name, or 'Camera <index>' fallback
        }
    """
    win_names = _try_get_windows_names()

    devices = []
    consecutive = 0
    idx = 0

    while consecutive < MAX_CONSECUTIVE_FAILURES:
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
        if cap.isOpened():
            ret, _ = cap.read()
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if ret and w > 0 and h > 0:
                name = win_names.get(idx, f"Camera {idx}")
                devices.append({
                    'index':  idx,
                    'width':  w,
                    'height': h,
                    'name':   name,
                })
                consecutive = 0
            else:
                cap.release()
                consecutive += 1
        else:
            cap.release()
            consecutive += 1
        idx += 1

    return devices