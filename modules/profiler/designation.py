# modules/profiler/designation.py
# Handles face detection and applies role-based overlays to detected faces.

import cv2
import numpy as np
import os
import threading

DEFAULT_ROLE = 'irrelevant'

ROLE_OVERLAYS = {
    'irrelevant':   'irrelevant.png',
    'root':         'root.png',
    'admin':        'admin.png',
    'threat':       'threat.png',
    'victim':       'victim.png',
    'perpetrator':  'perpetrator.png',
}

OVERLAY_DIR = os.path.join('assets', 'overlay')


class Designator:
    def __init__(self, app):
        self.app = app
        self._overlays = self._load_overlays()

        # Latest frame to process and latest results
        self._pending_frame = None
        self._latest_faces = []  # list of (bbox, role)
        self._lock = threading.Lock()

        # Start detection thread
        self._running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()

    def _load_overlays(self):
        overlays = {}
        for role, filename in ROLE_OVERLAYS.items():
            path = os.path.join(OVERLAY_DIR, filename)
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                print(f"[Designator] Warning: could not load overlay '{path}'")
            else:
                overlays[role] = img
        return overlays

    def stop(self):
        self._running = False

    def _detection_loop(self):
        """Runs in background — continuously detects faces on the latest frame."""
        while self._running:
            with self._lock:
                frame = self._pending_frame
                self._pending_frame = None

            if frame is None:
                threading.Event().wait(0.01)  # small sleep, avoid busy loop
                continue

            try:
                faces = self.app.get(frame)
                results = [(face.bbox.astype(int), DEFAULT_ROLE) for face in faces]
            except Exception:
                results = []

            with self._lock:
                self._latest_faces = results

    def process_frame(self, frame, person_roles=None):
        """
        Submit frame for detection and draw latest known overlays.
        Returns the frame with overlays applied immediately using last known results.
        """
        # Submit this frame for detection
        with self._lock:
            self._pending_frame = frame.copy()
            faces = list(self._latest_faces)

        # Apply last known detections to current frame
        for bbox, role in faces:
            if person_roles:
                # future: look up recognized person role
                pass
            frame = self._apply_overlay(frame, bbox, role)

        return frame

    def _apply_overlay(self, frame, bbox, role):
        overlay_img = self._overlays.get(role)
        if overlay_img is None:
            overlay_img = self._overlays.get(DEFAULT_ROLE)
        if overlay_img is None:
            return frame

        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1

        if w <= 0 or h <= 0:
            return frame

        # Square, centered on face, 40% larger than biggest dimension
        size = int(max(w, h) * 1.4)
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        half = size // 2

        ox1 = cx - half
        oy1 = cy - half
        ox2 = cx + half
        oy2 = cy + half

        # Clip to frame bounds
        fx1 = max(0, ox1)
        fy1 = max(0, oy1)
        fx2 = min(frame.shape[1], ox2)
        fy2 = min(frame.shape[0], oy2)

        if fx2 <= fx1 or fy2 <= fy1:
            return frame

        # Resize overlay to full square, then crop to clipped region
        resized = cv2.resize(overlay_img, (size, size), interpolation=cv2.INTER_LINEAR)
        crop_x1 = fx1 - ox1
        crop_y1 = fy1 - oy1
        crop_x2 = crop_x1 + (fx2 - fx1)
        crop_y2 = crop_y1 + (fy2 - fy1)
        resized = resized[crop_y1:crop_y2, crop_x1:crop_x2]

        overlay_bgr = resized[:, :, :3]
        alpha = resized[:, :, 3] / 255.0

        roi = frame[fy1:fy2, fx1:fx2]
        for c in range(3):
            roi[:, :, c] = (alpha * overlay_bgr[:, :, c] +
                            (1.0 - alpha) * roi[:, :, c])
        frame[fy1:fy2, fx1:fx2] = roi

        return frame