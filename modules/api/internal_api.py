# modules/api/internal_api.py
# Internal REST API — runs as a daemon thread inside the PROFM process on port 5001.
# Not exposed to the internet; only the web proxy on port 8000 talks to it.

import os
import time
import threading
import tempfile
import random
import cv2

from flask import Flask, Response, jsonify, request, send_file

from modules.core.command_processor import CommandProcessor
from modules.profiler.heuristics import generate as gen_heuristics
from modules.profiler.recognition import (
    LIVE_ENROLL_DESIGNATIONS, LIVE_ENROLL_WEIGHTS, save_enrolled_image
)

# Module-level singletons set by start_internal_api()
_feed_manager = None
_db           = None
_cmd_proc     = None


# =============================================================================
# Flask app factory
# =============================================================================

def _create_app():
    app = Flask(__name__)

    # ── Auth ─────────────────────────────────────────────────────────────────

    @app.route('/auth/login', methods=['POST'])
    def auth_login():
        data = request.get_json(force=True) or {}
        ssn  = data.get('ssn', '').strip()
        if not ssn:
            return jsonify({'ok': False, 'reason': 'missing_ssn'})

        person = _db.get_by_ssn(ssn)
        if not person:
            return jsonify({'ok': False, 'reason': 'not_found'})

        _, _, name, designation, _, _, _ = person
        if designation not in ('root', 'admin'):
            return jsonify({'ok': False, 'reason': 'unauthorized'})

        # Check if user is currently visible in any active feed
        visible = _feed_manager.get_visible_ssns()
        if ssn in visible:
            feed_id = _feed_manager.get_ssn_feed(ssn)
            return jsonify({
                'ok':          True,
                'ssn':         ssn,
                'name':        name or 'UNKNOWN',
                'designation': designation,
                'feed_id':     feed_id,
            })

        # User not in any feed — caller must verify via camera
        return jsonify({'ok': False, 'reason': 'not_in_feed'})

    @app.route('/auth/verify_face', methods=['POST'])
    def auth_verify_face():
        """Accept an uploaded image and verify it matches the claimed SSN."""
        ssn = request.form.get('ssn', '').strip()
        if not ssn:
            return jsonify({'ok': False, 'reason': 'missing_ssn'})

        person = _db.get_by_ssn(ssn)
        if not person or person[3] not in ('root', 'admin'):
            return jsonify({'ok': False, 'reason': 'unauthorized'})

        if 'image' not in request.files:
            return jsonify({'ok': False, 'reason': 'no_image'})

        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        request.files['image'].save(tmp.name)
        tmp.close()

        try:
            frame = cv2.imread(tmp.name)
            if frame is None:
                return jsonify({'ok': False, 'reason': 'bad_image'})

            faces = _feed_manager.app.get(frame)
            if not faces:
                return jsonify({'ok': False, 'reason': 'no_face'})

            embedding = faces[0].embedding
            if embedding is None:
                return jsonify({'ok': False, 'reason': 'no_embedding'})

            match = _db.verify(ssn, embedding)
            if match:
                _, _, name, designation, _, _, _ = person
                return jsonify({
                    'ok':          True,
                    'ssn':         ssn,
                    'name':        name or 'UNKNOWN',
                    'designation': designation,
                    'feed_id':     None,
                })
            return jsonify({'ok': False, 'reason': 'face_mismatch'})

        finally:
            os.unlink(tmp.name)

    # ── Feeds ─────────────────────────────────────────────────────────────────

    @app.route('/feeds')
    def feeds():
        result = []
        for fid, source, flip_h, flip_v, status in _feed_manager.list_feeds_with_config():
            result.append({
                'id':     fid,
                'source': str(source),
                'flip_h': flip_h,
                'flip_v': flip_v,
                'status': status,
            })
        return jsonify(result)

    @app.route('/feed/<int:feed_id>/stream')
    def feed_stream(feed_id):
        """MJPEG stream for a single feed."""
        def generate():
            while True:
                frames = _feed_manager.get_frames()
                frame  = frames.get(feed_id)
                if frame is not None:
                    _, jpeg = cv2.imencode(
                        '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65]
                    )
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + jpeg.tobytes()
                        + b'\r\n'
                    )
                time.sleep(1 / 15)   # 15 fps cap

        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/feed/<int:feed_id>/subjects')
    def feed_subjects(feed_id):
        return jsonify(_feed_manager.get_subjects_in_feed(feed_id))

    # ── Subjects ──────────────────────────────────────────────────────────────

    @app.route('/subjects')
    def subjects():
        rows   = _db.get_all()
        result = []
        for _, ssn, name, designation, notes, last_ts, last_feed in rows:
            result.append({
                'ssn':         ssn,
                'name':        name or 'UNKNOWN',
                'designation': designation,
                'notes':       notes,
                'last_seen':   last_ts,
                'last_feed':   last_feed,
            })
        return jsonify(result)

    @app.route('/subject/<ssn>')
    def subject(ssn):
        person = _db.get_by_ssn(ssn)
        if not person:
            return jsonify({'error': 'not_found'}), 404
        _, ssn, name, designation, notes, last_ts, last_feed = person
        h = gen_heuristics(ssn, designation)
        return jsonify({
            'ssn':         ssn,
            'name':        name or 'UNKNOWN',
            'designation': designation,
            'notes':       notes,
            'last_seen':   last_ts,
            'last_feed':   last_feed,
            'heuristics':  h,
        })

    @app.route('/subject/<ssn>/photo')
    def subject_photo(ssn):
        path = os.path.join('database', 'enrolled', f'{ssn}.jpg')
        if not os.path.exists(path):
            return '', 404
        return send_file(os.path.abspath(path), mimetype='image/jpeg')

    # ── Command execution ─────────────────────────────────────────────────────

    @app.route('/command', methods=['POST'])
    def command():
        data = request.get_json(force=True) or {}
        ssn  = data.get('ssn', '').strip()
        cmd  = data.get('command', '').strip()
        if not cmd:
            return jsonify({'output': '', 'ok': False})
        result = _cmd_proc.execute(cmd, active_user_ssn=ssn)
        return jsonify(result)

    # ── Recognize / enroll from uploaded image ────────────────────────────────

    @app.route('/recognize', methods=['POST'])
    def recognize():
        if 'image' not in request.files:
            return jsonify({'ok': False, 'reason': 'no_image'})

        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        request.files['image'].save(tmp.name)
        tmp.close()

        try:
            frame = cv2.imread(tmp.name)
            if frame is None:
                return jsonify({'ok': False, 'reason': 'bad_image'})

            faces = _feed_manager.app.get(frame)
            if not faces:
                return jsonify({'ok': False, 'reason': 'no_face'})
            if len(faces) > 1:
                return jsonify({
                    'ok':    False,
                    'reason': 'multiple_faces',
                    'count': len(faces),
                })

            embedding = faces[0].embedding
            if embedding is None:
                return jsonify({'ok': False, 'reason': 'no_embedding'})

            match = _db.identify(embedding)
            if match:
                ssn, name, designation, sim = match
                return jsonify({
                    'ok':          True,
                    'matched':     True,
                    'ssn':         ssn,
                    'name':        name or 'UNKNOWN',
                    'designation': designation,
                    'confidence':  round(float(sim) * 100, 1),
                })

            # No match — auto-enroll
            designation = random.choices(
                LIVE_ENROLL_DESIGNATIONS, weights=LIVE_ENROLL_WEIGHTS, k=1
            )[0]
            ssn  = _db.enroll(embedding, designation)
            bbox = faces[0].bbox.astype(int)
            save_enrolled_image(ssn, frame, bbox)

            return jsonify({
                'ok':          True,
                'matched':     False,
                'enrolled':    True,
                'ssn':         ssn,
                'name':        'UNKNOWN',
                'designation': designation,
            })

        finally:
            os.unlink(tmp.name)

    return app


# =============================================================================
# Startup helper
# =============================================================================

def start_internal_api(feed_manager, db, port=5001):
    """Start the internal API in a daemon thread.  Call once from main.py."""
    global _feed_manager, _db, _cmd_proc
    _feed_manager = feed_manager
    _db           = db
    _cmd_proc     = CommandProcessor(feed_manager, db)

    flask_app = _create_app()

    def _run():
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        try:
            flask_app.run(
                host='127.0.0.1',
                port=port,
                threaded=True,
                use_reloader=False,
            )
        except OSError as e:
            print(f'[InternalAPI] Could not start on port {port}: {e}')

    t = threading.Thread(target=_run, daemon=True, name='InternalAPI')
    t.start()
    print(f'[InternalAPI] Started on http://127.0.0.1:{port}')