"""Launch the packaged exe, open a real .md via ?path=, and capture screenshots.

This is the end-to-end check for the two reported issues: editing a file opened
by double-click, and dark-mode legibility of the floating UI.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9370
EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "dist", "MD Editor", "MD Editor.exe")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


def find_app_port():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process 'MD Editor' -ErrorAction SilentlyContinue | "
         "ForEach-Object { Get-NetTCPConnection -OwningProcess $_.Id -State Listen "
         "-ErrorAction SilentlyContinue } | "
         "Select-Object -ExpandProperty LocalPort"],
        capture_output=True, text=True, timeout=60)
    ports = [int(p) for p in out.stdout.split() if p.strip().isdigit()]
    return ports[0] if ports else None


def targets():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as fh:
            return json.load(fh)
    except urllib.error.URLError:
        return []


def main():
    os.makedirs(SHOTS, exist_ok=True)

    sample_dir = tempfile.mkdtemp(prefix="md-shot-")
    sample = os.path.join(sample_dir, "catatan.md")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write(
            "# Catatan Proyek\n\n"
            "Dokumen ini dibuka lewat klik dua kali, jadi editor harus langsung aktif.\n\n"
            "## Rencana\n\n"
            "- Susun draft\n- Review bersama tim\n- Publish\n\n"
            "> Preview bisa langsung diedit tanpa pindah panel.\n\n"
            "| Fitur | Status |\n| --- | :---: |\n| Edit preview | Selesai |\n| Tema gelap | Diperbaiki |\n"
        )

    # Exactly how the shell launches the app for a double-clicked file.
    proc = subprocess.Popen([EXE, sample], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(14)

    port = find_app_port()
    if not port:
        print("FAIL: packaged app did not start")
        return 1
    print("packaged app on port", port)

    url = f"http://127.0.0.1:{port}/?path={urllib.parse.quote(os.path.abspath(sample))}"
    profile = tempfile.mkdtemp(prefix="md-editor-shot-")
    edge = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        "--window-size=1440,900",
        f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        import websocket
        deadline = time.time() + 40
        page = None
        while time.time() < deadline and page is None:
            page = next((t for t in targets() if t["type"] == "page"), None)
            time.sleep(0.3)
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=40)
        counter = {"id": 0}

        def send(method, **params):
            counter["id"] += 1
            ws.send(json.dumps({"id": counter["id"], "method": method, "params": params}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == counter["id"]:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg.get("result", {})

        send("Runtime.enable")
        send("Page.enable")

        def ev(expr):
            r = send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            if "exceptionDetails" in r:
                return "<EXC %s>" % json.dumps(r["exceptionDetails"])[:200]
            return r["result"].get("value")

        def shot(name, full=False):
            if full:
                metrics = send("Page.getLayoutMetrics")
                size = metrics.get("cssContentSize") or metrics.get("contentSize")
                send("Emulation.setDeviceMetricsOverride",
                     width=int(size["width"]), height=int(size["height"]),
                     deviceScaleFactor=1, mobile=False)
                time.sleep(0.4)
            data = send("Page.captureScreenshot", format="png")["data"]
            path = os.path.join(SHOTS, name)
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(data))
            if full:
                send("Emulation.clearDeviceMetricsOverride")
            print("  saved", path)
            return path

        deadline = time.time() + 45
        mounted = False
        while time.time() < deadline:
            if ev("!!document.querySelector('#richEditor .ProseMirror')"):
                mounted = True
                break
            time.sleep(0.3)
        print("rich preview active for double-clicked file:", mounted)
        if not mounted:
            return 1
        time.sleep(1.5)

        print("\nlight mode:")
        shot("light-split.png")

        # Switch to dark via the app's own toggle.
        ev("""
        (() => {
          if (document.documentElement.getAttribute('data-theme') !== 'dark') {
            document.getElementById('themeToggle').click();
          }
          return true;
        })()
        """)
        time.sleep(1.2)
        print("  theme:", ev("document.documentElement.getAttribute('data-theme')"))
        shot("dark-split.png")

        # Reveal the floating toolbar by selecting text, and the block handle
        # by placing the caret in a paragraph.
        ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          pm.focus();
          const w = document.createTreeWalker(pm, NodeFilter.SHOW_TEXT);
          let n = null;
          while ((n = w.nextNode())) if (n.nodeValue.includes('langsung')) break;
          if (!n) return 'no text';
          const s = n.nodeValue.indexOf('langsung');
          const r = document.createRange();
          r.setStart(n, s); r.setEnd(n, s + 9);
          const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
          document.dispatchEvent(new Event('selectionchange'));
          return true;
        })()
        """)
        time.sleep(1.2)
        print("  crepe toolbar visible:", ev(
            "!!document.querySelector('.milkdown-toolbar[data-show=\"true\"]')"))
        shot("dark-toolbar.png")

        # Slash menu, the other menu users hit in dark mode.
        ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          pm.focus();
          const sel = getSelection(); sel.removeAllRanges();
          const r = document.createRange(); r.selectNodeContents(pm); r.collapse(false);
          sel.addRange(r);
          document.execCommand('insertText', false, '/');
          return true;
        })()
        """)
        time.sleep(1.2)
        print("  slash menu visible:", ev("!!document.querySelector('.milkdown-slash-menu')"))
        shot("dark-slash-menu.png")

        print("\nfull-page dark view:")
        shot("dark-full.png", full=True)
        return 0
    finally:
        edge.terminate()
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
