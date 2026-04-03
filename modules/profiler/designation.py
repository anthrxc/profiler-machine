# modules/profiler/designation.py
# Handles face detection, recognition, and overlay application.

import cv2
import numpy as np
import os
import threading
import time
import random

from modules.profiler.recognition import (
    RecognitionDB, LIVE_ENROLL_DESIGNATIONS, LIVE_ENROLL_WEIGHTS
)

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
AUTO_ENROLL_SECONDS = 3.0


class Designator:
    def __init__(self, app, db: RecognitionDB):
        self.app = app
        self.db = db
        self._overlays = self._load_overlays()

        self._pending_frame = None
        self._pending_feed_id = 0
        self._latest_results = []   # list of dicts: {bbox, ssn, designation, embedding, face_age, face_sex}
        self._visible_ssns = set()
        self._lock = threading.Lock()

        self._tracking = {}
        self._debug_role = None

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

    def set_debug_role(self, role):
        if role in ROLE_OVERLAYS:
            self._debug_role = role
            return True
        self._debug_role = None
        return False

    def is_ssn_in_frame(self, ssn):
        with self._lock:
            return ssn in self._visible_ssns

    # -------------------------------------------------------------------------
    # Detection loop
    # -------------------------------------------------------------------------

    def _detection_loop(self):
        while self._running:
            with self._lock:
                frame = self._pending_frame
                feed_id = self._pending_feed_id
                self._pending_frame = None

            if frame is None:
                time.sleep(0.01)
                continue

            try:
                faces = self.app.get(frame)
            except Exception:
                faces = []

            results = []
            visible = set()
            now = time.time()

            for face in faces:
                bbox = face.bbox.astype(int)
                embedding = face.embedding
                face_age = getattr(face, 'age', None)
                face_sex = getattr(face, 'sex', None)

                if embedding is None:
                    results.append({
                        'bbox': bbox,
                        'ssn': None,
                        'designation': DEFAULT_ROLE,
                        'embedding': None,
                        'face_age': face_age,
                        'face_sex': face_sex,
                    })
                    continue

                match = self.db.identify(embedding)

                if match:
                    ssn, name, designation, sim = match
                    self.db.update_last_seen(ssn, feed_id)
                    # Save last seen face crop
                    visible.add(ssn)
                    results.append({
                        'bbox': bbox,
                        'ssn': ssn,
                        'designation': designation,
                        'embedding': embedding,
                        'face_age': face_age,
                        'face_sex': face_sex,
                    })
                    tracking_key = self._find_tracking_key(embedding)
                    if tracking_key:
                        del self._tracking[tracking_key]
                else:
                    tracking_key = self._find_tracking_key(embedding)
                    if tracking_key is None:
                        tracking_key = id(embedding)
                        self._tracking[tracking_key] = {
                            'first_seen': now,
                            'embedding': embedding,
                            'feed_id': feed_id,
                            'bbox': bbox
                        }
                    else:
                        self._tracking[tracking_key]['bbox'] = bbox
                        elapsed = now - self._tracking[tracking_key]['first_seen']

                        if elapsed >= AUTO_ENROLL_SECONDS:
                            designation = random.choices(
                                LIVE_ENROLL_DESIGNATIONS,
                                weights=LIVE_ENROLL_WEIGHTS
                            )[0]
                            ssn = self.db.enroll(
                                embedding,
                                designation=designation,
                            )
                            from modules.profiler.recognition import save_enrolled_image
                            save_enrolled_image(ssn, frame, bbox);
                            print(f"[Designator] Auto-enrolled {ssn} as {designation}")
                            del self._tracking[tracking_key]
                            visible.add(ssn)
                            results.append({
                                'bbox': bbox,
                                'ssn': ssn,
                                'designation': designation,
                                'embedding': embedding,
                                'face_age': face_age,
                                'face_sex': face_sex,
                            })
                            continue

                    results.append({
                        'bbox': bbox,
                        'ssn': None,
                        'designation': DEFAULT_ROLE,
                        'embedding': embedding,
                        'face_age': face_age,
                        'face_sex': face_sex,
                    })

            self._tracking = {
                k: v for k, v in self._tracking.items()
                if now - v['first_seen'] < AUTO_ENROLL_SECONDS * 3
            }

            with self._lock:
                self._latest_results = results
                self._visible_ssns = visible

    def _find_tracking_key(self, embedding, threshold=0.6):
        from modules.profiler.recognition import _cosine_similarity
        for key, data in self._tracking.items():
            if _cosine_similarity(data['embedding'], embedding) > threshold:
                return key
        return None

    # -------------------------------------------------------------------------
    # Frame processing
    # -------------------------------------------------------------------------

    def process_frame(self, frame, feed_id=0):
        with self._lock:
            self._pending_frame = frame.copy()
            self._pending_feed_id = feed_id
            results = list(self._latest_results)

        for result in results:
            role = self._debug_role or result['designation']
            frame = self._apply_overlay(frame, result['bbox'], role)

        return frame

    # -------------------------------------------------------------------------
    # Overlay rendering
    # -------------------------------------------------------------------------

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

        size = int(max(w, h) * 1.4)
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        half = size // 2

        ox1 = cx - half
        oy1 = cy - half
        ox2 = cx + half
        oy2 = cy + half

        fx1 = max(0, ox1)
        fy1 = max(0, oy1)
        fx2 = min(frame.shape[1], ox2)
        fy2 = min(frame.shape[0], oy2)

        if fx2 <= fx1 or fy2 <= fy1:
            return frame

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