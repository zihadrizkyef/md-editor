"""MD Editor desktop app.

Built into a standalone MD Editor.exe (via PyInstaller) that can be set as
the default "Open with" app for .md files in Windows. Renders in its own
native window (via pywebview / Edge WebView2) -- no browser tab involved.

Each launch is a self-contained instance: it spins up a small local HTTP
server on an OS-assigned free port (serving the app's static files and a
read/save API for the opened file), opens a native window pointed at it,
and shuts everything down when that window is closed.
"""
import sys
import os
import threading
import urllib.parse
import http.server
import socketserver
import json

import webview

HOST = "127.0.0.1"
ALLOWED_EXT = {".md", ".markdown", ".mdown", ".txt"}
ALLOWED_IMAGE_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
}


def resource_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = resource_dir()

def settings_path():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(root, "MD Editor")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


SETTINGS_PATH = settings_path()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/file":
            return self.handle_read(parsed)
        if parsed.path == "/api/settings":
            return self.handle_get_settings()
        if parsed.path == "/api/image":
            return self.handle_get_image(parsed)
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/save":
            return self.handle_save(parsed)
        if parsed.path == "/api/settings":
            return self.handle_post_settings()
        if parsed.path == "/api/upload-image":
            return self.handle_upload_image(parsed)
        self.send_response(404)
        self.end_headers()

    def handle_get_image(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        raw = qs.get("path", [None])[0]
        if not raw:
            return self.send_json(400, {"error": "missing path"})
        path = os.path.abspath(raw)
        ext = os.path.splitext(path)[1].lower()
        mime = ALLOWED_IMAGE_EXT.get(ext)
        if not mime:
            return self.send_json(403, {"error": "unsupported image type"})
        if not os.path.isfile(path):
            return self.send_json(404, {"error": "file not found"})
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def handle_upload_image(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        dir_raw = qs.get("dir", [None])[0]
        name_raw = qs.get("name", ["pasted-image.png"])[0]
        base, ext = os.path.splitext(name_raw)
        ext = ext.lower() if ext.lower() in ALLOWED_IMAGE_EXT else ".png"
        base = "".join(c for c in base if c.isalnum() or c in ("-", "_")) or "image"

        if dir_raw:
            target_dir = os.path.abspath(dir_raw)
            if not os.path.isdir(target_dir):
                return self.send_json(400, {"error": "target folder not found"})
        else:
            target_dir = os.path.join(os.path.dirname(SETTINGS_PATH), "pasted-images")
            os.makedirs(target_dir, exist_ok=True)

        filename = f"{base}{ext}"
        target_path = os.path.join(target_dir, filename)
        counter = 1
        while os.path.exists(target_path):
            filename = f"{base}-{counter}{ext}"
            target_path = os.path.join(target_dir, filename)
            counter += 1

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            with open(target_path, "wb") as f:
                f.write(body)
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, {"ok": True, "path": target_path, "filename": filename})

    def handle_get_settings(self):
        settings = {}
        try:
            if os.path.isfile(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            settings = {}
        self.send_json(200, settings)

    def handle_post_settings(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            incoming = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self.send_json(400, {"error": "invalid json"})
        settings = {}
        try:
            if os.path.isfile(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            settings = {}
        settings.update(incoming)
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f)
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, {"ok": True})

    def _resolve_path(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        raw = qs.get("path", [None])[0]
        if not raw:
            self.send_json(400, {"error": "missing path"})
            return None
        path = os.path.abspath(raw)
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXT:
            self.send_json(403, {"error": "unsupported file type"})
            return None
        return path

    def handle_read(self, parsed):
        path = self._resolve_path(parsed)
        if path is None:
            return
        if not os.path.isfile(path):
            return self.send_json(404, {"error": "file not found"})
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, {"name": os.path.basename(path), "path": path, "content": content})

    def handle_save(self, parsed):
        path = self._resolve_path(parsed)
        if path is None:
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(body)
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, {"ok": True})

    def send_json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def load_settings():
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_window_state(state):
    try:
        settings = load_settings()
        settings["window"] = state
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f)
    except OSError:
        pass


def main():
    file_path = sys.argv[1] if len(sys.argv) > 1 else None

    httpd = ReusableServer((HOST, 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    url = f"http://{HOST}:{port}/"
    if file_path:
        url += "?path=" + urllib.parse.quote(os.path.abspath(file_path))

    title = os.path.basename(file_path) + " - MD Editor" if file_path else "MD Editor"

    win_state = load_settings().get("window", {})
    maximized = bool(win_state.get("maximized", False))
    width = win_state.get("width", 1280)
    height = win_state.get("height", 800)
    x = win_state.get("x")
    y = win_state.get("y")

    window = webview.create_window(
        title,
        url,
        width=width,
        height=height,
        x=x,
        y=y,
        maximized=maximized,
        min_size=(760, 480),
    )

    # Remember window geometry / maximized state across restarts so the app
    # reopens the way it was left, instead of always defaulting to a small
    # fixed-size window.
    current_state = {
        "maximized": maximized,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
    }

    def _on_maximized():
        current_state["maximized"] = True

    def _on_restored():
        current_state["maximized"] = False

    def _on_resized(w, h):
        current_state["width"] = w
        current_state["height"] = h

    def _on_moved(mx, my):
        current_state["x"] = mx
        current_state["y"] = my

    def _on_closing():
        save_window_state(current_state)

    window.events.maximized += _on_maximized
    window.events.restored += _on_restored
    window.events.resized += _on_resized
    window.events.moved += _on_moved
    window.events.closing += _on_closing

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
