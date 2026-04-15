# modules/profiler/designation.py
# Handles face detection, recognition, tracking, and overlay application.

import cv2
import numpy as np
import os
import threading
import time
import random
import torch

from bytetracker import BYTETracker

from modules.profiler.recognition import (
    RecognitionDB, LIVE_ENROLL_DESIGNATIONS, LIVE_ENROLL_WEIGHTS
)
from modules.profiler.antispoof import AntiSpoofModel

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
ANTISPOOF_WEIGHTS = os.path.join('assets', 'antispoof', 'MiniFASNetV2.onnx')
AUTO_ENROLL_SECONDS = 3.0

# Re-identify a tracked face every N seconds
REIDENTIFY_INTERVAL = 2.0


def _make_tracker():
    """Create a fresh BYTETracker instance."""
    return BYTETracker(
        track_thresh=0.5,
        track_buffer=30,
        match_thresh=0.8,
        frame_rate=30
    )


class Designator:
    def __init__(self, app, db: RecognitionDB):
        self.app = app
        self.db = db
        self._overlays = self._load_overlays()

        # Detection thread state
        self._pending_frame = None
        self._pending_feed_id = 0
        self._latest_results = []   # list of dicts: {bbox, ssn, designation, track_id, face_age, face_sex}
        self._visible_ssns = set()
        self._lock = threading.Lock()

        # ByteTracker — one per feed
        self._trackers = {}         # {feed_id: BYTETracker}

        # Track → identity binding: {track_id: {ssn, designation, last_identified, face_age, face_sex}}
        self._track_identities = {}

        # Tracks waiting for auto-enrollment: {track_id: {first_seen, embedding}}
        self._pending_enrollment = {}

        self._debug_role = None

        self.antispoof = AntiSpoofModel(
            model_path=ANTISPOOF_WEIGHTS,
            scale=2.7
        )
        self._auth_request_ssn = None
        self._auth_result = None

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

            # Get or create tracker for this feed
            if feed_id not in self._trackers:
                self._trackers[feed_id] = _make_tracker()
            tracker = self._trackers[feed_id]

            try:
                faces = self.app.get(frame)
            except Exception:
                faces = []

            now = time.time()
            h, w = frame.shape[:2]

            # Build detection array for ByteTrack: [x1, y1, x2, y2, score]
            detections = []
            face_data = []  # parallel list of face attributes
            for face in faces:
                bbox = face.bbox.astype(float)
                score = float(getattr(face, 'det_score', 1.0))
                cls = 0.0
                detections.append([bbox[0], bbox[1], bbox[2], bbox[3], score, cls])
                face_data.append({
                    'embedding': face.embedding,
                    'face_age':  getattr(face, 'age', None),
                    'face_sex':  getattr(face, 'sex', None),
                    'bbox':      face.bbox.astype(int),
                })

            if detections:
                dets_np = np.array(detections, dtype=np.float32)
                dets_t = torch.tensor(dets_np, dtype=torch.float32)
                online_targets = tracker.update(dets_t, [h, w])
            else:
                # Feed empty detections to keep tracks updated
                online_targets = tracker.update(
                    torch.empty((0, 6), dtype=torch.float32), [h, w]
                )

            # Match ByteTrack targets back to InsightFace detections by IoU
            results = []
            visible = set()

            for target in online_targets:
                # BYTETracker returns rows of [x1, y1, x2, y2, track_id, cls, score]
                tx1, ty1, tx2, ty2 = int(target[0]), int(target[1]), int(target[2]), int(target[3])
                track_id = int(target[4])
                tracked_bbox = np.array([tx1, ty1, tx2, ty2])

                # Find best matching InsightFace detection by IoU
                best_idx = self._match_detection(tracked_bbox, face_data)
                embedding = face_data[best_idx]['embedding'] if best_idx is not None else None
                face_age  = face_data[best_idx]['face_age']  if best_idx is not None else None
                face_sex  = face_data[best_idx]['face_sex']  if best_idx is not None else None

                # Look up or refresh identity for this track
                identity = self._track_identities.get(track_id)
                should_identify = (
                    embedding is not None and (
                        identity is None or
                        now - identity.get('last_identified', 0) > REIDENTIFY_INTERVAL
                    )
                )

                if should_identify:
                    match = self.db.identify(embedding)
                    if match:
                        ssn, name, designation, sim = match
                        self.db.update_last_seen(ssn, feed_id)
                        self._track_identities[track_id] = {
                            'ssn':             ssn,
                            'designation':     designation,
                            'last_identified': now,
                            'face_age':        face_age,
                            'face_sex':        face_sex,
                        }
                        # Remove from pending enrollment if it was there
                        self._pending_enrollment.pop(track_id, None)
                    else:
                        # Unknown face — track for auto-enrollment
                        if track_id not in self._pending_enrollment:
                            self._pending_enrollment[track_id] = {
                                'first_seen': now,
                                'embedding':  embedding,
                            }
                        else:
                            elapsed = now - self._pending_enrollment[track_id]['first_seen']
                            if elapsed >= AUTO_ENROLL_SECONDS:
                                designation = random.choices(
                                    LIVE_ENROLL_DESIGNATIONS,
                                    weights=LIVE_ENROLL_WEIGHTS
                                )[0]
                                ssn = self.db.enroll(embedding, designation=designation)
                                from modules.profiler.recognition import save_enrolled_image
                                save_enrolled_image(ssn, frame, tracked_bbox)
                                print(f"[Designator] Auto-enrolled {ssn} as {designation} (track {track_id})")
                                self._track_identities[track_id] = {
                                    'ssn':             ssn,
                                    'designation':     designation,
                                    'last_identified': now,
                                    'face_age':        face_age,
                                    'face_sex':        face_sex,
                                }
                                del self._pending_enrollment[track_id]

                # Use whatever identity we have for this track (may be None if not yet identified)
                identity = self._track_identities.get(track_id)
                if identity:
                    ssn         = identity['ssn']
                    designation = identity['designation']
                    face_age    = identity.get('face_age')
                    face_sex    = identity.get('face_sex')
                    visible.add(ssn)
                else:
                    ssn         = None
                    designation = DEFAULT_ROLE

                results.append({
                    'bbox':        tracked_bbox,
                    'track_id':    track_id,
                    'ssn':         ssn,
                    'designation': designation,
                    'embedding':   embedding,
                    'face_age':    face_age,
                    'face_sex':    face_sex,
                })

            # Clean up identities for tracks that are no longer active
            active_ids = {int(t[4]) for t in online_targets}
            stale = [tid for tid in self._track_identities if tid not in active_ids]
            for tid in stale:
                del self._track_identities[tid]

            # Clean up pending enrollment for lost tracks
            stale_enroll = [tid for tid in self._pending_enrollment if tid not in active_ids]
            for tid in stale_enroll:
                del self._pending_enrollment[tid]

            with self._lock:
                self._latest_results = results
                self._visible_ssns = visible

    def _match_detection(self, tracked_bbox, face_data, iou_threshold=0.3):
        """Find the InsightFace detection that best matches a tracked bbox by IoU."""
        if not face_data:
            return None
        best_iou = iou_threshold
        best_idx = None
        for i, fd in enumerate(face_data):
            iou = self._bbox_iou(tracked_bbox, fd['bbox'])
            if iou > best_iou:
                best_iou = iou
                best_idx = i
        return best_idx

    def _bbox_iou(self, a, b):
        """Compute IoU between two bboxes [x1,y1,x2,y2]."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter)

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

    def request_auth_check(self, ssn):
        with self._lock:
            self._auth_request_ssn = ssn
            self._auth_result = None

    def consume_auth_result(self):
        with self._lock:
            result = self._auth_result
            self._auth_result = None
            return result