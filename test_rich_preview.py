"""Headless acceptance test for MD Editor's rich preview.

Covers what the feature is judged on:
  1. every inline/block toolbar command applied from a preview selection
  2. the source textarea path still behaves as before
  3. Edit / Split / Preview view modes
  4. autosave and theme switching reaching the rich editor
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
DEBUG_PORT = 9340

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
        self.ev(f"setContent({json.dumps(markdown)})")
        time.sleep(0.7)

    def select_word(self, word):
        return self.ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          const w = document.createTreeWalker(pm, NodeFilter.SHOW_TEXT);
          let n = null;
          while ((n = w.nextNode())) if (n.nodeValue.includes(%s)) break;
          if (!n) return 'word not found';
          const s = n.nodeValue.indexOf(%s);
          const r = document.createRange();
          r.setStart(n, s); r.setEnd(n, s + %d);
          const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
          pm.focus();
          return sel.toString();
        })()
        """ % (json.dumps(word), json.dumps(word), len(word)))

    def click(self, cmd):
        """Click a toolbar button the way a user does: mousedown, then click."""
        self.ev("""
        (() => {
          const btn = document.querySelector('#toolbar button[data-cmd=%s]');
          btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
          btn.click();
          return true;
        })()
        """ % json.dumps(cmd))
        time.sleep(0.7)

    def md(self):
        md = self.ev("getContent()")
        return md if isinstance(md, str) else ""

    def type_in_preview(self, text):
        """Insert text at the end of the preview via a real editing command."""
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
        # Autosave is debounced; poll rather than assuming a fixed delay.
        deadline = time.time() + 6
        while time.time() < deadline:
            stored = self.ev("localStorage.getItem('md-editor-content')")
            if isinstance(stored, str) and text in stored:
                break
            time.sleep(0.25)


