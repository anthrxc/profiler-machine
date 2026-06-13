# web/server.py
# Standalone Flask proxy — serves the mobile web UI over HTTPS and forwards all
# API calls to the internal PROFM API on port 5001.
# Spawned as a subprocess by main.py.
#
# HTTPS: a self-signed cert is generated once into web/certs/ on first run.
# The browser shows a one-time security warning; accept it and camera will work.
# Add web/certs/ to .gitignore — do not commit private keys.

import os
import sys
import json
import ssl
import datetime
import threading
import urllib.request
import urllib.error
import logging

# Add project root to path so imports resolve correctly when spawned as subprocess.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Flask, Response, request, stream_with_context

_HERE     = os.path.dirname(os.path.abspath(__file__))
_CERT_DIR = os.path.join(_HERE, 'certs')
_CERT     = os.path.join(_CERT_DIR, 'server.crt')
_KEY      = os.path.join(_CERT_DIR, 'server.key')


# =============================================================================
# Config  (config/web.json — falls back to defaults if missing/invalid)
# =============================================================================

_DEFAULTS = {
    'https_port':           8000,
    'redirect_port':        8001,
    'internal_api_port':    5001,
    'host':                 '0.0.0.0',
    'enable_http_redirect': True,
}

def _load_config():
    cfg = dict(_DEFAULTS)
    path = os.path.join(_ROOT, 'config', 'web.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            user = json.load(fh)
        for k in _DEFAULTS:
            if k in user:
                cfg[k] = user[k]
    except FileNotFoundError:
        print('[WebServer] config/web.json not found — using defaults')
    except (json.JSONDecodeError, OSError) as e:
        print(f'[WebServer] config/web.json invalid ({e}) — using defaults')
    return cfg

CONFIG       = _load_config()
HTTPS_PORT   = CONFIG['https_port']
REDIRECT_PORT = CONFIG['redirect_port']
HOST         = CONFIG['host']
INTERNAL     = f"http://127.0.0.1:{CONFIG['internal_api_port']}"

app = Flask(
    __name__,
    template_folder=os.path.join(_HERE, 'templates'),
    static_folder=os.path.join(_HERE, 'static'),
)


# =============================================================================
# Self-signed cert generation  (runs once, result persisted to web/certs/)
# =============================================================================

def _cert_pair_valid():
    """Return True if cert+key exist, parse, and actually match each other."""
    if not (os.path.exists(_CERT) and os.path.exists(_KEY)):
        return False
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(_CERT, _KEY)   # raises if corrupt or mismatched
        return True
    except Exception as e:
        print(f'[WebServer] Existing cert invalid ({e}) — regenerating')
        return False


def _ensure_cert():
    """Generate a self-signed TLS cert if missing or invalid."""
    if _cert_pair_valid():
        return

    # Remove any stale/corrupt files before regenerating
    for p in (_CERT, _KEY):
        if os.path.exists(p):
            os.remove(p)

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        print('[WebServer] Generating self-signed TLS certificate (ECDSA P-256)...')
        os.makedirs(_CERT_DIR, exist_ok=True)

        # ECDSA P-256: ~half the cert size of RSA-2048.  Keeps the TLS
        # handshake within Tailscale's 1280-byte MTU — large RSA certs can
        # fragment and stall the handshake on mobile clients over WireGuard.
        key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PROFM')])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName('localhost'),
                    x509.DNSName('*.ts.net'),   # Tailscale domain wildcard hint
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256(), default_backend())
        )

        with open(_CERT, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        with open(_KEY, 'wb') as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))

        print(f'[WebServer] Certificate written to {_CERT_DIR}')
        print('[WebServer] NOTE: Add web/certs/ to .gitignore')

    except ImportError:
        print('[WebServer] WARNING: cryptography library not found — falling back to HTTP')
        print('[WebServer] Camera will not work over plain HTTP (non-localhost)')


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
# Helpers
# =============================================================================

def _get_local_ips():
    """Return a list of non-loopback IPv4 addresses for this machine."""
    import socket
    ips = set()
    try:
        # Preferred: which interface would route to the internet?
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.'):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips) or ['localhost']


def _run_http_redirect():
    """Minimal HTTP server that redirects every request to the HTTPS port.
    Uses http.server (stdlib) to avoid running two Werkzeug instances in one process."""
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            host = (self.headers.get('Host') or 'localhost').split(':')[0]
            self.send_response(301)
            self.send_header('Location', f'https://{host}:{HTTPS_PORT}{self.path}')
            self.end_headers()
        def do_POST(self):
            self.do_GET()
        def log_message(self, *_):
            pass  # silence

    with http.server.HTTPServer((HOST, REDIRECT_PORT), _Handler) as srv:
        srv.serve_forever()


# =============================================================================
# Parent watchdog — exit when the PROFM process dies (prevents zombie servers)
# =============================================================================

def _start_parent_watchdog():
    """If --parent-pid was passed, poll it and self-terminate when it dies.
    Prevents orphaned web servers holding port 8000 after PROFM crashes
    or is force-killed (atexit doesn't fire on hard kills)."""
    if '--parent-pid' not in sys.argv:
        return
    try:
        parent_pid = int(sys.argv[sys.argv.index('--parent-pid') + 1])
    except (IndexError, ValueError):
        return

    import psutil

    def _watch():
        import time
        while True:
            if not psutil.pid_exists(parent_pid):
                print(f'[WebServer] Parent (PID {parent_pid}) died — shutting down')
                os._exit(0)
            time.sleep(2)

    threading.Thread(target=_watch, daemon=True).start()
    print(f'[WebServer] Watching parent PID {parent_pid}')


# =============================================================================
# Entry point
# =============================================================================

if __name__ == '__main__':
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    _start_parent_watchdog()
    _ensure_cert()

    ips = _get_local_ips()

    if os.path.exists(_CERT) and os.path.exists(_KEY):
        if CONFIG['enable_http_redirect']:
            threading.Thread(target=_run_http_redirect, daemon=True).start()

        # Explicit SSL context — maximum client compatibility
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.load_cert_chain(_CERT, _KEY)

        print('[WebServer] ──────────────────────────────────────────────')
        print('[WebServer] PROFM mobile UI  (HTTPS — camera enabled)')
        for ip in ips:
            print(f'[WebServer]   https://{ip}:{HTTPS_PORT}')
        if CONFIG['enable_http_redirect']:
            print('[WebServer]')
            print('[WebServer] HTTP auto-redirect  (plain http → https above)')
            for ip in ips:
                print(f'[WebServer]   http://{ip}:{REDIRECT_PORT}')
        print('[WebServer]')
        print('[WebServer] First visit: browser will warn about self-signed cert.')
        print('[WebServer] Click "Advanced" → "Proceed" once per device.')
        print('[WebServer] ──────────────────────────────────────────────')

        app.run(host=HOST, port=HTTPS_PORT, threaded=True,
                use_reloader=False, ssl_context=ssl_ctx)
    else:
        print('[WebServer] ──────────────────────────────────────────────')
        print('[WebServer] PROFM mobile UI  (HTTP — camera disabled)')
        for ip in ips:
            print(f'[WebServer]   http://{ip}:{HTTPS_PORT}')
        print('[WebServer] ──────────────────────────────────────────────')
        app.run(host=HOST, port=HTTPS_PORT, threaded=True, use_reloader=False)