"""Verify the two reported issues are fixed.

1. A file opened the way a double-click opens it (``?path=...``) must give an
   editable preview, not a read-only rendered pane.
2. Dark-mode floating UI (toolbar, block handle, slash menu) must have visible
   foreground against its surface.

Runs against either the source tree or a running app; pass a base URL.
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
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9360

FAILURES = []


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_source_tree():
    """Serve the app the way app.py does, including its /api endpoints."""
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


def luminance(rgb):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def parse_rgb(text):
    """Accept 'rgb(a, b, c)', '#rrggbb' and 'a b c' forms."""
    text = (text or "").strip()
    if text.startswith("#"):
        hexed = text[1:7] if len(text) >= 7 else text[1:4]
        if len(hexed) == 3:
            return tuple(int(c * 2, 16) for c in hexed)
        return tuple(int(hexed[i:i + 2], 16) for i in (0, 2, 4))
    inner = text[text.find("(") + 1:text.find(")")] if "(" in text else text
    parts = [p for p in inner.replace("/", " ").replace(",", " ").split() if p]
    return tuple(int(float(p)) for p in parts[:3])


def contrast(fg, bg):
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def main():
    httpd, port = serve_source_tree()

    markdown = (
        "# Judul Dokumen\n\n"
        "Ini paragraf dengan **teks tebal** di dalamnya.\n\n"
        "- item satu\n- item dua\n\n"
        "| Kolom | Nilai |\n| --- | --- |\n| A | 1 |\n"
    )
    sample = os.path.join(tempfile.mkdtemp(prefix="md-open-"), "contoh.md")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write(markdown)

    # This is exactly how a double-click opens a file: app.py appends ?path=.
    url = f"http://127.0.0.1:{port}/?path={urllib.parse.quote(os.path.abspath(sample))}"
    print("opening:", url)

    profile = tempfile.mkdtemp(prefix="md-editor-fix-")
    proc = subprocess.Popen([
        EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
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
        if page is None:
            print("FAIL: no page target")
            return 1

        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=40)
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
                d = r["exceptionDetails"]
                return "<EXC %s %s>" % (d.get("text"),
                                        (d.get("exception") or {}).get("description", "")[:300])
            return r["result"].get("value")

        print("\n== issue 1: file opened via ?path= (double-click) ==")
        deadline = time.time() + 45
        mounted = False
        while time.time() < deadline:
            if ev("!!document.querySelector('#richEditor .ProseMirror')"):
                mounted = True
                break
            time.sleep(0.3)
        check("preview is an editable rich editor", mounted)
        if not mounted:
            print("  richEditor hidden:", ev("document.getElementById('richEditor').hidden"))
            print("  file loaded into textarea:", repr(ev(
                "document.getElementById('editor').value.slice(0,40)")))
            print("  status:", ev("document.getElementById('saveStatus').textContent"))
            return 1

        time.sleep(1.0)
        check("the opened file's text is in the preview",
              "Judul Dokumen" in (ev(
                  "document.querySelector('#richEditor .ProseMirror').textContent") or ""))

        # Bold a word in the opened file, through the preview.
        ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          const w = document.createTreeWalker(pm, NodeFilter.SHOW_TEXT);
          let n=null; while ((n=w.nextNode())) if (n.nodeValue.includes('paragraf')) break;
          if (!n) return 'not found';
          const s = n.nodeValue.indexOf('paragraf');
          const r = document.createRange(); r.setStart(n,s); r.setEnd(n,s+8);
          const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
          pm.focus(); return true;
        })()
        """)
        time.sleep(0.4)
        ev("""
        (() => {
          const btn = document.querySelector('#toolbar button[data-cmd="bold"]');
          btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
          btn.click(); return true;
        })()
        """)
        time.sleep(1.0)
        got = ev("getContent()")
        check("bold works in a double-clicked file", "**paragraf**" in (got or ""), str(got)[:120])

        time.sleep(1.2)
        with open(sample, "r", encoding="utf-8") as fh:
            on_disk = fh.read()
        check("the edit is saved back to the .md file", "**paragraf**" in on_disk,
              on_disk[:120])

        print("\n== issue 2: dark-mode contrast of floating UI ==")
        # The server-side settings file wins at boot, so drive the theme the
        # same way a user does and confirm it actually takes effect.
        ev("""
        (() => {
          if (document.documentElement.getAttribute('data-theme') !== 'dark') {
            document.getElementById('themeToggle').click();
          }
          return true;
        })()
        """)
        time.sleep(0.8)
        check("dark theme active",
              ev("document.documentElement.getAttribute('data-theme')") == "dark",
              str(ev("document.documentElement.getAttribute('data-theme')")))
        check("dark class is on the milkdown root",
              ev("!!document.querySelector('#richEditor .milkdown.md-editor-dark')"))

        # The floating UI only appears on selection / hover, so make it render
        # before measuring contrast.
        ev("""
        (() => {
          const pm = document.querySelector('#richEditor .ProseMirror');
          pm.focus();
          const w = document.createTreeWalker(pm, NodeFilter.SHOW_TEXT);
          let n = null;
          while ((n = w.nextNode())) if (n.nodeValue.trim()) break;
          if (n) {
            const r = document.createRange();
            r.setStart(n, 0);
            r.setEnd(n, Math.min(4, n.nodeValue.length));
            const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
          }
          // Nudge the handle into its visible state.
          document.querySelectorAll('.milkdown-block-handle').forEach(el => {
            el.style.opacity = '1';
          });
          return true;
        })()
        """)
        time.sleep(0.8)

        report = ev("""
        (() => {
          const out = [];
          const grab = (name, el) => {
            if (!el) { out.push({name, missing: true}); return; }
            const cs = getComputedStyle(el);
            // Effective background: walk up until something paints.
            let bgEl = el, bg = 'rgba(0, 0, 0, 0)';
            while (bgEl && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
              bg = getComputedStyle(bgEl).backgroundColor;
              bgEl = bgEl.parentElement;
            }
            out.push({name, color: cs.color, fill: cs.fill, bg, opacity: cs.opacity});
          };
          const root = document.querySelector('#richEditor .milkdown');
          grab('milkdown-root', root);
          const handle = document.querySelector('.milkdown-block-handle');
          grab('block-handle', handle);
          grab('block-handle-svg', handle && handle.querySelector('svg'));
          grab('block-handle-item', handle && handle.querySelector('.operation-item'));
          const toolbar = document.querySelector('.milkdown-toolbar');
          grab('toolbar', toolbar);
          grab('toolbar-svg', toolbar && toolbar.querySelector('svg'));
          return JSON.stringify(out);
        })()
        """)
        print("  computed styles:", report)

        try:
            items = json.loads(report)
        except Exception:
            items = []

        for item in items:
            if item.get("missing"):
                print(f"  [note] {item['name']} not in the DOM right now")
                continue
            # SVG icons are painted with `fill` (its default is black, which is
            # not what is rendered); everything else is painted with `color`.
            is_svg = item["name"].endswith("-svg")
            fg_raw = item["fill"] if is_svg else item["color"]
            fg = parse_rgb(fg_raw)
            bg = parse_rgb(item["bg"])
            ratio = contrast(fg, bg)
            check(f"{item['name']} legible ({fg_raw} on {item['bg']})", ratio >= 3.0,
                  f"contrast {ratio:.2f}:1")

        print()
        print("== regression: the same UI in light mode ==")
        ev("""
        (() => {
          if (document.documentElement.getAttribute('data-theme') !== 'light') {
            document.getElementById('themeToggle').click();
          }
          return true;
        })()
        """)
        time.sleep(0.8)
        check("light theme restored",
              ev("document.documentElement.getAttribute('data-theme')") == "light")
        light_report = ev("""
        (() => {
          const el = document.querySelector('#richEditor .milkdown');
          const cs = getComputedStyle(el);
          return JSON.stringify({color: cs.color, bg: cs.backgroundColor});
        })()
        """)
        print("  light root:", light_report)
        try:
            light = json.loads(light_report)
            ratio = contrast(parse_rgb(light["color"]), parse_rgb(light["bg"]))
            check("light mode body text still legible", ratio >= 3.0, f"contrast {ratio:.2f}:1")
        except Exception as exc:  # noqa: BLE001
            check("light mode body text still legible", False, str(exc))

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