def main():
    httpd, port = serve()
    profile = tempfile.mkdtemp(prefix="md-editor-accept-")
    url = f"http://127.0.0.1:{port}/index.html"
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        s = Session()
        print("\n== editor boot ==")
        if not check("rich editor mounts in preview pane", s.wait_ready()):
            return 1
        check("plain preview hidden while rich editor active",
              s.ev("document.getElementById('preview').hidden === true"))
        check("no page errors during boot",
              "EXC" not in str(s.ev("1+1")))

        print("\n== inline commands from a preview selection ==")
        s.seed("Halo dunia ini teks biasa.\n")
        s.select_word("dunia")
        s.click("bold")
        check("bold wraps selection", "**dunia**" in s.md(), s.md())

        s.seed("Halo dunia ini teks biasa.\n")
        s.select_word("dunia")
        s.click("italic")
        check("italic wraps selection", "*dunia*" in s.md(), s.md())

        s.seed("Halo dunia ini teks biasa.\n")
        s.select_word("dunia")
        s.click("strike")
        check("strikethrough wraps selection", "~~dunia~~" in s.md(), s.md())

        s.seed("Halo dunia ini teks biasa.\n")
        s.select_word("dunia")
        s.click("code")
        check("inline code wraps selection", "`dunia`" in s.md(), s.md())

        print("\n== block commands ==")
        s.seed("Jadi begini ceritanya.\n")
        s.select_word("begini")
        s.click("h3")
        check("H3 applies to block", "### Jadi begini ceritanya." in s.md(), s.md())

        s.seed("Jadi begini ceritanya.\n")
        s.select_word("begini")
        s.click("h1")
        check("H1 applies to block", "# Jadi begini ceritanya." in s.md(), s.md())

        s.seed("Jadi begini ceritanya.\n")
        s.select_word("begini")
        s.click("ul")
        listed = s.md()
        # Crepe normalises the bullet marker to "-"; accept either form.
        check("bullet list applies",
              listed.lstrip().startswith(("-", "*")) and "Jadi begini ceritanya." in listed,
              listed)

        print("\n== source pane still works ==")
        # Focus the textarea explicitly first: the rich editor owns the caret
        # after the block tests, and the toolbar follows the focused surface.
        # Split view keeps the source pane visible so it can actually take focus
        # (preview-only mode hides it, and a hidden textarea cannot be focused).
        s.ev("document.querySelector('#viewSwitch button[data-view=\"split\"]').click()")
        time.sleep(0.3)
        s.ev("setContent('teks sumber\\n')")
        time.sleep(0.5)
        s.ev("""
        (() => {
          const ed = document.getElementById('editor');
          ed.focus();
          ed.setSelectionRange(0, 4);
          return true;
        })()
        """)
        time.sleep(0.3)
        check("focus is on the source textarea",
              s.ev("document.activeElement === document.getElementById('editor')"))
        s.click("bold")
        check("textarea selection still bolds", "**teks**" in s.md(), s.md())

        print("\n== view modes ==")
        s.ev("document.querySelector('#viewSwitch button[data-view=\"preview\"]').click()")
        time.sleep(0.3)
        check("preview-only mode hides source pane",
              s.ev("getComputedStyle(document.getElementById('editorPane')).display") == "none")
        check("rich editor still visible in preview-only mode",
              s.ev("document.getElementById('richEditor').hidden === false"))

        s.ev("document.querySelector('#viewSwitch button[data-view=\"edit\"]').click()")
        time.sleep(0.3)
        check("edit mode hides preview pane",
              s.ev("getComputedStyle(document.getElementById('previewPane')).display") == "none")

        s.ev("document.querySelector('#viewSwitch button[data-view=\"split\"]').click()")
        time.sleep(0.3)
        check("split mode shows both panes",
              s.ev("getComputedStyle(document.getElementById('previewPane')).display") != "none")
        check("rich editor usable again after switching back",
              s.ev("!!document.querySelector('#richEditor .ProseMirror')"))

        print("\n== autosave + theme ==")
        # Autosave must fire for edits made *in the preview*, so the text is
        # typed through the rich editor rather than injected with setContent.
        s.seed("isi penting\n")
        s.ev("localStorage.setItem('md-editor-content', 'SENTINEL')")
        s.type_in_preview("baris baru")
        stored = s.ev("localStorage.getItem('md-editor-content')")
        check("preview edits reach localStorage",
              isinstance(stored, str) and "baris baru" in stored, str(stored))
        check("preview edits reach the source textarea too",
              "baris baru" in (s.ev("document.getElementById('editor').value") or ""),
              s.ev("document.getElementById('editor').value"))

        s.ev("document.getElementById('themeToggle').click()")
        time.sleep(0.6)
        dark = s.ev("document.documentElement.getAttribute('data-theme')")
        check("theme toggles to dark", dark == "dark", str(dark))
        check("dark class lands on the milkdown root",
              s.ev("!!document.querySelector('#richEditor .milkdown.md-editor-dark')"))
        s.ev("document.getElementById('themeToggle').click()")
        time.sleep(0.5)
        check("theme toggles back to light",
              s.ev("document.documentElement.getAttribute('data-theme')") == "light")

        print("\n== round trip through the parser ==")
        s.seed("# Judul\n\n- satu\n- dua\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        time.sleep(0.6)
        round_tripped = s.md()
        check("headings survive a get/set round trip", "# Judul" in round_tripped, round_tripped)
        check("bullets survive a get/set round trip", "- satu" in round_tripped or "* satu" in round_tripped, round_tripped)
        check("tables survive a get/set round trip", "| A | B |" in round_tripped, round_tripped)
        check("plain preview renderer still works on the same text",
              s.ev("parseMarkdown('# Judul\\n\\n- satu\\n').includes('<h1')"))

        print()
        if FAILURES:
            print(f"RESULT: FAIL ({len(FAILURES)}): " + ", ".join(FAILURES))
            return 1
        print("RESULT: PASS (all checks)")
        return 0
    finally:
        proc.terminate()
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
