"""Static server for the demo recorder.

Serves the app from the repo root and stubs the /api/* endpoints the UI calls,
so the front end can be recorded in a plain browser without the desktop shell.
"""
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "Catatan-Rilis.md": None,
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            return self._json({"theme": "light"})
        if parsed.path == "/api/open-events":
            return self._json({"path": None})
        if parsed.path == "/api/file":
            path = parse_qs(parsed.query).get("path", [""])[0]
            name = os.path.basename(path)
            if name in FILES and FILES[name] is not None:
                return self._json({
                    "content": FILES[name],
                    "path": path,
                    "revision": "1",
                })
            return self._json({"error": "not found"}, 404)
        if parsed.path == "/api/image":
            return self._json({"error": "no image"}, 404)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if parsed.path == "/api/save":
            return self._json({"ok": True, "revision": "2"})
        if parsed.path == "/api/settings":
            return self._json({"ok": True})
        if parsed.path == "/api/upload-image":
            return self._json({"path": "images/demo-image.png"})
        return self._json({"ok": True})


def start():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
