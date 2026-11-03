"""Screenplay for the 30 second demo: what the recorder does, and when."""

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
    const el = host.querySelector('.ProseMirror blockquote p');
    if (!el) return null;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    return true;
  },
  richTargetRect: () => {
    const host = document.getElementById('richEditor');
    const el = host.querySelector('.ProseMirror blockquote p');
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
    rec.page.js("__demo.focusEnd()")
    thread = rec.type_async(text, cps=cps)
    rec.hold(len(text) / cps + 0.35)
    thread.join()


def perform(rec, page):
    """Absolute 30 second timeline."""
    page.js("__demo.scrollPreview(0, 2000)")
    rec.at(2.4)
    page.js("__demo.setView('split')")
    rec.hold(0.9)

    type_into_editor(rec, "> Preview live: setiap ketukan langsung terlihat.\n", 26)
    rec.hold(0.5)

    page.js("__demo.selectLine('ringan, offline')")
    rec.hold(0.4)
    page.js("__demo.click('[data-cmd=\"bold\"]')")
    rec.hold(0.9)

    page.js("__demo.scrollPreview(520, 900)")
    rec.hold(1.2)

    page.js("__demo.setView('preview')")
    rec.hold(1.0)

    page.js("__demo.richTarget()")
    rec.hold(0.9)
    coords = page.js("__demo.richTargetRect()")
    if coords:
        page.click(coords["x"], coords["y"])
    rec.hold(0.6)
    page.key("End", code="End", key_code=35)
    thread = rec.type_async(" Bisa langsung diketik di sini.", cps=24)
    rec.hold(1.7)
    thread.join()
    rec.hold(0.3)

    page.key("Enter", code="Enter", key_code=13, text="\r")
    rec.hold(0.3)
    page.insert("/")
    rec.hold(1.6)
    page.key("Escape", code="Escape", key_code=27)
    rec.hold(0.4)
    page.js("__demo.cleanSlash()")
    rec.hold(0.4)

    page.js("__demo.setTheme('dark')")
    rec.hold(1.5)

    page.js("__demo.openFile('roadmap.md', " + repr(SECOND_DOC) + ")")
    rec.hold(1.6)

    page.js("__demo.tabClick(0)")
    rec.hold(1.1)
    page.js("__demo.tabClick(1)")
    rec.hold(1.0)

    page.js("__demo.setView('split')")
    rec.hold(0.9)
    rec.page.js("__demo.focusEnd()")
    thread = rec.type_async("\n- Tambahkan riwayat versi\n", cps=26)
    rec.hold(1.4)
    thread.join()
    rec.hold(0.4)

    page.js("__demo.tabClick(0)")
    rec.hold(0.3)
    page.js("__demo.setView('preview')")
    rec.hold(1.0)
    page.js("__demo.scrollPreview(0, 1200)")
    rec.hold(1.4)

    page.js("__demo.setTheme('light')")
    rec.hold(1.3)

    rec.at(27.0)
    page.js("__demo.scrollPreview(300, 2400)")
    rec.at(29.7)
    rec.frame()


def setup(page):
    page.js(JS_HELPERS)
    page.js("setContent(" + repr(MAIN_DOC) + ")")
    page.js("const t = activeTab(); t.content = " + repr(MAIN_DOC) +
            "; t.filename = 'Catatan Rilis.md'; filenameInput.value = t.filename;"
            "currentFilePath = null; renderTabs(); render();")
    page.js("__demo.setTheme('light')")
    page.js("document.querySelectorAll('#richEditor .ProseMirror').forEach(pm => {"
            " pm.setAttribute('spellcheck', 'false'); pm.spellcheck = false; })")

