# modules/profiler/body_detector.py
# Person (full-body) detection used to maintain identity continuity when the
# face is occluded or turned away from the camera.
#
# Wraps Ultralytics YOLOv8n. The model is loaded lazily via the .load() method
# so that startup.py can call it from a controlled context (after CUDA DLLs
# are pre-loaded, before QApplication owns the main thread).

import os
import numpy as np

# COCO class index for "person"
COCO_PERSON = 0

DEFAULT_MODEL_NAME = 'yolov8n.pt'   # ~6 MB — auto-downloaded on first use
DEFAULT_CONF       = 0.35
DEFAULT_IOU        = 0.5
DEFAULT_IMGSZ      = 640


class BodyDetector:
    """Detects person bounding boxes in a frame.

    Usage:
        detector = BodyDetector()
        detector.load()                       # blocks; downloads model if missing
        boxes = detector.detect(frame)        # list of [x1,y1,x2,y2,score]

    `detect()` returns an empty list if the detector is not loaded — callers
    can treat the body channel as best-effort and degrade gracefully to
    face-only tracking.
    """

    def __init__(self, model_name=DEFAULT_MODEL_NAME, conf=DEFAULT_CONF,
                 iou=DEFAULT_IOU, imgsz=DEFAULT_IMGSZ, device=None):
        self._model_name = model_name
        self._conf       = conf
        self._iou        = iou
        self._imgsz      = imgsz
        self._device     = device     # None → ultralytics auto-picks (cuda:0 if available)
        self._model      = None
        self._loaded     = False

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def load(self):
        """Load the YOLO model. Call once during startup. Idempotent."""
        if self._loaded:
            return True

        try:
            # Import lazily so that environments without ultralytics installed
            # can still import this module (the detector simply stays inert).
            from ultralytics import YOLO

            # Prefer a model bundled in assets/detector/ if present, otherwise
            # let ultralytics resolve and auto-download.
            asset_path = os.path.join('assets', 'detector', self._model_name)
            model_path = asset_path if os.path.exists(asset_path) else self._model_name

            self._model = YOLO(model_path)

            # Move to device if specified (e.g. 'cuda:0'). Ultralytics will
            # otherwise auto-select on first inference call.
            if self._device is not None:
                self._model.to(self._device)

            self._loaded = True
            return True
        except Exception as e:
            print(f"[BodyDetector] Failed to load model: {e}")
            self._model  = None
            self._loaded = False
            return False

    @property
    def is_loaded(self):
        return self._loaded

    # -------------------------------------------------------------------------
    # Inference
    # -------------------------------------------------------------------------

    def detect(self, frame):
        """Return person detections as a list of [x1, y1, x2, y2, score].

        Coordinates are in image pixels. Returns [] if the detector is not
        loaded or inference fails — callers should treat this as a transient
        miss, not an error.
        """
        if not self._loaded or self._model is None or frame is None:
            return []

        try:
            results = self._model.predict(
                frame,
                conf=self._conf,
                iou=self._iou,
                imgsz=self._imgsz,
                classes=[COCO_PERSON],
                verbose=False,
            )
        except Exception as e:
            print(f"[BodyDetector] Inference error: {e}")
            return []

        if not results:
            return []

        # ultralytics returns a list of Results, one per input image
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []

        # Pull tensors → CPU numpy in one shot
        try:
            xyxy = r.boxes.xyxy.detach().cpu().numpy()
            conf = r.boxes.conf.detach().cpu().numpy()
        except Exception:
            return []

        out = []
        for (x1, y1, x2, y2), score in zip(xyxy, conf):
            out.append([float(x1), float(y1), float(x2), float(y2), float(score)])
        return out


# -----------------------------------------------------------------------------
# Geometry helpers — pure functions, used by Designator for binding face↔body
# tracks and for placing the overlay on the head region of a body bbox when
# the face is not visible.
# -----------------------------------------------------------------------------

def face_in_body(face_bbox, body_bbox, top_frac=0.40, above_frac=0.50):
    """True if the face plausibly belongs to this body.

    Face center must be horizontally within the body bbox, and vertically
    in one of two zones:
      • Inside the top `top_frac` of the body bbox (full-body framing).
      • Above the body's top by up to `above_frac × body_height` — the
        waist-up webcam case where YOLO's body bbox doesn't reach the head.

    `top_frac=0.40` and `above_frac=0.50` are deliberately generous, since
    body-detector boxes wobble at the top by several pixels.
    """
    fx1, fy1, fx2, fy2 = face_bbox
    bx1, by1, bx2, by2 = body_bbox
    if bx2 <= bx1 or by2 <= by1:
        return False
    fcx = (fx1 + fx2) * 0.5
    fcy = (fy1 + fy2) * 0.5
    if not (bx1 <= fcx <= bx2):
        return False
    body_h = by2 - by1
    lo = by1 - body_h * above_frac
    hi = by1 + body_h * top_frac
    return lo <= fcy <= hi


def body_top_distance(face_bbox, body_bbox):
    """Tie-breaker for face↔body binding when multiple bodies contain a face.

    Returns the squared distance from the face center to the body's top-center.
    Smaller is better. Returns +inf if the bbox is degenerate.
    """
    bx1, by1, bx2, by2 = body_bbox
    if bx2 <= bx1 or by2 <= by1:
        return float('inf')
    fcx = (face_bbox[0] + face_bbox[2]) * 0.5
    fcy = (face_bbox[1] + face_bbox[3]) * 0.5
    head_cx = (bx1 + bx2) * 0.5
    head_cy = by1
    dx = fcx - head_cx
    dy = fcy - head_cy
    return dx * dx + dy * dy


def head_region_from_body(body_bbox, last_face_size=None, last_face_offset=None):
    """Estimate a face-equivalent bbox at the head of a body bbox.

    Used to place the overlay when the actual face is not currently detected
    (back turned, occluded).

    `last_face_size` (w, h in px) is the most recent face dimensions — when
    provided, the returned bbox uses that size, preventing the overlay from
    "popping" in scale at face death/reacquisition.

    `last_face_offset` (dx, dy in px) is the displacement of the most recent
    face center relative to the body's top-center. When provided, the head
    region is centred at that offset from the current body top — this is the
    correct position for waist-up shots where the head sits *above* the body
    bbox, and tracks the head's true location as the body moves. Without it,
    we fall back to a heuristic 9% of body height below the body top.

    Returns (x1, y1, x2, y2) ints.
    """
    bx1, by1, bx2, by2 = body_bbox
    body_w = max(1, bx2 - bx1)
    body_h = max(1, by2 - by1)

    if last_face_offset is not None:
        dx, dy = last_face_offset
        head_cx = (bx1 + bx2) * 0.5 + dx
        head_cy = by1 + dy
    else:
        head_cx = (bx1 + bx2) * 0.5
        head_cy = by1 + body_h * 0.09   # roughly 1/11th from top

    if last_face_size is not None:
        fw, fh = last_face_size
        # Sanity-clamp: if the recorded face size is wildly larger than the
        # body box, we're probably dealing with a child detector glitch or a
        # tight crop. Fall back to body-relative estimation.
        if fw > body_w * 0.7 or fh > body_h * 0.4:
            fw = body_w * 0.20
            fh = body_h * 0.14
    else:
        # No prior face seen — estimate head size from body proportions.
        fw = body_w * 0.20
        fh = body_h * 0.14

    half_w = fw * 0.5
    half_h = fh * 0.5
    return (
        int(round(head_cx - half_w)),
        int(round(head_cy - half_h)),
        int(round(head_cx + half_w)),
        int(round(head_cy + half_h)),
    )