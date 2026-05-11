# modules/profiler/designation.py
# Face + body tracking pipeline. Subjects are tracked across head turns:
# face tracks identify, body tracks carry continuity when faces disappear.

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
from modules.profiler.body_detector import (
    BodyDetector, face_in_body, body_top_distance, head_region_from_body
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
ANTISPOOF_WEIGHTS = os.path.join('assets', 'antispoof', 'MiniFASNetV2.onnx')
AUTO_ENROLL_SECONDS = 3.0

# Re-identify a tracked face every N seconds, in case the first match was
# wrong or in case the subject's track id was hijacked by a passer-by.
REIDENTIFY_INTERVAL = 10.0

# ByteTrack tuning — face buffer is short (faces flicker), body buffer is
# longer so the subject survives head-turns and brief occlusions.
FACE_TRACK_BUFFER = 30      # ~1.0 s @ 30fps
BODY_TRACK_BUFFER = 60      # ~2.0 s @ 30fps
TRACKER_FRAME_RATE = 30

# How long after a track id was last seen do we still consider it "ours"?
# These match the ByteTrack buffers above so they expire together.
FACE_GRACE_SEC = FACE_TRACK_BUFFER / TRACKER_FRAME_RATE
BODY_GRACE_SEC = BODY_TRACK_BUFFER / TRACKER_FRAME_RATE


def _make_face_tracker():
    return BYTETracker(
        track_thresh=0.5,
        track_buffer=FACE_TRACK_BUFFER,
        match_thresh=0.8,
        frame_rate=TRACKER_FRAME_RATE,
    )


def _make_body_tracker():
    return BYTETracker(
        track_thresh=0.4,           # YOLO confidences are typically lower than InsightFace
        track_buffer=BODY_TRACK_BUFFER,
        match_thresh=0.85,          # bodies move more between frames; need looser IoU
        frame_rate=TRACKER_FRAME_RATE,
    )


# -----------------------------------------------------------------------------
# Subject — bridges a face track and a body track.
# -----------------------------------------------------------------------------

class Subject:
    """A tracked person.

    A Subject can be in one of three states:
      • face + body  — both tracks active. Best case. Identification happens
                       on the face; the body provides continuity if the face
                       turns away.
      • face only    — close-up shot or body detector missed. Behaves like
                       the old face-only pipeline.
      • body only    — face has turned away or is occluded. Identity (if
                       previously established) survives on the body track.
                       The overlay is rendered on the head region of the
                       body bbox.

    When the face reappears and binds back to the same body track, the
    Subject re-validates identity via the new face embedding.
    """

    __slots__ = (
        'feed_id',
        'face_tid', 'body_tid',
        'face_bbox', 'body_bbox',
        'last_face_seen', 'last_body_seen',
        'last_face_size', 'last_face_offset',
        'has_face_history',
        'ssn', 'designation',
        'embedding', 'face_age', 'face_sex',
        'last_identified',
        'pending_enroll_since', 'pending_enroll_embedding',
    )

    def __init__(self, feed_id):
        self.feed_id = feed_id
        self.face_tid = None
        self.body_tid = None
        self.face_bbox = None              # np.ndarray [x1,y1,x2,y2] of last seen face
        self.body_bbox = None              # np.ndarray [x1,y1,x2,y2] of last seen body
        self.last_face_seen = 0.0
        self.last_body_seen = 0.0
        self.last_face_size = None         # (w, h) — used to size body-mode overlay
        self.last_face_offset = None       # (dx, dy) — face center vs body top-center,
                                           # recorded whenever face+body are both seen.
                                           # Drives overlay position in body-only mode.
        self.has_face_history = False      # True once a face has ever bound to this
                                           # subject. Body-only subjects that have never
                                           # had a face are likely YOLO false positives
                                           # (hands, fabric) and are not rendered.
        self.ssn = None
        self.designation = DEFAULT_ROLE
        self.embedding = None
        self.face_age = None
        self.face_sex = None
        self.last_identified = 0.0
        self.pending_enroll_since = None
        self.pending_enroll_embedding = None

    @property
    def has_identity(self):
        return self.ssn is not None

    @property
    def has_active_face(self):
        return self.face_tid is not None

    @property
    def has_active_body(self):
        return self.body_tid is not None

    def is_alive(self):
        return self.face_tid is not None or self.body_tid is not None

    def render_bbox(self):
        """The bbox to draw the overlay on this frame.

        Prefers the live face bbox; falls back to a head region estimated
        from the body bbox (sized to the last known face for visual
        continuity). Returns None if neither track is currently active.
        """
        if self.face_tid is not None and self.face_bbox is not None:
            return tuple(int(v) for v in self.face_bbox)
        if self.body_tid is not None and self.body_bbox is not None:
            return head_region_from_body(self.body_bbox,
                                         self.last_face_size,
                                         self.last_face_offset)
        return None


# -----------------------------------------------------------------------------
# Designator
# -----------------------------------------------------------------------------

class Designator:
    def __init__(self, app, db: RecognitionDB, body_detector=None):
        self.app = app
        self.db = db
        self._body_detector = body_detector  # may be None — degrades to face-only
        self._overlays = self._load_overlays()

        # Per-feed queue: {feed_id: frame} — holds latest unprocessed frame per feed.
        # Detection loop round-robins through feeds so no feed starves.
        self._pending_frames = {}        # {feed_id: frame}
        self._latest_results = {}        # {feed_id: [result dicts]}
        self._visible_ssns = set()
        self._lock = threading.Lock()
        self._feed_order = []            # insertion-ordered list of known feed_ids

        # Per-feed trackers — face and body tracks evolve independently.
        self._face_trackers = {}         # {feed_id: BYTETracker}
        self._body_trackers = {}         # {feed_id: BYTETracker}

        # Per-feed subjects — the bridging objects between face and body tracks.
        self._subjects = {}              # {feed_id: list[Subject]}

        self._debug_role = None

        # Cross-feed subject tracking (preserved API).
        self._tracked_ssn       = None
        self._tracked_last_feed = None

        self.antispoof = AntiSpoofModel(model_path=ANTISPOOF_WEIGHTS, scale=2.7)
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

    # -- Cross-feed tracking API ------------------------------------------------

    def set_tracked_ssn(self, ssn):
        with self._lock:
            self._tracked_ssn = ssn
            self._tracked_last_feed = None

    def clear_tracked_ssn(self):
        with self._lock:
            self._tracked_ssn = None
            self._tracked_last_feed = None

    def get_tracked_ssn(self):
        with self._lock:
            return self._tracked_ssn

    def get_tracked_last_feed(self):
        with self._lock:
            return self._tracked_last_feed

    def is_tracked_visible(self):
        with self._lock:
            return self._tracked_ssn is not None and self._tracked_ssn in self._visible_ssns

    # -------------------------------------------------------------------------
    # Detection loop
    # -------------------------------------------------------------------------

    def _detection_loop(self):
        while self._running:
            with self._lock:
                feed_id = None
                frame = None
                for fid in self._feed_order:
                    if fid in self._pending_frames:
                        feed_id = fid
                        frame = self._pending_frames.pop(fid)
                        break

            if frame is None:
                time.sleep(0.01)
                continue

            self._process_feed_frame(feed_id, frame)

    # -------------------------------------------------------------------------
    # Per-feed frame processing
    # -------------------------------------------------------------------------

    def _process_feed_frame(self, feed_id, frame):
        # Initialize per-feed state on first sight.
        if feed_id not in self._face_trackers:
            self._face_trackers[feed_id] = _make_face_tracker()
            self._body_trackers[feed_id] = _make_body_tracker()
            self._subjects[feed_id] = []

        face_tracker = self._face_trackers[feed_id]
        body_tracker = self._body_trackers[feed_id]
        subjects     = self._subjects[feed_id]

        now = time.time()
        h, w = frame.shape[:2]

        # ── Detection ────────────────────────────────────────────────────────
        try:
            faces = self.app.get(frame)
        except Exception:
            faces = []

        body_dets = self._body_detector.detect(frame) if self._body_detector else []

        # ── Track update ─────────────────────────────────────────────────────
        face_targets, _ = self._update_face_tracker(face_tracker, faces, h, w)
        body_targets    = self._update_body_tracker(body_tracker, body_dets, h, w)

        # ── Subject reconciliation ───────────────────────────────────────────
        face_target_ids = set(face_targets.keys())
        body_target_ids = set(body_targets.keys())

        # Refresh existing subjects from current tracks.
        for sub in subjects:
            if sub.face_tid is not None and sub.face_tid in face_target_ids:
                fdata = face_targets[sub.face_tid]
                sub.face_bbox = fdata['bbox']
                sub.last_face_seen = now
                sub.has_face_history = True
                fw = fdata['bbox'][2] - fdata['bbox'][0]
                fh = fdata['bbox'][3] - fdata['bbox'][1]
                if fw > 0 and fh > 0:
                    sub.last_face_size = (fw, fh)
                if fdata['embedding'] is not None:
                    sub.embedding = fdata['embedding']
                if fdata['face_age'] is not None:
                    sub.face_age = fdata['face_age']
                if fdata['face_sex'] is not None:
                    sub.face_sex = fdata['face_sex']
                self._maybe_identify_or_enroll(sub, frame, now)

            if sub.body_tid is not None and sub.body_tid in body_target_ids:
                sub.body_bbox = body_targets[sub.body_tid]
                sub.last_body_seen = now

        # Drop stale track ids (track went away long enough ago).
        for sub in subjects:
            if sub.face_tid is not None:
                fresh = sub.face_tid in face_target_ids
                if not fresh and (now - sub.last_face_seen) > FACE_GRACE_SEC:
                    sub.face_tid = None
                    sub.face_bbox = None
                    # Keep last_face_size — we want it for body-mode overlay sizing.
            if sub.body_tid is not None:
                fresh = sub.body_tid in body_target_ids
                if not fresh and (now - sub.last_body_seen) > BODY_GRACE_SEC:
                    sub.body_tid = None
                    sub.body_bbox = None

        # Bind any face track ids that aren't yet bound to a subject.
        bound_face_ids = {s.face_tid for s in subjects if s.face_tid is not None}
        for face_tid in face_target_ids - bound_face_ids:
            fdata = face_targets[face_tid]
            face_bbox = fdata['bbox']
            host = self._find_host_body_subject(subjects, face_bbox, body_targets)
            if host is not None:
                # Reacquisition — attach face track to the existing subject.
                host.face_tid = face_tid
                host.face_bbox = face_bbox
                host.last_face_seen = now
                host.has_face_history = True
                fw = face_bbox[2] - face_bbox[0]
                fh = face_bbox[3] - face_bbox[1]
                if fw > 0 and fh > 0:
                    host.last_face_size = (fw, fh)
                if fdata['embedding'] is not None:
                    host.embedding = fdata['embedding']
                if fdata['face_age'] is not None:
                    host.face_age = fdata['face_age']
                if fdata['face_sex'] is not None:
                    host.face_sex = fdata['face_sex']
                # Force re-identification on reacquisition — body track id might
                # be stale, or we might have been on an unidentified body up to now.
                host.last_identified = 0.0
                self._maybe_identify_or_enroll(host, frame, now)
            else:
                # Brand new subject — face only for now; try to bind to a body.
                sub = Subject(feed_id)
                sub.face_tid = face_tid
                sub.face_bbox = face_bbox
                sub.last_face_seen = now
                sub.has_face_history = True
                fw = face_bbox[2] - face_bbox[0]
                fh = face_bbox[3] - face_bbox[1]
                if fw > 0 and fh > 0:
                    sub.last_face_size = (fw, fh)
                sub.embedding = fdata['embedding']
                sub.face_age = fdata['face_age']
                sub.face_sex = fdata['face_sex']
                self._maybe_identify_or_enroll(sub, frame, now)
                body_tid = self._find_body_for_face(
                    face_bbox, body_targets,
                    exclude_ids=self._bound_body_ids(subjects),
                )
                if body_tid is not None:
                    sub.body_tid = body_tid
                    sub.body_bbox = body_targets[body_tid]
                    sub.last_body_seen = now
                subjects.append(sub)

        # Bind any body track ids that aren't yet bound to a subject.
        bound_body_ids = self._bound_body_ids(subjects)
        for body_tid in body_target_ids - bound_body_ids:
            body_bbox = body_targets[body_tid]
            sub = Subject(feed_id)
            sub.body_tid = body_tid
            sub.body_bbox = body_bbox
            sub.last_body_seen = now
            subjects.append(sub)

        # Drop fully dead subjects.
        subjects[:] = [s for s in subjects if s.is_alive()]

        # Record face↔body offset for any subject seen in both channels this
        # frame. The offset later positions the head-region overlay when only
        # the body track survives — crucial for waist-up shots where the body
        # bbox doesn't include the head.
        for sub in subjects:
            if (sub.last_face_seen == now and sub.last_body_seen == now
                    and sub.face_bbox is not None and sub.body_bbox is not None):
                bx1, by1, bx2, _by2 = sub.body_bbox
                face_cx = (sub.face_bbox[0] + sub.face_bbox[2]) * 0.5
                face_cy = (sub.face_bbox[1] + sub.face_bbox[3]) * 0.5
                sub.last_face_offset = (face_cx - (bx1 + bx2) * 0.5,
                                        face_cy - by1)

        # ── Build results ────────────────────────────────────────────────────
        results = []
        visible = set()
        for sub in subjects:
            # Subjects that have never had a face bound are likely YOLO false
            # positives (hands, fabric, shadows). Keep them tracked silently —
            # they may later bind a real face — but don't draw anything.
            if not sub.has_face_history:
                continue
            rbbox = sub.render_bbox()
            if rbbox is None:
                continue
            if sub.has_identity:
                visible.add(sub.ssn)
            results.append({
                'bbox':         np.array(rbbox, dtype=int),
                'track_id':     sub.body_tid if sub.body_tid is not None else sub.face_tid,
                'face_tid':     sub.face_tid,
                'body_tid':     sub.body_tid,
                'ssn':          sub.ssn,
                'designation':  sub.designation,
                'embedding':    sub.embedding,
                'face_age':     sub.face_age,
                'face_sex':     sub.face_sex,
                'face_visible': sub.has_active_face,
                'body_bbox':    tuple(int(v) for v in sub.body_bbox)
                                if sub.body_bbox is not None else None,
            })

        with self._lock:
            self._latest_results[feed_id] = results
            all_visible = set()
            for feed_results in self._latest_results.values():
                for r in feed_results:
                    if r['ssn']:
                        all_visible.add(r['ssn'])
            self._visible_ssns = all_visible
            if self._tracked_ssn and self._tracked_ssn in visible:
                self._tracked_last_feed = feed_id

    # -------------------------------------------------------------------------
    # Tracker helpers
    # -------------------------------------------------------------------------

    def _update_face_tracker(self, tracker, faces, h, w):
        """Run face detections through ByteTrack, return ({tid: face_data}, list).

        face_data dict: {'bbox', 'embedding', 'face_age', 'face_sex'}.
        Each tracked face is IoU-matched back to the originating InsightFace
        detection so we can attach the embedding and demographics.

        Predicted-only outputs (ByteTrack carrying a track via Kalman with no
        backing detection this frame) are dropped. They drift visibly when the
        subject is occluded and we'd rather let the grace period handle the
        gap than render a ghost overlay.
        """
        face_data_list = []
        detections = []
        for face in faces:
            bbox = face.bbox.astype(float)
            score = float(getattr(face, 'det_score', 1.0))
            detections.append([bbox[0], bbox[1], bbox[2], bbox[3], score, 0.0])
            face_data_list.append({
                'embedding': face.embedding,
                'face_age':  getattr(face, 'age', None),
                'face_sex':  getattr(face, 'sex', None),
                'bbox':      face.bbox.astype(int),
            })

        if detections:
            dets_t = torch.tensor(np.array(detections, dtype=np.float32),
                                  dtype=torch.float32)
            online = tracker.update(dets_t, [h, w])
        else:
            online = tracker.update(torch.empty((0, 6), dtype=torch.float32), [h, w])

        out = {}
        for target in online:
            tx1, ty1, tx2, ty2 = (int(target[0]), int(target[1]),
                                  int(target[2]), int(target[3]))
            tid = int(target[4])
            tracked_bbox = np.array([tx1, ty1, tx2, ty2], dtype=int)
            best_idx = self._match_detection(tracked_bbox, face_data_list)
            if best_idx is None:
                # Predicted-only track — skip. Let the grace period handle
                # short detection drops without producing a ghost overlay.
                continue
            fd = face_data_list[best_idx]
            out[tid] = {
                'bbox':      tracked_bbox,
                'embedding': fd['embedding'],
                'face_age':  fd['face_age'],
                'face_sex':  fd['face_sex'],
            }
        return out, face_data_list

    def _update_body_tracker(self, tracker, body_dets, h, w):
        """Run body detections through ByteTrack.

        Predicted-only outputs are dropped for the same reason as faces — they
        cause overlays to "float in the air" when bodies briefly vanish, and
        especially when YOLO false-positives on hands or moving fabric.
        """
        det_bboxes = []
        if body_dets:
            arr = np.array([[d[0], d[1], d[2], d[3], d[4], 0.0] for d in body_dets],
                           dtype=np.float32)
            dets_t = torch.tensor(arr, dtype=torch.float32)
            online = tracker.update(dets_t, [h, w])
            for d in body_dets:
                det_bboxes.append(np.array([int(d[0]), int(d[1]),
                                            int(d[2]), int(d[3])], dtype=int))
        else:
            online = tracker.update(torch.empty((0, 6), dtype=torch.float32), [h, w])

        out = {}
        for target in online:
            tx1, ty1, tx2, ty2 = (int(target[0]), int(target[1]),
                                  int(target[2]), int(target[3]))
            tid = int(target[4])
            tracked_bbox = np.array([tx1, ty1, tx2, ty2], dtype=int)
            # Only accept this track if it's backed by an actual detection
            # this frame.
            backed = False
            for db in det_bboxes:
                if self._bbox_iou(tracked_bbox, db) >= 0.3:
                    backed = True
                    break
            if not backed:
                continue
            out[tid] = tracked_bbox
        return out

    def _match_detection(self, tracked_bbox, face_data, iou_threshold=0.3):
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

    @staticmethod
    def _bbox_iou(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter)

    # -------------------------------------------------------------------------
    # Subject binding helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _bound_body_ids(subjects):
        return {s.body_tid for s in subjects if s.body_tid is not None}

    def _find_host_body_subject(self, subjects, face_bbox, body_targets):
        """Find a subject whose body bbox plausibly contains this face.

        Used for face reacquisition: we lost the face track, kept tracking
        the body, and now a new face appears in the right place.
        """
        best = None
        best_dist = float('inf')
        for sub in subjects:
            if sub.body_tid is None:
                continue
            if sub.face_tid is not None:
                continue
            body_bbox = body_targets.get(sub.body_tid)
            if body_bbox is None:
                continue
            if not face_in_body(face_bbox, body_bbox):
                continue
            d = body_top_distance(face_bbox, body_bbox)
            if d < best_dist:
                best_dist = d
                best = sub
        return best

    @staticmethod
    def _find_body_for_face(face_bbox, body_targets, exclude_ids):
        best_tid = None
        best_dist = float('inf')
        for tid, body_bbox in body_targets.items():
            if tid in exclude_ids:
                continue
            if not face_in_body(face_bbox, body_bbox):
                continue
            d = body_top_distance(face_bbox, body_bbox)
            if d < best_dist:
                best_dist = d
                best_tid = tid
        return best_tid

    # -------------------------------------------------------------------------
    # Identification / auto-enrollment
    # -------------------------------------------------------------------------

    def _maybe_identify_or_enroll(self, sub, frame, now):
        if sub.embedding is None:
            return

        needs_id = (
            not sub.has_identity or
            (now - sub.last_identified) > REIDENTIFY_INTERVAL
        )
        if not needs_id:
            return

        match = self.db.identify(sub.embedding)
        if match:
            ssn, name, designation, sim = match
            self.db.update_last_seen(ssn, sub.feed_id)
            sub.ssn = ssn
            sub.designation = designation
            sub.last_identified = now
            sub.pending_enroll_since = None
            sub.pending_enroll_embedding = None
            return

        if sub.pending_enroll_since is None:
            sub.pending_enroll_since = now
            sub.pending_enroll_embedding = sub.embedding
            return

        if (now - sub.pending_enroll_since) >= AUTO_ENROLL_SECONDS:
            designation = random.choices(
                LIVE_ENROLL_DESIGNATIONS,
                weights=LIVE_ENROLL_WEIGHTS,
            )[0]
            ssn = self.db.enroll(sub.pending_enroll_embedding, designation=designation)
            from modules.profiler.recognition import save_enrolled_image
            if sub.face_bbox is not None:
                save_enrolled_image(ssn, frame, sub.face_bbox)
            print(f"[Designator] Auto-enrolled {ssn} as {designation} "
                  f"(face_tid={sub.face_tid} body_tid={sub.body_tid})")
            sub.ssn = ssn
            sub.designation = designation
            sub.last_identified = now
            sub.pending_enroll_since = None
            sub.pending_enroll_embedding = None

    # -------------------------------------------------------------------------
    # Frame processing (called by FeedManager every frame)
    # -------------------------------------------------------------------------

    def process_frame(self, frame, feed_id=0):
        with self._lock:
            if feed_id not in self._feed_order:
                self._feed_order.append(feed_id)
            self._pending_frames[feed_id] = frame.copy()
            results = list(self._latest_results.get(feed_id, []))
            tracked_ssn = self._tracked_ssn

        for result in results:
            role = self._debug_role or result['designation']
            frame = self._apply_overlay(frame, result['bbox'], role)

        if tracked_ssn:
            for result in results:
                if result.get('ssn') == tracked_ssn:
                    desig = self._debug_role or result['designation']
                    self._draw_tracking_indicator(frame, result['bbox'], desig)

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

        ox1, oy1, ox2, oy2 = cx - half, cy - half, cx + half, cy + half
        fx1 = max(0, ox1); fy1 = max(0, oy1)
        fx2 = min(frame.shape[1], ox2); fy2 = min(frame.shape[0], oy2)
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

    def _draw_tracking_indicator(self, frame, bbox, designation='irrelevant'):
        colour = (0, 191, 255)
        fh, fw = frame.shape[:2]

        x1, y1, x2, y2 = bbox
        face_w, face_h = x2 - x1, y2 - y1
        size = int(max(face_w, face_h) * 1.4)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        half = size // 2
        ov_x2 = min(fw - 1, cx + half)

        label = "TRACKING"
        font  = cv2.FONT_HERSHEY_COMPLEX_SMALL
        scale = 0.65
        thick = 1
        (tw, th), _ = cv2.getTextSize(label, font, scale, thick)

        gap = 8
        tx = ov_x2 + gap
        ov_x1 = max(0, cx - half)
        if tx + tw > fw:
            tx = ov_x1 - tw - gap
        tx = max(0, tx)
        ty = cy + th // 2

        cv2.putText(frame, label, (tx + 1, ty + 1),
                    font, scale, (0, 0, 0), thick + 1, cv2.LINE_AA)
        cv2.putText(frame, label, (tx, ty),
                    font, scale, colour, thick, cv2.LINE_AA)

    # -------------------------------------------------------------------------
    # Auth (preserved API)
    # -------------------------------------------------------------------------

    def request_auth_check(self, ssn):
        with self._lock:
            self._auth_request_ssn = ssn
            self._auth_result = None

    def consume_auth_result(self):
        with self._lock:
            result = self._auth_result
            self._auth_result = None
            return result