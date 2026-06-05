# web/server.py
# Standalone Flask proxy — serves the mobile web UI and forwards all API calls
# to the internal PROFM API on port 5001.
# Spawned as a subprocess by main.py.

import os
import sys
import json
import urllib.request
import urllib.error
import logging

# Add project root to path so imports resolve correctly when spawned as subprocess.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Flask, Response, request, stream_with_context

INTERNAL = 'http://127.0.0.1:5001'
_HERE    = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(_HERE, 'templates'),
    static_folder=os.path.join(_HERE, 'static'),
)


# =============================================================================
# HTML entry point
# =============================================================================

@app.route('/')
def index():
    path = os.path.join(_HERE, 'templates', 'index.html')
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}


# =============================================================================
# MJPEG stream proxy  (keep connection open, stream chunks)
# =============================================================================

@app.route('/api/feed/<int:feed_id>/stream')
def stream_proxy(feed_id):
    def generate():
        try:
            req = urllib.request.urlopen(
                f'{INTERNAL}/feed/{feed_id}/stream', timeout=120
            )
            while True:
                chunk = req.read(8192)
                if not chunk:
                    break
                yield chunk
        except Exception:
            pass  # client disconnected or internal API not ready yet

    return Response(
        stream_with_context(generate()),
        content_type='multipart/x-mixed-replace; boundary=frame',
    )


# =============================================================================
# Generic REST proxy  (all other /api/* routes)
# =============================================================================

@app.route('/api/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    url = f'{INTERNAL}/{path}'

    try:
        if request.method == 'GET':
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read()
                ct   = resp.headers.get('Content-Type', 'application/json')
            return Response(body, status=200, content_type=ct)

        # POST — distinguish JSON from multipart (file uploads)
        content_type = request.content_type or ''
        raw_body     = request.get_data()

        req = urllib.request.Request(
            url,
            data=raw_body,
            headers={'Content-Type': content_type},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
        return Response(body, status=200, content_type='application/json')

    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status=exc.code,
                        content_type='application/json')
    except urllib.error.URLError as exc:
        err = json.dumps({'error': f'Internal API unavailable: {exc.reason}'})
        return Response(err, status=503, content_type='application/json')
    except Exception as exc:
        err = json.dumps({'error': str(exc)})
        return Response(err, status=500, content_type='application/json')


# =============================================================================
# Entry point
# =============================================================================

if __name__ == '__main__':
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    print('[WebServer] Mobile profiler UI running on http://0.0.0.0:8000')
    app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False)