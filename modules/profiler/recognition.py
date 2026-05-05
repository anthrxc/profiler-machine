# modules/profiler/recognition.py
# Handles face recognition, enrollment, and the persons database.

import os
import sqlite3
import random
import numpy as np
import cv2
from datetime import datetime

DB_PATH         = os.path.join('database', 'profm.sqlite')
IMAGES_DIR      = os.path.join('database', 'enroll')
ENROLLED_DIR    = os.path.join('database', 'enrolled')

DESIGNATIONS = ['irrelevant', 'root', 'admin', 'threat', 'victim', 'perpetrator']

LIVE_ENROLL_DESIGNATIONS = ['irrelevant', 'perpetrator', 'victim', 'threat']
LIVE_ENROLL_WEIGHTS      = [0.89,         0.05,          0.05,     0.01]

SIMILARITY_THRESHOLD = 0.5
ROOT_SSN = '000-00-0000'


def _generate_ssn():
    a = random.randint(100, 999)
    b = random.randint(10, 99)
    c = random.randint(1000, 9999)
    return f"{a:03d}-{b:02d}-{c:04d}"


def _embedding_to_blob(embedding):
    return embedding.astype(np.float32).tobytes()


def _blob_to_embedding(blob):
    return np.frombuffer(blob, dtype=np.float32)


def _cosine_similarity(a, b):
    a = a / (np.linalg.norm(a) + 1e-10)
    b = b / (np.linalg.norm(b) + 1e-10)
    return float(np.dot(a, b))


def _get_random_description(designation):
    path = os.path.join('assets', 'descriptions', f"{designation}.txt")
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        return random.choice(lines) if lines else None
    except Exception:
        return None

def save_enrolled_image(ssn, frame, bbox):
    """Save a face crop to database/enrolled/<ssn>.jpg (only at enrollment time)."""
    os.makedirs(ENROLLED_DIR, exist_ok=True)
    x1, y1, x2, y2 = bbox
    pad = 10
    h, w = frame.shape[:2]
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    if x2 <= x1 or y2 <= y1:
        return
    crop = frame[y1:y2, x1:x2]
    cv2.imwrite(os.path.join(ENROLLED_DIR, f"{ssn}.jpg"), crop)


class RecognitionDB:
    def __init__(self):
        self._conn = None

    def connect(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        os.makedirs(ENROLLED_DIR, exist_ok=True)
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS persons (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                stylized_id         TEXT UNIQUE NOT NULL,
                name                TEXT,
                designation         TEXT NOT NULL DEFAULT 'irrelevant',
                notes               TEXT,
                embedding           BLOB NOT NULL,
                last_seen_timestamp TEXT,
                last_seen_feed      INTEGER
            )
        ''')
        self._conn.commit()

    def is_empty(self):
        cursor = self._conn.execute('SELECT COUNT(*) FROM persons')
        return cursor.fetchone()[0] == 0

    def count(self):
        cursor = self._conn.execute('SELECT COUNT(*) FROM persons')
        return cursor.fetchone()[0]

    def get_all(self):
        cursor = self._conn.execute(
            'SELECT id, stylized_id, name, designation, notes, last_seen_timestamp, last_seen_feed FROM persons'
        )
        return cursor.fetchall()

    def get_by_ssn(self, ssn):
        cursor = self._conn.execute(
            'SELECT id, stylized_id, name, designation, notes, last_seen_timestamp, last_seen_feed FROM persons WHERE stylized_id = ?',
            (ssn,)
        )
        return cursor.fetchone()

    def update_person(self, ssn, field, value):
        allowed = {'name', 'designation', 'notes'}
        if field not in allowed:
            return False
        self._conn.execute(
            f'UPDATE persons SET {field} = ? WHERE stylized_id = ?',
            (value, ssn)
        )
        self._conn.commit()
        return True

    def update_last_seen(self, ssn, feed_id):
        self._conn.execute(
            'UPDATE persons SET last_seen_timestamp = ?, last_seen_feed = ? WHERE stylized_id = ?',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), feed_id, ssn)
        )
        self._conn.commit()

    def remove_person(self, ssn):
        cursor = self._conn.execute('DELETE FROM persons WHERE stylized_id = ?', (ssn,))
        self._conn.commit()
        for d in [ENROLLED_DIR]:
            p = os.path.join(d, f"{ssn}.jpg")
            if os.path.exists(p):
                os.remove(p)
        return cursor.rowcount > 0

    def enroll(self, embedding, designation, name=None, notes=None, force_ssn=None):
        ssn = force_ssn if force_ssn else _generate_ssn()
        while not force_ssn and self.get_by_ssn(ssn):
            ssn = _generate_ssn()
        if notes is None:
            notes = _get_random_description(designation)
        self._conn.execute(
            '''INSERT INTO persons (stylized_id, name, designation, notes, embedding, last_seen_timestamp)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (ssn, name, designation, notes,
             _embedding_to_blob(embedding),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        self._conn.commit()
        return ssn

    def identify(self, embedding):
        cursor = self._conn.execute(
            'SELECT stylized_id, name, designation, embedding FROM persons'
        )
        rows = cursor.fetchall()
        best_match = None
        best_sim = SIMILARITY_THRESHOLD
        for ssn, name, designation, blob in rows:
            known_emb = _blob_to_embedding(blob)
            sim = _cosine_similarity(embedding, known_emb)
            if sim > best_sim:
                best_sim = sim
                best_match = (ssn, name, designation, sim)
        return best_match

    def enroll_from_image(self, app, image_path, designation='irrelevant', force_ssn=None):
        frame = cv2.imread(image_path)
        if frame is None:
            return None, False, f"Could not read image: {image_path}"
        faces = app.get(frame)
        if not faces:
            return None, False, "No face detected in image."
        if len(faces) > 1:
            return None, False, f"Multiple faces detected ({len(faces)}). Use a single-face image."
        embedding = faces[0].embedding
        if embedding is None:
            return None, False, "Could not extract embedding from face."
        ssn = self.enroll(embedding, designation, force_ssn=force_ssn)
        bbox = faces[0].bbox.astype(int)
        save_enrolled_image(ssn, frame, bbox)
        return ssn, True, None

    def enroll_startup_images(self, app):
        if not os.path.exists(IMAGES_DIR):
            os.makedirs(IMAGES_DIR, exist_ok=True)
            return []
        results = []
        image_files = [
            f for f in os.listdir(IMAGES_DIR)
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ]
        for filename in image_files:
            path = os.path.join(IMAGES_DIR, filename)
            is_first = self.is_empty()
            if is_first:
                ssn, success, error = self.enroll_from_image(
                    app, path, designation='root', force_ssn=ROOT_SSN
                )
                if success:
                    results.append((filename, ssn, True, "Enrolled as ROOT"))
                    os.remove(path)
                else:
                    results.append((filename, None, False, error))
            else:
                ssn, success, error = self.enroll_from_image(
                    app, path, designation='irrelevant'
                )
                if success:
                    results.append((filename, ssn, True, "Enrolled as IRRELEVANT"))
                    os.remove(path)
                else:
                    results.append((filename, None, False, error))
        return results
    
    def verify(self, ssn, embedding, threshold=SIMILARITY_THRESHOLD):
        cursor = self._conn.execute(
            'SELECT stylized_id, name, designation, embedding FROM persons WHERE stylized_id = ?',
            (ssn,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        found_ssn, name, designation, blob = row
        known_emb = _blob_to_embedding(blob)
        sim = _cosine_similarity(embedding, known_emb)

        if sim > threshold:
            return (found_ssn, name, designation, sim)
        return None