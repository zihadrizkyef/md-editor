"""Verify the *packaged* MD Editor.exe serves a working rich preview.

Connects to the local server the running exe opened and drives the page in a
headless browser, proving the bundled assets (rich-editor.js/css) are wired up
inside the PyInstaller build rather than only in the source tree.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9350


def find_app_port():
    """Discover the port the running MD Editor.exe is listening on."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process 'MD Editor' -ErrorAction SilentlyContinue | "
             "ForEach-Object { Get-NetTCPConnection -OwningProcess $_.Id -State Listen "
             "-ErrorAction SilentlyContinue } | "
             "Select-Object -ExpandProperty LocalPort"],
            capture_output=True, text=True, timeout=60)
        ports = [int(p) for p in out.stdout.split() if p.strip().isdigit()]
        return ports[0] if ports else None
    except Exception:
        return None


def targets():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as fh:
            return json.load(fh)
    except urllib.error.URLError:
        return []


def main():
    port = find_app_port()
    if not port:
        print("FAIL: no listening port found for the packaged app")
        return 1
    app_url = f"http://127.0.0.1:{port}/"
    print("packaged app serving on:", app_url)

    # The packaged server must expose the new bundle.
    for asset in ("rich-editor.js", "rich-editor.css", "script.js", "style.css"):
        try:
            with urllib.request.urlopen(app_url + asset, timeout=10) as fh:
                size = len(fh.read())
            print(f"  [ok] {asset} served ({size} bytes)")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {asset} not served: {exc}")
            return 1

    profile = tempfile.mkdtemp(prefix="md-editor-exe-")
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", app_url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        import websocket
        deadline = time.time() + 40
        page = None
        while time.time() < deadline and page is None:
            page = next((t for t in targets() if t["type"] == "page"), None)
            time.sleep(0.3)
        if page is None:
            print("FAIL: no page target")
            return 1

        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        counter = {"id": 0}

        def send(method, **params):
            counter["id"] += 1
            ws.send(json.dumps({"id": counter["id"], "method": method, "params": params}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == counter["id"]:
                    return msg.get("result", {})

        send("Runtime.enable")

        def ev(expr):
            r = send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            if "exceptionDetails" in r:
                return "<EXC %s>" % json.dumps(r["exceptionDetails"])[:200]
            return r["result"].get("value")

        deadline = time.time() + 45
        mounted = False
        while time.time() < deadline:
            if ev("!!document.querySelector('#richEditor .ProseMirror')"):
                mounted = True
                break
            time.sleep(0.3)

        print("rich editor mounted in packaged app:", mounted)
        if not mounted:
            return 1
        time.sleep(1.0)

        ev("setContent('Halo dunia ini teks biasa.\\n')")
        time.sleep(0.9)
        ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          const w = document.createTreeWalker(pm, NodeFilter.SHOW_TEXT);
          let n=null; while ((n=w.nextNode())) if (n.nodeValue.includes('dunia')) break;
          const s = n.nodeValue.indexOf('dunia');
          const r = document.createRange(); r.setStart(n,s); r.setEnd(n,s+5);
          const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
          pm.focus(); return true;
        })()
        """)
        time.sleep(0.4)
        ev("""
        (() => {
          const btn = document.querySelector('#toolbar button[data-cmd="bold"]');
          btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
          btn.click();
          return true;
        })()
        """)
        time.sleep(1.0)
        result = ev("getContent()")
        print("markdown after bold:", json.dumps(result))

        ok = isinstance(result, str) and "**dunia**" in result
        print("PACKAGED BOLD:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
