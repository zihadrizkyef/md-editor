"""Screenplay for the 30 second demo: what the recorder does, and when."""
import time

MAIN_DOC = """# Catatan Rilis 2.0

**MD Editor** adalah editor Markdown desktop untuk Windows: ringan, offline,
dan hasil preview-nya bisa langsung diketik.

## Yang baru

- Tab dokumen tanpa batas, tiap tab punya riwayat sendiri
- Preview WYSIWYG: klik dan ketik langsung di hasil render
- Tema terang dan gelap
- Gambar bisa di-paste atau di-drag ke dalam dokumen
- Autosave plus deteksi perubahan file dari luar

> Tulis di kiri, lihat hasilnya di kanan. Atau sebaliknya.

| Fitur | Status |
| --- | :---: |
| Preview live | Siap |
| Edit di preview | Siap |
| Export HTML | Siap |

```js
const doc = await mdEditor.open("catatan.md");
doc.preview.edit();
```

- [x] Editor tiga tampilan
- [x] Status simpan otomatis
- [ ] Sinkronisasi cloud
"""

SECOND_DOC = """# Roadmap Q4

1. Pencarian di seluruh tab
2. Sinkronisasi pengaturan antar perangkat
3. Ekspor ke PDF

Catatan: prioritas bisa berubah setelah review bersama tim.
"""

JS_HELPERS = r"""
window.__demo = {
  setView: v => document.querySelector(`[data-view="${v}"]`).click(),
  setTheme: t => { if ((document.documentElement.getAttribute('data-theme') || 'light') !== t)
                     document.getElementById('themeToggle').click(); },
  scrollPreview: (to, ms) => {
    const el = document.getElementById('previewPane');
    const from = el.scrollTop, t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      el.scrollTop = from + (to - from) * e;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },
  cursorInit: () => {
    if (window.__cur) return true;
    const arrow = document.createElement('div');
    arrow.id = '__cursor';
    arrow.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24">' +
      '<path d="M3.5 1.8 L3.5 19.4 L8.6 15.1 L12 21.6 L15.1 20.2 L11.7 13.9 L18.6 13.1 Z" ' +
      'fill="#101114" stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    arrow.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;' +
      'filter:drop-shadow(0 2px 4px rgba(0,0,0,.4));will-change:transform';
    document.body.appendChild(arrow);
    const ring = document.createElement('div');
    ring.id = '__cursorRing';
    ring.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483646;pointer-events:none;' +
      'width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;' +
      'border:2px solid rgba(79,70,229,.85);opacity:0;transform:scale(.2)';
    document.body.appendChild(ring);
    window.__cur = { arrow, ring, x: innerWidth * 0.5, y: innerHeight * 0.5 };
    arrow.style.transform = `translate(${innerWidth * 0.5}px, ${innerHeight * 0.5}px)`;
    return true;
  },
  cursorTo: (x, y, ms) => {
    const c = window.__cur;
    if (!c) return false;
    const x0 = c.x, y0 = c.y, t0 = performance.now();
    if (!ms) { c.arrow.style.transform = `translate(${x}px, ${y}px)`; c.x = x; c.y = y; return true; }
    const step = now => {
      const k = Math.min(1, (now - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const cx = x0 + (x - x0) * e, cy = y0 + (y - y0) * e;
      c.arrow.style.transform = `translate(${cx}px, ${cy}px)`;
      if (k < 1) requestAnimationFrame(step); else { c.x = x; c.y = y; }
    };
    c.x = x; c.y = y;
    requestAnimationFrame(step);
    return true;
  },
  cursorPress: () => {
    const c = window.__cur;
    if (!c) return false;
    const ring = c.ring;
    ring.style.left = c.x + 'px';
    ring.style.top = c.y + 'px';
    ring.style.transition = 'none';
    ring.style.opacity = '1';
    ring.style.transform = 'scale(.25)';
    requestAnimationFrame(() => {
      ring.style.transition = 'transform .42s ease-out, opacity .42s ease-out';
      ring.style.transform = 'scale(1.15)';
      ring.style.opacity = '0';
    });
    return true;
  },
  elCenterNth: (sel, i) => {
    const el = document.querySelectorAll(sel)[i];
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  },
  elCenter: sel => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  },
  cleanSlash: () => {
    const md = getContent();
    const next = md.replace(/^[ \t]*(>[ \t]*)?\/[ \t]*\r?\n/gm, '');
    if (next === md) return false;
    setContent(next);
    return true;
  },

  openFile: (name, text) => {
    const dt = new DataTransfer();
    dt.items.add(new File([text], name, { type: 'text/markdown' }));
    const input = document.getElementById('fileInput');
    input.files = dt.files;
    input.dispatchEvent(new Event('change'));
  },
  focusEnd: () => {
    const e = document.getElementById('editor');
    e.focus();
    e.setSelectionRange(e.value.length, e.value.length);    e.scrollTop = e.scrollHeight;
  },
  selectLine: (needle) => {
    const e = document.getElementById('editor');
    const i = e.value.indexOf(needle);
    if (i < 0) return false;
    e.focus();
    e.setSelectionRange(i, i + needle.length);
    return true;
  },
  click: sel => { const el = document.querySelector(sel); if (el) el.click(); return Boolean(el); },
  tabClick: i => {
    const el = document.querySelectorAll('.tab-label')[i];
    if (!el) return false;
    el.click();
    document.getElementById('tabbar').scrollLeft = 0;
    return true;
  },
  richTarget: () => {
    const host = document.getElementById('richEditor');
    const el = host.querySelector('.ProseMirror > p');
    if (!el) return null;
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    return true;
  },
  richTargetRect: () => {
    const host = document.getElementById('richEditor');
    const el = host.querySelector('.ProseMirror > p');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.right - 20), y: Math.round(r.top + r.height / 2) };
  },
  lastRichRect: () => {
    const host = document.getElementById('richEditor');
    const blocks = [...host.querySelectorAll('.ProseMirror p, .ProseMirror h2, .ProseMirror li')];
    if (!blocks.length) return null;
    const el = blocks[blocks.length - 1];
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.right - 12), y: Math.round(r.top + r.height / 2) };
  },
  focusRichEnd: () => {
    const host = document.getElementById('richEditor');
    const blocks = host.querySelectorAll('p, h2, li');
    const node = blocks[blocks.length - 1];
    const range = document.createRange();
    range.selectNodeContents(node);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const pm = host.querySelector('.ProseMirror');
    if (pm) pm.focus();
    return Boolean(node);
  },
};
"""


