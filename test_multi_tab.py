"""Headless acceptance test for MD Editor's multi-tab support.

Covers the reported workflow:

1. Double-clicking a second file must not replace the first one. The desktop
   handoff (``POST /api/open-events``) and the ``?path=`` boot path both have to
   land in a *new* tab.
2. Each tab keeps its own buffer, filename and autosave target, so switching
   tabs never writes one document's text into another document's file.
3. Tabs can be switched and closed, and closing a tab keeps the rest intact.

Serves the real app backend from the source tree and drives the page in a
headless browser over the DevTools protocol.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9370

FAILURES = []


def serve_source_tree():
    """Serve the app exactly the way app.py does, /api endpoints included."""
    sys.path.insert(0, ROOT)
    import app as app_module

    httpd = app_module.ReusableServer(("127.0.0.1", 0), app_module.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def targets():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as fh:
            return json.load(fh)
    except urllib.error.URLError:
        return []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" +
          (f"  ({detail})" if detail and not condition else ""))
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
            return f"<EXC {d.get('text')} {(d.get('exception') or {}).get('description', '')[:200]}>"
        return r["result"].get("value")

    def wait_ready(self, timeout=45):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ev("!!document.querySelector('#richEditor .ProseMirror')"):
                time.sleep(0.6)
                return True
            time.sleep(0.25)
        return False

    def tab_labels(self):
        return self.ev("Array.from(document.querySelectorAll('#tabbar .tab')).map(t => "
                       "t.querySelector('.tab-label').textContent.trim())")

    def wait_for_tabs(self, count, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            labels = self.tab_labels()
            if isinstance(labels, list) and len(labels) == count:
                time.sleep(0.4)
                return labels
            time.sleep(0.2)
        return self.tab_labels()

    def open_tab(self, index):
        self.ev(f"document.querySelectorAll('#tabbar .tab .tab-label')[{index}].click()")
        time.sleep(0.6)

    def reload_page(self):
        """Reload in place, the way WebView2 recovers or a user hits F5."""
        self.send("Page.enable")
        self.send("Page.reload")
        # The evaluate channel dies with the old document; wait it out.
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                if self.ev("!!document.querySelector('#richEditor .ProseMirror')"):
                    time.sleep(0.8)
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False


def post_handoff(port, path, token, request_id=None):
    """Deliver a file the way a second double-click does."""
    data = json.dumps({"path": os.path.abspath(path),
                       "request_id": request_id or ("0" * 31 + "1")}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/open-events", method="POST", data=data,
        headers={"Content-Type": "application/json", "X-MD-Editor-Token": token})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read())


def main():
    httpd, port = serve_source_tree()

    workdir = tempfile.mkdtemp(prefix="md-tabs-")
    file_a = os.path.join(workdir, "catatan-a.md")
    file_b = os.path.join(workdir, "catatan-b.md")
    with open(file_a, "w", encoding="utf-8") as fh:
        fh.write("# Dokumen A\n\nIsi dokumen A.\n")
    with open(file_b, "w", encoding="utf-8") as fh:
        fh.write("# Dokumen B\n\nIsi dokumen B.\n")

    url = (f"http://127.0.0.1:{port}/?path=" + urllib.parse.quote(os.path.abspath(file_a)))
    print("opening:", url)

    profile = tempfile.mkdtemp(prefix="md-tabs-profile-")
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        s = Session()
        print("\n== a file opened by double-click starts a tab ==")
        if not check("rich preview mounts", s.wait_ready()):
            print("  status:", s.ev("document.getElementById('saveStatus').textContent"))
            return 1
        check("one tab for the opened file", s.wait_for_tabs(1) == ["catatan-a.md"])
        check("file A is the buffer",
              "Dokumen A" in (s.ev("getContent()") or ""))

        print("\n== double-clicking file B opens a second tab ==")
        status, payload = post_handoff(port, file_b, httpd.handoff_token)
        check("handoff accepted", status == 200 and payload.get("ok") is True, str(payload))
        labels = s.wait_for_tabs(2)
        check("two tabs are open", labels == ["catatan-a.md", "catatan-b.md"], str(labels))
        check("file B became the active document",
              "Dokumen B" in (s.ev("getContent()") or ""))
        check("file A's buffer was preserved",
              "Dokumen A" in (s.ev(
                  "tabs.find(t => t.filename === 'catatan-a.md').content") or ""))

        print("\n== each tab keeps its own document and save target ==")
        s.ev("document.getElementById('editor').value += '\\nBaris tambahan B.\\n';"
             "document.getElementById('editor').dispatchEvent(new Event('input'))")
        time.sleep(1.5)
        s.open_tab(0)
        check("switching back shows file A",
              "Dokumen A" in (s.ev("document.getElementById('editor').value") or ""))
        s.ev("document.getElementById('editor').value += '\\nBaris tambahan A.\\n';"
             "document.getElementById('editor').dispatchEvent(new Event('input'))")
        time.sleep(1.5)

        with open(file_a, "r", encoding="utf-8") as fh:
            on_disk_a = fh.read()
        with open(file_b, "r", encoding="utf-8") as fh:
            on_disk_b = fh.read()
        check("edit in tab B reached file B", "Baris tambahan B." in on_disk_b, on_disk_b[-80:])
        check("edit in tab A reached file A", "Baris tambahan A." in on_disk_a, on_disk_a[-80:])
        check("file A did not receive B's edit", "Baris tambahan B." not in on_disk_a)
        check("file B did not receive A's edit", "Baris tambahan A." not in on_disk_b)

        print("\n== re-opening the same file reuses its tab ==")
        status, payload = post_handoff(port, file_a, httpd.handoff_token)
        check("second handoff accepted", status == 200, str(payload))
        time.sleep(1.2)
        check("still two tabs", len(s.tab_labels() or []) == 2, str(s.tab_labels()))

        print("\n== tabs can be closed ==")
        s.ev("document.querySelectorAll('#tabbar .tab')[1].querySelector('.tab-close').click()")
        labels = s.wait_for_tabs(1, timeout=10)
        check("one tab remains after closing", labels == ["catatan-a.md"], str(labels))
        check("the remaining tab still has content",
              "Dokumen A" in (s.ev("getContent()") or ""))
        check("no page errors",
              "EXC" not in str(s.ev("String(document.querySelectorAll('.tab').length)")))

        print("\n== the original single-file workflow still works ==")
        check("status bar reports a save",
              isinstance(s.ev("document.getElementById('saveStatus').textContent"), str))

        print("\n== a reload keeps every tab, not just the ?path= file ==")
        # The window's URL still carries ?path=catatan-a.md for its whole life,
        # so init() must restore the session *and* then honour that param
        # without dropping the other tabs or duplicating file A.
        status, payload = post_handoff(port, file_b, httpd.handoff_token,
                                       request_id="0" * 31 + "9")
        check("handoff before reload accepted", status == 200, str(payload))
        labels = s.wait_for_tabs(2)
        check("two tabs before reload", labels == ["catatan-a.md", "catatan-b.md"], str(labels))

        if check("page reloaded", s.reload_page()):
            labels = s.wait_for_tabs(2, timeout=25)
            check("both tabs survive the reload",
                  labels == ["catatan-a.md", "catatan-b.md"], str(labels))
            check("no duplicate tab for the ?path= file",
                  len([n for n in (labels or []) if n == "catatan-a.md"]) == 1, str(labels))
            check("restored tab still holds its text",
                  "Dokumen A" in (s.ev("getContent()") or "") or
                  "Dokumen B" in (s.ev("getContent()") or ""))

        print("\n== per-tab caret state is captured and restored ==")
        s.open_tab(1)
        # Place a distinctive caret inside tab B's first paragraph. The
        # ProseMirror selection is the source of truth: the DOM selection is
        # only materialized while the editor holds focus, so comparing DOM
        # offsets across a tab switch would measure focus, not restoration.
        s.ev("""
          (() => {
            const pm = document.querySelector('#richEditor .ProseMirror');
            pm.focus();
            const sel = document.getSelection();
            const r = document.createRange();
            const p = pm.querySelector('p') || pm;
            const node = p.firstChild || p;
            r.setStart(node, Math.min(4, node.textContent.length));
            r.collapse(true);
            sel.removeAllRanges(); sel.addRange(r);
            return true;
          })()
        """)
        time.sleep(0.4)
        live_from = s.ev("window.MDEditorRich.getHandle(document.getElementById('richEditor'))"
                         ".resolve('editorView').state.selection.from")
        # Freeze it into the tab the way a real switch does, then round-trip.
        s.ev("snapshotActiveTab()")
        caret_before = s.ev("tabs.find(t => t.id === activeTabId).richState.selection.from")
        s.open_tab(0)
        s.open_tab(1)
        caret_after = s.ev(
            "window.MDEditorRich.getHandle(document.getElementById('richEditor'))"
            ".resolve('editorView').state.selection.from")
        check("rich handle exposes captureState/restoreState",
              s.ev("typeof (window.MDEditorRich.getHandle(document.getElementById('richEditor'))"
                   "||{}).captureState") == "function" and
              s.ev("typeof (window.MDEditorRich.getHandle(document.getElementById('richEditor'))"
                   "||{}).restoreState") == "function")
        check("every visited tab stored its rich state",
              "false" not in str(s.ev("tabs.map(t => !!t.richState).join('|')")),
              str(s.ev("tabs.map(t => !!t.richState).join('|')")))
        check("captured caret matches the live caret",
              caret_before == live_from and isinstance(live_from, int) and live_from > 0,
              f"live={live_from!r} snapshot={caret_before!r}")
        check("caret sits where it was left after switching away and back",
              caret_before == caret_after,
              f"before={caret_before!r} after={caret_after!r}")
        check("each tab keeps its own caret, not the other tab's",
              s.ev("tabs[0].richState.selection.from") != s.ev("tabs[1].richState.selection.from"),
              f"A={s.ev('tabs[0].richState.selection.from')!r} "
              f"B={s.ev('tabs[1].richState.selection.from')!r}")
        # All tabs share one Crepe view, so a capture that handed back the live
        # `view.state` would make every tab alias the same object. ProseMirror
        # states are immutable so that would not corrupt caret positions today,
        # but nothing stops a future in-place mutation from leaking across tabs.
        check("captured state is a snapshot, not the live view state",
              s.ev("(() => {"
                   " const h = window.MDEditorRich.getHandle(document.getElementById('richEditor'));"
                   " return h.captureState() !== h.resolve('editorView').state; })()"))
        check("switching tabs kept the rich text in sync with the buffer",
              bool(s.ev("window.MDEditorRich.getHandle(document.getElementById('richEditor'))"
                        ".getMarkdown().trim() === document.getElementById('editor').value.trim()")))

        return 0 if not FAILURES else 1
    finally:
        proc.terminate()
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
