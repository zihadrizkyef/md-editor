"""Minimal Chrome DevTools Protocol client for driving the recorder."""
import json
import threading
import time
import urllib.request

import websocket


class Tab:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=60)
        self.next_id = 0
        self.send_lock = threading.Lock()
        self.cv = threading.Condition()
        self.responses = {}
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        while True:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                return
            if "id" in msg:
                with self.cv:
                    self.responses[msg["id"]] = msg
                    self.cv.notify_all()

    def call(self, method, **params):
        with self.send_lock:
            self.next_id += 1
            want = self.next_id
            self.ws.send(json.dumps({"id": want, "method": method, "params": params}))
        with self.cv:
            while want not in self.responses:
                if not self.cv.wait(60):
                    raise RuntimeError(f"{method}: timeout")
            msg = self.responses.pop(want)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def js(self, expression):
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        return result.get("result", {}).get("value")

    def shot(self, quality=85):
        data = self.call("Page.captureScreenshot", format="jpeg",
                         quality=quality, optimizeForSpeed=True,
                         captureBeyondViewport=False)
        import base64
        return base64.b64decode(data["data"])

    def click(self, x, y):
        base = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        self.call("Input.dispatchMouseEvent", type="mousePressed", **base)
        self.call("Input.dispatchMouseEvent", type="mouseReleased", **base)

    def insert(self, text):
        self.call("Input.insertText", text=text)

    def key(self, key, code=None, key_code=0, text=None, modifiers=0):
        base = {"modifiers": modifiers, "key": key, "code": code or key,
                "windowsVirtualKeyCode": key_code}
        self.call("Input.dispatchKeyEvent", type="rawKeyDown", **base)
        if text:
            self.call("Input.dispatchKeyEvent", type="char", text=text, **base)
        self.call("Input.dispatchKeyEvent", type="keyUp", **base)


def pick_page(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as fh:
                for target in json.load(fh):
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError("no debuggable page found")
