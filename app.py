"""MD Editor desktop app.

Built into a standalone MD Editor.exe (via PyInstaller) that can be set as
the default "Open with" app for .md files in Windows. Renders in its own
native window (via pywebview / Edge WebView2) -- no browser tab involved.

One desktop instance owns a local HTTP server and native window. Later
launches hand files to its authenticated queue so the existing window can
open them as tabs, including launches received while the UI initializes.
"""
import sys
import os
import threading
import urllib.parse
import http.server
import socketserver
import json
import time
import urllib.request
import urllib.error
import secrets
import hmac
import hashlib
import tempfile

# Importing the backend must not initialize a GUI (or require pywebview).
# The desktop dependency is loaded only by main().

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
RUNTIME_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), "runtime.json")
APP_ID = "md-editor-desktop"
HANDOFF_VERSION = 1
HANDOFF_HEADER = "X-MD-Editor-Token"
MAX_HANDOFF_BYTES = 64 * 1024


class WindowsInstanceMutex:
    """Keep the per-user instance claim until the native window exits.

    A kernel mutex survives neither crashes nor process termination, unlike a
    lock file. Its name is scoped to this Windows session and settings folder.
    Non-Windows backend tests do not need a desktop instance claim.
    """
    def __init__(self):
        self.handle = None
        self.owned = False
        self.kernel32 = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel32.CreateMutexW.restype = wintypes.HANDLE
            self.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            self.kernel32.ReleaseMutex.restype = wintypes.BOOL
            self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel32.CloseHandle.restype = wintypes.BOOL
            scope = os.path.normcase(os.path.abspath(RUNTIME_PATH)).encode("utf-8")
            name = "Local\\MD-Editor-" + hashlib.sha256(scope).hexdigest()
            self.handle = self.kernel32.CreateMutexW(None, False, name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def acquire(self):
        if self.owned:
            return True
        if self.handle is None:
            self.owned = True
            return True
        result = self.kernel32.WaitForSingleObject(self.handle, 0)
        if result in (0, 0x80):  # WAIT_OBJECT_0 or abandoned owner
            self.owned = True
            return True
        if result == 0x102:  # WAIT_TIMEOUT: another instance owns it
            return False
        raise OSError("Could not acquire the MD Editor instance mutex")

    def close(self):
        if self.handle is not None:
            if self.owned:
                self.kernel32.ReleaseMutex(self.handle)
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
        self.owned = False


def file_revision(path):
    """Opaque token that changes whenever the file's bytes change.

    Combines nanosecond mtime with size so that a rewrite that happens to
    land on the same mtime tick and the same length is still very unlikely
    to look identical. Returns None when the file cannot be stat'ed.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{st.st_mtime_ns:x}-{st.st_size:x}"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/instance":
            if not self.is_local_request():
                return self.send_json(403, {"error": "local requests only"})
            challenge = urllib.parse.parse_qs(parsed.query).get("challenge", [""])[0]
            if len(challenge) != 64 or any(c not in "0123456789abcdef" for c in challenge):
                return self.send_json(400, {"error": "invalid challenge"})
            proof = hmac.new(self.server.handoff_token.encode("ascii"),
                             challenge.encode("ascii"), hashlib.sha256).hexdigest()
            return self.send_json(200, {"app": APP_ID, "version": HANDOFF_VERSION,
                                        "instance": self.server.instance_id, "proof": proof})
        if parsed.path == "/api/open-events":
            if not self.is_local_request():
                return self.send_json(403, {"error": "local requests only"})
            # No JS callbacks: retain startup events until the initialized UI
            # polls. A failed HTTP write must not empty the queue.
            with self.server.pending_lock:
                events = list(self.server.pending_open_files)
                self.send_json(200, {"paths": events})
                del self.server.pending_open_files[:len(events)]
            return
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
        if parsed.path == "/api/open-events":
            return self.handle_open_event()
        if parsed.path == "/api/save":
            return self.handle_save(parsed)
        if parsed.path == "/api/settings":
            return self.handle_post_settings()
        if parsed.path == "/api/upload-image":
            return self.handle_upload_image(parsed)
        self.send_response(404)
        self.end_headers()

    def is_local_request(self):
        """Allow normal same-origin browser polling, not cross-site fetches."""
        expected = f"{HOST}:{self.server.server_address[1]}"
        if self.client_address[0] != HOST or self.headers.get("Host") != expected:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected}":
            return False
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return False
        referer = self.headers.get("Referer")
        if referer:
            parsed = urllib.parse.urlparse(referer)
            if parsed.scheme != "http" or parsed.netloc != expected:
                return False
        return True

    def handle_open_event(self):
        token = self.headers.get(HANDOFF_HEADER, "")
        if (not self.is_local_request() or not token.isascii() or
                not hmac.compare_digest(token, self.server.handoff_token)):
            return self.send_json(403, {"error": "invalid handoff token"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_HANDOFF_BYTES:
                return self.send_json(400, {"error": "invalid body length"})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("expected an object")
            request_id = payload.get("request_id")
            if (not isinstance(request_id, str) or len(request_id) != 32 or
                    any(c not in "0123456789abcdef" for c in request_id)):
                raise ValueError("invalid request id")
            path = payload.get("path")
            if path is not None:
                if not isinstance(path, str) or not path or "\u0000" in path:
                    raise ValueError("invalid path")
                path = os.path.abspath(path)
                if os.path.splitext(path)[1].lower() not in ALLOWED_EXT:
                    return self.send_json(403, {"error": "unsupported file type"})
        except (ValueError, UnicodeError, OSError):
            return self.send_json(400, {"error": "invalid handoff"})
        self.server.enqueue_open(path, request_id)
        return self.send_json(200, {"ok": True, "app": APP_ID,
                                    "instance": self.server.instance_id,
                                    "request_id": request_id})

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
        # Guard against an editor saving between our read and our stat: if the
        # revision moved, re-read so content and revision describe one state.
        rev = file_revision(path)
        for _ in range(3):
            after = file_revision(path)
            if after == rev:
                break
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                return self.send_json(500, {"error": str(e)})
            rev = after
        self.send_json(200, {
            "name": os.path.basename(path),
            "path": path,
            "content": content,
            "revision": rev,
            "mtime": os.stat(path).st_mtime,
        })

    def handle_save(self, parsed):
        path = self._resolve_path(parsed)
        if path is None:
            return
        qs = urllib.parse.parse_qs(parsed.query)
        base_rev = qs.get("base_rev", [None])[0]

        # Refuse a blind overwrite when the file changed on disk since the
        # client last read or wrote it. A revision of "-" means the client
        # opened a file that did not exist yet, which is always writable.
        if base_rev and base_rev != "-" and base_rev != file_revision(path):
            self.send_json(409, {
                "error": "conflict",
                "message": "File sudah berubah di luar MD Editor.",
                "revision": file_revision(path),
            })
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(body)
        except OSError as e:
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, {"ok": True, "revision": file_revision(path),
                             "mtime": os.stat(path).st_mtime})

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

    def __init__(self, *args, **kwargs):
        self.handoff_token = secrets.token_hex(32)
        self.instance_id = secrets.token_hex(16)
        self.pending_open_files = []
        self.pending_lock = threading.Lock()
        self.received_requests = set()
        self.window = None
        self.window_ready = False
        self.window_minimized = False
        self.focus_requested = False
        self.focus_running = False
        super().__init__(*args, **kwargs)

    def enqueue_open(self, path, request_id):
        with self.pending_lock:
            # Retries after a lost POST response must not enqueue twice.
            if request_id not in self.received_requests:
                self.received_requests.add(request_id)
                if path is not None:
                    self.pending_open_files.append(path)
            self.focus_requested = True
        self.request_focus()

    def attach_window(self, window):
        self.window = window
        window.events.shown += self.mark_window_ready
        window.events.minimized += self.mark_window_minimized
        window.events.restored += self.mark_window_restored
        window.events.maximized += self.mark_window_restored

    def mark_window_ready(self):
        with self.pending_lock:
            self.window_ready = True
        self.request_focus()

    def mark_window_minimized(self):
        with self.pending_lock:
            self.window_minimized = True

    def mark_window_restored(self):
        with self.pending_lock:
            self.window_minimized = False

    def request_focus(self):
        with self.pending_lock:
            if (not self.window_ready or self.window is None or
                    not self.focus_requested or self.focus_running):
                return
            self.focus_running = True
        # pywebview marshals restore/show onto the native UI thread. Keep
        # these calls off the HTTP thread and never evaluate JS to open files.
        threading.Thread(target=self._focus_window, daemon=True).start()

    def _focus_window(self):
        while True:
            with self.pending_lock:
                if not self.focus_requested:
                    self.focus_running = False
                    return
                self.focus_requested = False
                minimized = self.window_minimized
            try:
                if minimized:
                    self.window.restore()
                # On Windows show() invokes Show() and Activate(). There is
                # no public window.focus() method in current pywebview.
                self.window.show()
            except Exception:
                # A closing/native-unavailable window must not lose its queue
                # or turn a successfully accepted handoff into a failed POST.
                pass


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


def runtime_record(httpd):
    return {"app": APP_ID, "version": HANDOFF_VERSION, "pid": os.getpid(),
            "port": httpd.server_address[1], "instance": httpd.instance_id,
            "token": httpd.handoff_token}


def publish_runtime(httpd):
    """Publish only complete JSON while the instance mutex is held."""
    fd, temporary = tempfile.mkstemp(prefix="runtime-", suffix=".tmp",
                                     dir=os.path.dirname(RUNTIME_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(runtime_record(httpd), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, RUNTIME_PATH)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def remove_runtime(httpd):
    """Never let an exiting/failed instance delete a newer owner's record."""
    try:
        with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
            record = json.load(f)
        if (isinstance(record, dict) and record.get("instance") == httpd.instance_id and
                record.get("token") == httpd.handoff_token):
            os.remove(RUNTIME_PATH)
    except (OSError, ValueError):
        pass


def handoff_to_existing(file_path, request_id=None):
    request_id = request_id or secrets.token_hex(16)
    try:
        with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
            record = json.load(f)
        if not isinstance(record, dict):
            return False
        port, token, instance = (record.get(key) for key in ("port", "token", "instance"))
        if (record.get("app") != APP_ID or record.get("version") != HANDOFF_VERSION or
                type(port) is not int or not 1 <= port <= 65535 or
                not isinstance(token, str) or len(token) != 64 or
                any(c not in "0123456789abcdef" for c in token) or
                not isinstance(instance, str) or len(instance) != 32):
            return False
        base = f"http://{HOST}:{port}"
        # Do not send paths or the secret to a foreign server that inherited a
        # stale port. Require knowledge of the token via a fresh HMAC challenge.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        challenge = secrets.token_hex(32)
        with opener.open(base + "/api/instance?challenge=" + challenge, timeout=0.8) as response:
            identity = json.loads(response.read(MAX_HANDOFF_BYTES + 1))
        expected = hmac.new(token.encode("ascii"), challenge.encode("ascii"),
                            hashlib.sha256).hexdigest()
        if (not isinstance(identity, dict) or identity.get("app") != APP_ID or
                identity.get("version") != HANDOFF_VERSION or identity.get("instance") != instance or
                not isinstance(identity.get("proof"), str) or not identity["proof"].isascii() or
                not hmac.compare_digest(identity["proof"], expected)):
            return False
        data = {"path": os.path.abspath(file_path) if file_path else None,
                "request_id": request_id}
        req = urllib.request.Request(base + "/api/open-events", method="POST",
                                     data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json", HANDOFF_HEADER: token})
        with opener.open(req, timeout=0.8) as response:
            result = json.loads(response.read(MAX_HANDOFF_BYTES + 1))
        return (isinstance(result, dict) and result.get("ok") is True and
                result.get("app") == APP_ID and result.get("instance") == instance and
                result.get("request_id") == request_id)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return False


def claim_instance_or_handoff(mutex, file_path, timeout=30):
    """Wait through simultaneous startup without ever creating a second UI."""
    deadline = time.monotonic() + timeout
    request_id = secrets.token_hex(16)
    while True:
        if mutex.acquire():
            return True
        if handoff_to_existing(file_path, request_id):
            return False
        if time.monotonic() >= deadline:
            raise RuntimeError("The existing MD Editor instance is not responding; "
                               "close it and open the file again.")
        time.sleep(0.1)


def main():
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    mutex = WindowsInstanceMutex()
    httpd = None
    try:
        if not claim_instance_or_handoff(mutex, file_path):
            return
        import webview
        httpd = ReusableServer((HOST, 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        publish_runtime(httpd)
        run_desktop(httpd, file_path, webview)
    finally:
        if httpd is not None:
            remove_runtime(httpd)
            httpd.shutdown()
            httpd.server_close()
        mutex.close()


def run_desktop(httpd, file_path, webview):
    port = httpd.server_address[1]

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
    httpd.attach_window(window)

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
