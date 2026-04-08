import cv2
import numpy as np
import onnxruntime as ort


class AntiSpoofModel:
    def __init__(self, model_path: str, scale: float = 2.7):
        self.scale = scale
        self.session = ort.InferenceSession(
            model_path,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        shape = self.session.get_inputs()[0].shape
        self.input_h = int(shape[2])
        self.input_w = int(shape[3])

    def _crop_face_scaled(self, frame, bbox):
        x1, y1, x2, y2 = map(int, bbox)
        h, w = frame.shape[:2]

        bw = x2 - x1
        bh = y2 - y1
        if bw <= 0 or bh <= 0:
            return None

        scale = min((h - 1) / bh, (w - 1) / bw, self.scale)

        new_w = bw * scale
        new_h = bh * scale

        cx = x1 + bw / 2
        cy = y1 + bh / 2

        nx1 = max(0, int(cx - new_w / 2))
        ny1 = max(0, int(cy - new_h / 2))
        nx2 = min(w - 1, int(cx + new_w / 2))
        ny2 = min(h - 1, int(cy + new_h / 2))

        if nx2 <= nx1 or ny2 <= ny1:
            return None

        crop = frame[ny1:ny2 + 1, nx1:nx2 + 1]
        if crop.size == 0:
            return None

        return cv2.resize(crop, (self.input_w, self.input_h))

    def _preprocess(self, crop):
        # Match repo ONNX preprocessing exactly
        crop = crop.astype(np.float32)
        crop = np.transpose(crop, (2, 0, 1))
        crop = np.expand_dims(crop, axis=0)
        return crop

    @staticmethod
    def _softmax(x):
        e_x = np.exp(x - np.max(x, axis=1, keepdims=True))
        return e_x / e_x.sum(axis=1, keepdims=True)

    def predict_from_bbox(self, frame, bbox):
        crop = self._crop_face_scaled(frame, bbox)
        if crop is None:
            return {"ok": False, "is_live": False, "score": 0.0, "label_idx": -1, "probs": None}

        x = self._preprocess(crop)
        logits = self.session.run([self.output_name], {self.input_name: x})[0]
        probs = self._softmax(logits)

        label_idx = int(np.argmax(probs))
        score = float(probs[0, label_idx])

        # Repo logic: only class 1 is Real; all others are Fake
        is_live = (label_idx == 1)

        print(f"[AntiSpoof] label_idx={label_idx}, score={score:.4f}, probs={probs[0]}")

        return {
            "ok": True,
            "is_live": is_live,
            "score": score,
            "label_idx": label_idx,
            "probs": probs[0].tolist(),
        }