"""Record a 30 second demo of the app through Chrome DevTools Protocol.

    python demo/record.py          # capture frames, then encode demo.mp4/.gif
    python demo/record.py --smoke  # capture one frame per scene and stop
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp
import server
import scenes

CHROME = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo", "build")
DEBUG_PORT = 9411
WIDTH, HEIGHT, SCALE = 1280, 800, 1.5


class Recorder:
    def __init__(self, page, outdir):
        self.page = page
        self.outdir = outdir
        self.frames = []
        self.t0 = time.monotonic()
        # Real pointer position, tracked so travel looks continuous.
        self.px, self.py = WIDTH // 2, HEIGHT // 2
        self.drift = 0.0

    def move_to(self, x, y, seconds=0.5, steps=9):
        """Glide a visible cursor and the real pointer to (x, y)."""
        x0, y0 = self.px, self.py
        self.px, self.py = x, y
        self.page.js(f"__demo.cursorTo({x}, {y}, {int(seconds * 1000)})")

        def walk():
            for i in range(1, steps + 1):
                e = 1 - (1 - i / steps) ** 3
                self.page.call("Input.dispatchMouseEvent", type="mouseMoved",
                               x=round(x0 + (x - x0) * e),
                               y=round(y0 + (y - y0) * e))
                time.sleep(seconds / steps)

        walker = threading.Thread(target=walk, daemon=True)
        walker.start()
        self.hold(seconds + 0.05)
        walker.join()

    def click_at(self, x, y, seconds=0.5):
        self.move_to(x, y, seconds)
        self.page.js("__demo.cursorPress()")
        self.page.click(x, y)
        self.hold(0.4)

    def click_el(self, selector, seconds=0.5):
        point = self.page.js(f"__demo.elCenter({json.dumps(selector)})")
        if not point:
            return False
        self.click_at(point["x"], point["y"], seconds)
        return True

    def frame(self):
        path = os.path.join(self.outdir, f"f{len(self.frames):04d}.jpg")
        with open(path, "wb") as fh:
            fh.write(self.page.shot())
        self.frames.append((time.monotonic() - self.t0, path))

    def hold(self, seconds, fps=0):
        """Keep grabbing frames for `seconds`; fps=0 paces on capture latency."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.frame()
            if fps:
                time.sleep(max(0.0, min(1.0 / fps, end - time.monotonic())))

    def at(self, t):
        """Hold frames until the timeline reaches t seconds."""
        now = time.monotonic() - self.t0
        self.drift += now - t
        if os.environ.get("DEMO_DEBUG"):
            print(f"  fence {t:5.1f}  actual {now:5.2f}  drift {now - t:+.2f}")
        if t > now:
            self.hold(t - now)

    def type_text(self, text, cps=26):
        delay = 1.0 / cps
        for ch in text:
            self.page.insert(ch)
            time.sleep(delay)

    def type_async(self, text, cps=26):
        thread = threading.Thread(target=self.type_text, args=(text, cps),
                                  daemon=True)
        thread.start()
        return thread

    def write_manifest(self):
        with open(os.path.join(self.outdir, "frames.json"), "w") as fh:
            json.dump(self.frames, fh)


def boot(headless=True):
    httpd = server.start()
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/index.html"
    profile = tempfile.mkdtemp(prefix="md-demo-")
    args = [CHROME, "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}", f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-allow-origins=*", "--hide-scrollbars",
            f"--window-size={WIDTH},{HEIGHT}"]
    if headless:
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(args + [url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page = cdp.Tab(cdp.pick_page(DEBUG_PORT))
    page.call("Page.enable")
    page.call("Runtime.enable")
    page.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT,
              deviceScaleFactor=SCALE, mobile=False)
    page.call("Page.navigate", url=url)
    deadline = time.time() + 60
    while time.time() < deadline:
        if page.js("Boolean(document.getElementById('editor'))"):
            break
        time.sleep(0.4)
    time.sleep(3.0)  # let the Milkdown bundle mount
    return page, proc, httpd, profile


def encode(outdir, frames):
    total = frames[-1][0] if frames else 1.0
    concat = os.path.join(outdir, "frames.txt")
    with open(concat, "w") as fh:
        for i, (ts, path) in enumerate(frames):
            nxt = frames[i + 1][0] if i + 1 < len(frames) else total + 0.1
            fh.write(f"file '{path.replace(chr(92), '/')}'\n")
            fh.write(f"duration {max(0.01, nxt - ts):.3f}\n")
    mp4 = os.path.join(ROOT, "docs", "demo.mp4")
    gif = os.path.join(ROOT, "docs", "demo.gif")
    common = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", concat, "-t", "30"]
    subprocess.run(common + ["-vf", "fps=30,scale=1280:-2:flags=lanczos,"
                             "format=yuv420p", "-c:v", "libx264", "-crf", "20",
                             "-preset", "slow", "-movflags", "+faststart", mp4],
                   check=True)
    subprocess.run(common + ["-vf", "fps=12,scale=860:-1:flags=lanczos,split[a][b];"
                             "[a]palettegen=max_colors=128:stats_mode=diff[p];"
                             "[b][p]paletteuse=dither=bayer:bayer_scale=4", gif],
                   check=True)
    print("wrote", mp4, os.path.getsize(mp4) // 1024, "KB")
    print("wrote", gif, os.path.getsize(gif) // 1024, "KB")


def mp4_path():
    return os.path.join(ROOT, "docs", "demo.mp4")


def main():
    smoke = "--smoke" in sys.argv
    outdir = os.path.join(OUT, "frames")
    os.makedirs(os.path.dirname(mp4_path()), exist_ok=True)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    page, proc, httpd, profile = boot(headless=True)
    rec = Recorder(page, outdir)
    try:
        scenes.setup(page)
        time.sleep(1.5)
        if smoke:
            rec.frame()
            rec.write_manifest()
            print("smoke frame written to", outdir)
            return
        scenes.perform(rec, page)
        rec.write_manifest()
        print(f"captured {len(rec.frames)} frames, "
              f"{rec.frames[-1][0]:.1f}s")
        encode(outdir, rec.frames)
    finally:
        proc.terminate()
        httpd.shutdown()
        try:
            page.ws.close()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()

