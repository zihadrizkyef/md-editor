"""Headless acceptance test for MD Editor's undo / redo.

Covers:
  1. toolbar buttons enable only when there is something to step into
  2. undo/redo of typing in the source textarea
  3. undo of a toolbar command that rewrites the buffer programmatically
  4. undo/redo inside the rich preview (Ctrl+Z there must not be handled twice)
  5. per-tab isolation, and a new edit discarding the redo tail
"""
import functools
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9341

FAILURES = []


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    handler = functools.partial(Quiet, directory=ROOT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def targets():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as fh:
            return json.load(fh)
    except urllib.error.URLError:
        return []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)
    return condition


class Session:
    def __init__(self):
        import websocket
        self.id = 0
        deadline = time.time() + 30
        page = None
        while time.time() < deadline and page is None:
            page = next((t for t in targets() if t["type"] == "page"), None)
            time.sleep(0.2)
        if page is None:
            raise RuntimeError("no page target")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        self.send("Runtime.enable")
        self.send("Page.enable")

    def send(self, method, **params):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def ev(self, expr):
        r = self.send("Runtime.evaluate", expression=expr,
                      returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return f"<EXC {d.get('text')} {(d.get('exception') or {}).get('description','')[:200]}>"
        return r["result"].get("value")

    def wait_ready(self, timeout=40):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ev("!!document.querySelector('#richEditor .milkdown .ProseMirror')"):
                time.sleep(0.8)
                return True
            time.sleep(0.25)
        return False

    def seed(self, markdown):
        """Load a document from scratch, the way opening a file does."""
        self.ev(f"setContent({json.dumps(markdown)})")
        time.sleep(0.6)

    def md(self):
        md = self.ev("getContent()")
        return md if isinstance(md, str) else ""

    def type_source(self, text):
        """Append text to the source textarea the way typing does."""
        self.ev(f"""
        (() => {{
          const el = document.getElementById('editor');
          el.value += {json.dumps(text)};
          el.dispatchEvent(new Event('input', {{bubbles:true}}));
          return true;
        }})()
        """)
        time.sleep(0.35)

    def type_preview(self, text):
        """Insert text at the end of the rich preview through a real edit."""
        self.ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          pm.focus();
          const sel = getSelection(); sel.removeAllRanges();
          const r = document.createRange(); r.selectNodeContents(pm); r.collapse(false);
          sel.addRange(r);
          document.execCommand('insertText', false, %s);
          return true;
        })()
        """ % json.dumps(text))
        time.sleep(0.5)

    def press(self, target, key, **mods):
        """Dispatch a keydown on `target` so the app's own handler runs."""
        self.ev(f"""
        (() => {{
          const el = document.querySelector({json.dumps(target)});
          const ev = new KeyboardEvent('keydown', Object.assign(
            {{key: {json.dumps(key)}, bubbles: true, cancelable: true}},
            {json.dumps(mods)}));
          el.dispatchEvent(ev);
          return true;
        }})()
        """)
        time.sleep(0.45)

    def click(self, selector):
        self.ev(f"document.querySelector({json.dumps(selector)}).click()")
        time.sleep(0.45)

    def button_disabled(self, which):
        return self.ev(f"document.getElementById('{which}').disabled")


def main():
    httpd, port = serve()
    profile = tempfile.mkdtemp(prefix="md-editor-undo-")
    url = f"http://127.0.0.1:{port}/index.html"
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        s = Session()
        print("\n== boot ==")
        if not check("rich editor mounts in preview pane", s.wait_ready()):
            return 1

        seed_md = "# Judul\n\nHalo dunia\n"
        s.seed(seed_md)
        check("undo is disabled on a fresh document", s.button_disabled("undoBtn") is True)
        check("redo is disabled on a fresh document", s.button_disabled("redoBtn") is True)

        print("\n== typing in the source textarea ==")
        s.type_source("tambahan")
        check("undo enables after an edit", s.button_disabled("undoBtn") is False)
        check("edit reached the buffer", "tambahan" in s.md(), s.md())

        s.click("#undoBtn")
        check("undo removes the typed text", s.md() == seed_md, repr(s.md()))
        check("redo enables after an undo", s.button_disabled("redoBtn") is False)

        s.click("#redoBtn")
        check("redo restores the typed text", "tambahan" in s.md(), s.md())
        check("redo is disabled again at the tip", s.button_disabled("redoBtn") is True)

        print("\n== a new edit discards the redo tail ==")
        s.click("#undoBtn")
        check("undo landed back on the base", s.md() == seed_md, repr(s.md()))
        s.type_source("baru")
        check("redo tail is dropped after a fresh edit",
              s.button_disabled("redoBtn") is True)

        print("\n== programmatic toolbar command ==")
        base = "Halo dunia ini teks biasa.\n"
        s.seed(base)
        # The toolbar acts on whichever surface owns the selection, so switch to
        # Edit view to exercise the textarea path deterministically.
        s.click('#viewSwitch button[data-view="edit"]')
        s.ev("""
        (() => {
          const el = document.getElementById('editor');
          const at = el.value.indexOf('dunia');
          el.focus();
          el.setSelectionRange(at, at + 5);
          return true;
        })()
        """)
        s.click('#toolbar button[data-cmd="bold"]')
        check("bold wrapped the selection", "**dunia**" in s.md(), s.md())
        s.click("#undoBtn")
        check("undo reverts the toolbar command", s.md() == base, repr(s.md()))

        print("\n== undo inside the rich preview ==")
        s.click('#viewSwitch button[data-view="preview"]')
        rich_base = "Halo dunia\n"
        s.seed(rich_base)
        s.type_preview("tambahan teks")
        check("preview edit reached the buffer", "tambahan teks" in s.md(), s.md())

        s.press("#richEditor .ProseMirror", "z", ctrlKey=True)
        after_undo = s.md()
        check("Ctrl+Z in the preview undoes the edit",
              "tambahan teks" not in after_undo, repr(after_undo))
        check("Ctrl+Z in the preview did not double-apply",
              after_undo.strip() == rich_base.strip(), repr(after_undo))

        s.press("#richEditor .ProseMirror", "y", ctrlKey=True)
        check("Ctrl+Y in the preview redoes the edit", "tambahan teks" in s.md(), s.md())

        s.press("#richEditor .ProseMirror", "z", ctrlKey=True, shiftKey=True)
        check("Ctrl+Shift+Z in the preview also redoes", "tambahan teks" in s.md(), s.md())

        print("\n== history is per tab ==")
        first = s.ev("activeTabId")
        s.ev("(() => { createTab({ content: 'Tab dua asli\\n', filename: 'dua.md' }); return true; })()")
        time.sleep(0.6)
        check("second tab is active", s.ev("activeTabId") != first)
        check("new tab starts with an empty history",
              s.button_disabled("undoBtn") is True)

        s.type_source("x")
        s.click("#undoBtn")
        check("undo in the second tab empties it back",
              s.md() == "Tab dua asli\n", repr(s.md()))

        s.ev(f"activateTab({first})")
        time.sleep(0.6)
        check("first tab content survived the second tab's undo",
              "tambahan teks" in s.md(), s.md())
        check("first tab still has its own undo history",
              s.button_disabled("undoBtn") is False)

        print("\n== nothing to undo at the base ==")
        s.ev("setContent('dasar\\n')")
        time.sleep(0.4)
        s.press("#editor", "z", ctrlKey=True)
        check("Ctrl+Z at the base keeps the document", s.md() == "dasar\n", repr(s.md()))

        print()
        if FAILURES:
            print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
            return 1
        print("All undo/redo checks passed.")
        return 0
    finally:
        proc.terminate()
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