def type_into_editor(rec, text, cps=26):
    rec.click_el("#editor", 0.45)
    rec.page.js("__demo.focusEnd()")
    thread = rec.type_async(text, cps=cps)
    rec.hold(len(text) / cps + 0.35)
    thread.join()


def click_tab(rec, index):
    point = rec.page.js(f"__demo.elCenterNth('.tab-label', {index})")
    if point:
        rec.click_at(point["x"], point["y"], 0.45)


def perform(rec, page):
    """30 second timeline, paced with wall-clock fences."""
    rec.t0 = time.monotonic()
    page.js("__demo.scrollPreview(0, 2000)")
    rec.at(2.2)
    rec.click_el('[data-view="split"]', 0.5)

    rec.at(3.2)
    type_into_editor(rec, "> Preview live: ketukan langsung terlihat." + chr(10), 38)

    rec.at(6.2)
    page.js("__demo.selectLine('ringan, offline')")
    rec.hold(0.3)
    rec.click_el('[data-cmd="bold"]', 0.5)

    rec.at(7.4)
    rec.click_el('[data-view="preview"]', 0.5)

    rec.at(8.3)
    page.js("__demo.richTarget()")
    rec.hold(0.7)
    coords = page.js("__demo.richTargetRect()")
    if coords:
        rec.click_at(coords["x"], coords["y"], 0.55)
    rec.hold(0.2)
    page.key("End", code="End", key_code=35)
    thread = rec.type_async(" Bisa diketik di sini.", cps=38)
    rec.hold(1.2)
    thread.join()

    rec.at(12.0)
    page.key("Enter", code="Enter", key_code=13, text=chr(13))
    rec.hold(0.25)
    page.insert("/")
    rec.hold(1.4)
    page.key("Escape", code="Escape", key_code=27)
    rec.hold(0.3)
    page.js("__demo.cleanSlash()")
    rec.hold(0.3)

    rec.at(14.4)
    rec.click_el("#themeToggle", 0.55)
    rec.hold(0.6)

    rec.at(16.2)
    page.js("__demo.openFile('roadmap.md', " + repr(SECOND_DOC) + ")")
    rec.hold(1.0)

    rec.at(17.4)
    click_tab(rec, 0)
    rec.hold(0.4)

    rec.at(18.8)
    rec.click_el('[data-view="split"]', 0.45)
    rec.hold(0.2)

    rec.at(20.0)
    rec.click_el("#editor", 0.4)
    rec.page.js("__demo.focusEnd()")
    thread = rec.type_async(chr(10) + "- Riwayat versi" + chr(10), cps=38)
    rec.hold(1.2)
    thread.join()

    rec.at(22.6)
    click_tab(rec, 1)
    rec.hold(0.5)

    rec.at(24.4)
    rec.click_el('[data-view="preview"]', 0.45)
    rec.hold(0.3)

    rec.at(25.8)
    rec.click_el("#themeToggle", 0.55)
    rec.hold(0.4)

    rec.at(27.5)
    page.js("__demo.scrollPreview(0, 900)")
    rec.at(29.4)
    rec.frame()



def setup(page):
    page.js(JS_HELPERS)
    page.js("__demo.cursorInit()")
    page.js("const st = document.createElement('style');"
            " st.textContent = '.milkdown-drop-indicator{display:none !important}';"
            " document.head.appendChild(st);")
    page.js("setContent(" + repr(MAIN_DOC) + ")")
    page.js("const t = activeTab(); t.content = " + repr(MAIN_DOC) +
            "; t.filename = 'Catatan Rilis.md'; filenameInput.value = t.filename;"
            "currentFilePath = null; renderTabs(); render();")
    page.js("__demo.setTheme('light')")
    page.js("document.querySelectorAll('#richEditor .ProseMirror').forEach(pm => {"
            " pm.setAttribute('spellcheck', 'false'); pm.spellcheck = false; })")

