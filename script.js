/* ===================== Markdown Parser ===================== */
/* Small self-contained markdown -> HTML converter (no external deps). */

let currentFileDir = null; // directory of the currently open file, used to resolve relative image paths
let footnoteOrder = [];
let footnoteDefs = new Map();

function resetFootnotes() {
  footnoteOrder = [];
  footnoteDefs = new Map();
}

function dirnameOf(p) {
  if (!p) return null;
  const idx = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return idx >= 0 ? p.slice(0, idx) : null;
}

function resolveImageSrc(src) {
  if (/^(https?:|data:|file:|\/api\/)/i.test(src)) return src;
  let fullPath;
  if (/^[a-zA-Z]:[\\/]/.test(src) || src.startsWith("/") || src.startsWith("\\")) {
    fullPath = src;
  } else if (currentFileDir) {
    const sep = currentFileDir.includes("\\") ? "\\" : "/";
    const cleanRel = src.replace(/[\\/]/g, sep);
    fullPath = currentFileDir.replace(/[\\/]+$/, "") + sep + cleanRel;
  } else {
    return src; // no open file context to resolve a relative path against
  }
  return `/api/image?path=${encodeURIComponent(fullPath)}`;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* Positions keep the preview editable: an HTML tokenizer turns the rendered
   document back into (block, offset) coordinates in the Markdown source, so a
   caret in the preview maps to a caret in the textarea and back. */
let currentSrc = "";
let blockCtx = null;
let inlineCtx = null;

function srcIndexOf(text, from) {
  if (!blockCtx) return null;
  const at = currentSrc.indexOf(text, from);
  return at === -1 ? null : at;
}

function splitRowCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
}

function parseInline(text, ctx) {
  const previous = inlineCtx;
  inlineCtx = ctx || null;

  try {
    // Protect inline code first
    const codeSpans = [];
    text = text.replace(/`([^`]+?)`/g, (m, code) => {
      codeSpans.push(escapeHtml(code));
      return `CODE${codeSpans.length - 1}`;
    });

    text = escapeHtml(text);

    // Images ![alt](src)
    text = text.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
      (m, alt, src, title) => `<img src="${resolveImageSrc(src)}" alt="${alt}"${title ? ` title="${title}"` : ""}>`);

    // Footnote reference [^id]
    text = text.replace(/\[\^([^\]\s]+)\]/g, (m, id) => {
      if (!footnoteDefs.has(id)) return m; // not a defined footnote, leave as-is
      if (!footnoteOrder.includes(id)) footnoteOrder.push(id);
      const num = footnoteOrder.indexOf(id) + 1;
      return `<sup class="footnote-ref"><a href="#fn-${escapeHtml(id)}" id="fnref-${escapeHtml(id)}" data-footnote-ref="${escapeHtml(id)}">[${num}]</a></sup>`;
    });

    // Links [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
      (m, label, url, title) => {
        let mid = 0;
        if (inlineCtx) {
          // Point the rendered anchor text at the label inside the markdown link.
          const at = srcIndexOf(m, inlineCtx.from);
          inlineCtx.from = at === null ? inlineCtx.to : at + m.length;
          if (at !== null) mid = at + 1;
        }
        return `<a href="${url}" target="_blank" rel="noopener noreferrer"${title ? ` title="${title}"` : ""}` +
          (mid ? ` data-md="${mid}" data-mdl="${label.length}"` : "") + `>${label}</a>`;
      });

    // Bold+italic ***text*** or ___text___
    text = text.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
    // Bold **text** or __text__
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    // Italic *text* or _text_
    text = text.replace(/(?<!\*)\*([^*\s][^*]*?)\*(?!\*)/g, "<em>$1</em>");
    text = text.replace(/(?<!_)_([^_\s][^_]*?)_(?!_)/g, "<em>$1</em>");
    // Strikethrough
    text = text.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    // Restore code spans
    text = text.replace(/CODE(\d+)/g, (m, i) => `<code>${codeSpans[i]}</code>`);

    return text;
  } finally {
    inlineCtx = previous;
  }
}

function parseMarkdown(src, isRoot = true) {
  currentSrc = src.replace(/\r\n?/g, "\n");

  if (!src || !src.trim()) {
    return `<p class="empty-hint">Belum ada konten. Mulai ketik di editor untuk melihat pratinjau di sini.</p>`;
  }

  if (isRoot) resetFootnotes();

  let lines = currentSrc.split("\n");
  let lineStarts = [];

  // Pre-scan footnote definitions: [^id]: definition text (possibly multi-line, indented continuation)
  if (isRoot) {
    const keptLines = [];
    const keptStarts = [];
    let offset = 0;
    for (let idx = 0; idx < lines.length; idx++) {
      const start = offset;
      offset += lines[idx].length + 1;
      const defMatch = lines[idx].match(/^\[\^([^\]\s]+)\]:\s?(.*)$/);
      if (defMatch) {
        const bodyLines = [defMatch[2]];
        let j = idx + 1;
        while (j < lines.length && /^(\s{2,}|\t)\S/.test(lines[j])) {
          bodyLines.push(lines[j].trim());
          j++;
        }
        footnoteDefs.set(defMatch[1], {
          text: bodyLines.join(" ").trim(),
          pos: start + lines[idx].indexOf(defMatch[2]),
        });
        idx = j - 1;
        continue;
      }
      keptLines.push(lines[idx]);
      keptStarts.push(start);
    }
    lines = keptLines;
    lineStarts = keptStarts;
  } else {
    let offset = 0;
    for (let idx = 0; idx < lines.length; idx++) {
      lineStarts.push(offset);
      offset += lines[idx].length + 1;
    }
  }

  const lineStart = (idx) => idx < lineStarts.length ? lineStarts[idx] : currentSrc.length;

  const html = [];
  let i = 0;

  let inCodeBlock = false;
  let codeBuffer = [];
  let codeLang = "";
  let codeStart = 0;

  let listStack = []; // { type: 'ul'|'ol', indent, depth }
  let inTable = false;
  let tableRows = [];
  let paragraphBuffer = [];
  let paragraphStart = null;

  function flushParagraph() {
    if (paragraphBuffer.length) {
      const from = paragraphStart ?? 0;
      const to = from + paragraphBuffer.join(" ").length;
      html.push(`<p data-bs="${from}" data-be="${to}">${parseInline(paragraphBuffer.join(" "), { from, to })}</p>`);
      paragraphBuffer = [];
      paragraphStart = null;
    }
  }

  const listMeta = () => listStack.length ? ` data-bs="${listStack[listStack.length - 1].start}"` : "";

  function closeLists(toIndent = -1) {
    while (listStack.length && listStack[listStack.length - 1].indent > toIndent) {
      const open = listStack.pop();
      html.push(open.type === "ul" ? "</ul>" : "</ol>");
    }
  }

  function ensureList(type, indent, at) {
    // Close any deeper-nested lists first.
    closeLists(indent);
    const top = listStack[listStack.length - 1];
    if (!top || top.indent < indent) {
      html.push(type === "ul" ? `<ul data-bs="${at}">` : `<ol data-bs="${at}">`);
      listStack.push({ type, indent, start: at });
    } else if (top.indent === indent && top.type !== type) {
      html.push(top.type === "ul" ? "</ul>" : "</ol>");
      listStack.pop();
      html.push(type === "ul" ? `<ul data-bs="${at}">` : `<ol data-bs="${at}">`);
      listStack.push({ type, indent, start: at });
    }
    // else: same indent + same type -> reuse the open list.
  }

  // A line that starts a new block (so it can't be a lazy-continuation of the
  // previous list item / paragraph line above it).
  function startsNewBlock(l) {
    return /^\s*$/.test(l) ||
      /^(\s*)```/.test(l) ||
      /^\s*\|.*\|\s*$/.test(l) ||
      /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l) ||
      /^#{1,6}\s+/.test(l) ||
      /^\s*>\s?/.test(l) ||
      /^(\s*)[-*+]\s+/.test(l) ||
      /^(\s*)\d+\.\s+/.test(l);
  }

  // Collect subsequent lazy-continuation lines (plain wrapped text with no
  // block marker of its own) starting at index `from`, so they can be joined
  // onto the same list item / paragraph before running parseInline once.
  function collectContinuation(from) {
    const parts = [];
    let j = from;
    while (j < lines.length && !startsNewBlock(lines[j])) {
      parts.push(lines[j].trim());
      j++;
    }
    return { text: parts.join(" "), next: j };
  }

  function flushTable() {
    if (!tableRows.length) return;
    const header = tableRows[0];
    const alignRow = tableRows[1];
    const bodyRows = tableRows.slice(2);
    const aligns = alignRow ? alignRow.cells.map(c => {
      const t = c.text.trim();
      if (/^:-+:$/.test(t)) return "center";
      if (/^-+:$/.test(t)) return "right";
      if (/^:-+$/.test(t)) return "left";
      return "";
    }) : [];
    const headHtml = [`<tr data-rs="${header.start}">`];
    header.cells.forEach((c, idx) => {
      const style = aligns[idx] ? ` style="text-align:${aligns[idx]}"` : "";
      headHtml.push(`<th data-bs="${c.pos}" data-be="${c.pos + c.length}"${style}>${parseInline(c.text.trim(), { from: c.pos, to: c.pos + c.length })}</th>`);
    });
    headHtml.push("</tr>");

    const bodyHtml = [];
    bodyRows.forEach(row => {
      bodyHtml.push(`<tr data-rs="${row.start}">`);
      row.cells.forEach((c, idx) => {
        const style = aligns[idx] ? ` style="text-align:${aligns[idx]}"` : "";
        bodyHtml.push(`<td data-bs="${c.pos}" data-be="${c.pos + c.length}"${style}>${parseInline(c.text.trim(), { from: c.pos, to: c.pos + c.length })}</td>`);
      });
      bodyHtml.push("</tr>");
    });

    const last = tableRows[tableRows.length - 1];
    html.push(`<div class="table-wrap" data-bs="${header.start}" data-be="${last.end}" data-rows="${tableRows.length}">` +
      `<table><thead>${headHtml.join("")}</thead><tbody>${bodyHtml.join("")}</tbody></table></div>`);
    tableRows = [];
    inTable = false;
  }

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw;

    // Fenced code block
    const fenceMatch = line.match(/^(\s*)```(.*)$/);
    if (fenceMatch) {
      if (!inCodeBlock) {
        flushParagraph();
        closeLists();
        inCodeBlock = true;
        codeLang = fenceMatch[2].trim();
        codeBuffer = [];
        codeStart = lineStart(i);
      } else {
        inCodeBlock = false;
        const langClass = codeLang ? ` class="language-${escapeHtml(codeLang)}"` : "";
        html.push(`<pre data-bs="${codeStart}" data-be="${lineStart(i) + line.length}"><code${langClass}>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
        codeBuffer = [];
        codeLang = "";
      }
      i++;
      continue;
    }
    if (inCodeBlock) {
      codeBuffer.push(raw);
      i++;
      continue;
    }

    // Blank line
    if (/^\s*$/.test(line)) {
      flushParagraph();
      closeLists();
      flushTable();
      i++;
      continue;
    }

    // Table detection
    if (/^\s*\|.*\|\s*$/.test(line) || (line.includes("|") && lines[i + 1] && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1]))) {
      const nextLine = lines[i + 1] || "";
      if (/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(nextLine)) {
        flushParagraph();
        closeLists();
        const cellRow = (lineIdx) => {
          const lineText = lines[lineIdx];
          const cells = [];
          let cursor = 0;
          for (const rawCell of splitRowCells(lineText)) {
            const at = lineText.indexOf(rawCell, cursor);
            cursor = at === -1 ? cursor : at + rawCell.length;
            cells.push({ text: rawCell, pos: lineStart(lineIdx) + Math.max(at, 0), length: rawCell.length });
          }
          return {
            cells,
            start: lineStart(lineIdx),
            end: lineStart(lineIdx) + lineText.length,
          };
        };
        tableRows = [cellRow(i), cellRow(i + 1)];
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          tableRows.push(cellRow(i));
          i++;
        }
        flushTable();
        continue;
      }
    }

    // Horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph();
      closeLists();
      html.push(`<hr data-bs="${lineStart(i)}">`);
      i++;
      continue;
    }

    // Headers
    const headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headerMatch) {
      flushParagraph();
      closeLists();
      const level = headerMatch[1].length;
      const text = headerMatch[2].trim();
      const from = lineStart(i) + line.indexOf(text, headerMatch[1].length);
      html.push(`<h${level} data-bs="${from}" data-be="${from + text.length}">${parseInline(text, { from, to: from + text.length })}</h${level}>`);
      i++;
      continue;
    }

    // Blockquote
    const quoteMatch = line.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      closeLists();
      const innerStarts = [lineStart(i) + line.indexOf(quoteMatch[1], 1)];
      const quoteLines = [quoteMatch[1]];
      i++;
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        const inner = lines[i].replace(/^\s*>\s?/, "");
        quoteLines.push(inner);
        innerStarts.push(lineStart(i) + lines[i].length - inner.length);
        i++;
      }
      const base = innerStarts[0];
      const size = quoteLines.map(l => l.length).reduce((a, b) => a + b, 0) + Math.max(0, quoteLines.length - 1);
      const inner = parseMarkdown(quoteLines.join("\n"), false);
      html.push(`<blockquote data-bs="${base}" data-be="${base + size}">${inner}</blockquote>`);
      continue;
    }

    // Task list item
    const taskMatch = line.match(/^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$/);
    if (taskMatch) {
      flushParagraph();
      const indent = taskMatch[1].length;
      const checked = taskMatch[2].toLowerCase() === "x";
      const at = lineStart(i);
      ensureList("ul", indent, at);
      let taskText = taskMatch[3];
      const from = at + line.indexOf(taskText, indent + 5);
      const taskCont = collectContinuation(i + 1);
      if (taskCont.text) { taskText += " " + taskCont.text; }
      i = taskCont.next;
      html.push(`<li class="task-item" data-bs="${at}"${listMeta()}>` +
        `<input type="checkbox"${checked ? " checked" : ""} data-task="1"> ` +
        `<span data-bs="${from}" data-be="${from + taskText.length}">${parseInline(taskText, { from, to: from + taskText.length })}</span></li>`);
      continue;
    }

    // Unordered list item
    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (ulMatch) {
      flushParagraph();
      const indent = ulMatch[1].length;
      const at = lineStart(i);
      ensureList("ul", indent, at);
      let itemText = ulMatch[2];
      const from = at + line.indexOf(itemText, indent);
      const ulCont = collectContinuation(i + 1);
      if (ulCont.text) itemText += " " + ulCont.text;
      i = ulCont.next;
      html.push(`<li data-bs="${at}"${listMeta()} data-be="${from + itemText.length}">${parseInline(itemText, { from, to: from + itemText.length })}</li>`);
      continue;
    }

    // Ordered list item
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      flushParagraph();
      const indent = olMatch[1].length;
      const at = lineStart(i);
      ensureList("ol", indent, at);
      let olText = olMatch[2];
      const from = at + line.indexOf(olText, indent);
      const olCont = collectContinuation(i + 1);
      if (olCont.text) olText += " " + olCont.text;
      i = olCont.next;
      html.push(`<li data-bs="${at}"${listMeta()} data-be="${from + olText.length}">${parseInline(olText, { from, to: from + olText.length })}</li>`);
      continue;
    }

    // Paragraph text
    closeLists();
    if (paragraphStart === null) paragraphStart = lineStart(i) + (line.length - line.trimStart().length);
    paragraphBuffer.push(line.trim());
    i++;
  }

  flushParagraph();
  closeLists();
  flushTable();
  if (inCodeBlock) {
    // Unterminated fence: render what we have rather than dropping it.
    html.push(`<pre data-bs="${codeStart}"><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
  }

  if (isRoot && footnoteOrder.length) {
    html.push('<section class="footnotes"><hr><ol>');
    footnoteOrder.forEach((id) => {
      const def = footnoteDefs.get(id);
      const body = def ? def.text : "";
      const from = def ? def.pos : 0;
      html.push(
        `<li id="fn-${escapeHtml(id)}" data-bs="${from}" data-be="${from + body.length}">` +
        `${parseInline(body, { from, to: from + body.length })} ` +
        `<a href="#fnref-${escapeHtml(id)}" class="footnote-backref" title="Kembali ke teks">&#8617;</a></li>`
      );
    });
    html.push("</ol></section>");
  }

  return html.join("\n");
}

/* ===================== App Logic ===================== */

const editor = document.getElementById("editor");
const preview = document.getElementById("preview");
const filenameInput = document.getElementById("filename");
const workspace = document.getElementById("workspace");
const viewSwitch = document.getElementById("viewSwitch");
const themeToggle = document.getElementById("themeToggle");
const openBtn = document.getElementById("openBtn");
const saveBtn = document.getElementById("saveBtn");
const exportHtmlBtn = document.getElementById("exportHtmlBtn");
const fileInput = document.getElementById("fileInput");
const divider = document.getElementById("divider");
const editorPane = document.getElementById("editorPane");
const wordCountEl = document.getElementById("wordCount");
const charCountEl = document.getElementById("charCount");
const readTimeEl = document.getElementById("readTime");
const saveStatusEl = document.getElementById("saveStatus");
const fileAlertEl = document.getElementById("fileAlert");
const fileAlertTextEl = document.getElementById("fileAlertText");
const fileAlertPrimaryEl = document.getElementById("fileAlertPrimary");
const fileAlertSecondaryEl = document.getElementById("fileAlertSecondary");
const fileAlertDismissEl = document.getElementById("fileAlertDismiss");
const tabbar = document.getElementById("tabbar");

const STORAGE_KEY = "md-editor-content";
const STORAGE_FILENAME = "md-editor-filename";
const STORAGE_THEME = "md-editor-theme";

/* ---- External-change tracking ----
   The server hands out an opaque revision token (mtime-ns + size) on every
   read and write. We remember the revision the editor buffer is based on and
   compare it with the token on disk to notice edits made by other apps. */
const WATCH_INTERVAL_MS = 2000;
const API_PREFIX = "/api/";
const newlinePattern = /\r\n?/g;

let knownRevision = null;   // revision of the file content the editor is based on
let diskRevision = null;    // revision last seen on disk
let externalChange = false; // disk moved away from knownRevision
let lastDiskContent = null; // disk text as of the last check, for the preview
let alertMode = null;       // null | "changed" | "conflict"
let watchTimer = null;
let openEventTimer = null;
let openEventPolling = false;

const DEFAULT_CONTENT = `# Selamat Datang di MD Editor

Ini adalah editor **Markdown** dengan pratinjau langsung.

## Fitur

- Tampilan split editor & preview
- Toolbar format cepat
- Simpan / buka file \`.md\`
- Ekspor ke \`.html\`
- Mode gelap & terang
- Autosave ke local storage

## Contoh

\`\`\`js
function hello() {
  console.log("Halo dunia!");
}
\`\`\`

> Edit teks di sebelah kiri, dan lihat hasilnya di sini secara langsung.

- [x] Tulis draft
- [ ] Review
- [ ] Publish

| Fitur | Status |
| --- | :---: |
| Editor | âœ… |
| Preview | âœ… |
| Export | âœ… |

[Pelajari Markdown](https://www.markdownguide.org)
`;

const STORAGE_TABS = "md-editor-tabs";
let saveTimeout = null;
let currentFilePath = null; // set when opened via the local server (server.py) from a real file on disk

// Each tab owns its document metadata and buffer. The existing editor surface is
// reused when switching tabs, so rich-preview state remains lightweight.
const tabs = [];
let activeTabId = null;
let tabSequence = 0;

function activeTab() {
  return tabs.find(tab => tab.id === activeTabId);
}

function persistTabs() {
  snapshotActiveTab();
  try {
    localStorage.setItem(STORAGE_TABS, JSON.stringify({
      activeId: activeTabId,
      tabs: tabs.map(({ richState, saveTimer, savePromise, ...tab }) => tab),
    }));
    const tab = activeTab();
    if (tab) {
      localStorage.setItem(STORAGE_KEY, tab.content);
      localStorage.setItem(STORAGE_FILENAME, tab.filename);
    }
  } catch (_) { /* Keep the live buffers if storage is unavailable or full. */ }
}

function snapshotActiveTab() {
  const tab = tabs.find(t => t.id === activeTabId);
  if (!tab) return;
  tab.content = getContent();
  tab.filename = filenameInput.value;
  tab.path = currentFilePath;
  tab.dir = currentFileDir;
  tab.knownRevision = knownRevision;
  tab.diskRevision = diskRevision;
  tab.lastDiskContent = lastDiskContent;
  tab.externalChange = externalChange;
  tab.alertMode = alertMode;
  tab.status = saveStatusEl.textContent;
  tab.selectionStart = editor.selectionStart;
  tab.selectionEnd = editor.selectionEnd;
  tab.scrollTop = editor.scrollTop;
  tab.previewScrollTop = document.getElementById("previewPane").scrollTop;
  if (richReady && richHandle.captureState) tab.richState = richHandle.captureState();
}

function renderTabs() {
  tabbar.innerHTML = "";
  tabs.forEach(tab => {
    const item = document.createElement("div");
    item.className = `tab${tab.id === activeTabId ? " active" : ""}`;
    item.dataset.tabId = String(tab.id);
    const button = document.createElement("button");
    button.className = "tab-label";
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(tab.id === activeTabId));
    button.title = tab.path || tab.filename;
    // The dirty marker is its own element rather than a suffix in the label,
    // so the filename itself stays stable and ellipsizes predictably.
    button.textContent = tab.filename || "untitled.md";
    item.append(button);
    if (tab.dirty) {
      const dot = document.createElement("span");
      dot.className = "tab-dirty";
      dot.title = "Belum disimpan";
      dot.setAttribute("aria-label", "Belum disimpan");
      item.append(dot);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.className = "tab-close";
    close.textContent = "×";
    close.title = "Tutup tab";
    close.setAttribute("aria-label", `Tutup ${tab.filename}`);
    close.addEventListener("click", event => {
      event.stopPropagation();
      closeTab(tab.id);
    });
    item.append(close);
    button.addEventListener("click", () => activateTab(tab.id));
    // Middle-click closes, matching every tabbed editor users already know.
    item.addEventListener("auxclick", event => {
      if (event.button === 1) { event.preventDefault(); closeTab(tab.id); }
    });
    tabbar.appendChild(item);
  });
  if (typeof updateTabOverflowHint === "function") updateTabOverflowHint();
}

// Keep the active tab visible when the row is wider than the window.
function updateTabOverflowHint() {
  requestAnimationFrame(() => {
    const active = tabbar.querySelector(".tab.active");
    if (active) active.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
}

function activateTab(id) {
  if (id === activeTabId) return;
  snapshotActiveTab();
  const tab = tabs.find(t => t.id === id);
  if (!tab) return;
  activeTabId = id;
  currentFilePath = tab.path;
  currentFileDir = tab.dir;
  knownRevision = tab.knownRevision;
  diskRevision = tab.diskRevision;
  lastDiskContent = tab.lastDiskContent;
  externalChange = tab.externalChange;
  filenameInput.value = tab.filename || "untitled.md";
  editor.value = tab.content || "";
  richDirty = false;
  if (richReady && richHandle.restoreState) {
    richApplying = true;
    clearTimeout(richApplyTimer);
    richHandle.restoreState(tab.richState || null, editor.value);
    richApplyTimer = setTimeout(() => { richApplying = false; refreshRichDirty(); }, 250);
    richDirty = false;
  } else {
    pushToRich(editor.value);
  }
  editor.setSelectionRange(tab.selectionStart || 0, tab.selectionEnd || 0);
  editor.scrollTop = tab.scrollTop || 0;
  document.getElementById("previewPane").scrollTop = tab.previewScrollTop || 0;
  hideAlert();
  if (tab.alertMode) showAlert(tab.alertMode);
  saveStatusEl.textContent = tab.status || (tab.path ? `Dibuka dari ${tab.path}` : "Tersimpan otomatis");
  renderTabs();
  render();
  persistTabs();
  if (currentFilePath) { startWatching(); checkForExternalChange(); }
}

function createTab(data = {}) {
  snapshotActiveTab();
  const tab = {
    id: ++tabSequence, content: data.content || "", filename: data.filename || "untitled.md",
    path: data.path || null, dir: data.dir || null, knownRevision: data.knownRevision || null,
    diskRevision: data.diskRevision || null, lastDiskContent: data.lastDiskContent ?? null,
    externalChange: false, dirty: false, ...data,
  };
  tabs.push(tab);
  activeTabId = null;
  activateTab(tab.id);
  renderTabs();
  return tab;
}

async function closeTab(id) {
  snapshotActiveTab();
  const tab = tabs.find(t => t.id === id);
  if (!tab || tab.closing) return;
  tab.closing = true;
  clearTimeout(tab.saveTimer);

  // Try to flush the tab before asking anything. `saveTab` returns false when
  // the write was refused (file changed on disk, or the save failed), and it
  // deliberately leaves `dirty` set in that case — so judge by its result
  // rather than by `dirty`, which would prompt a second time right after the
  // user already chose to save.
  let flushed = true;
  if (tab.path && tab.dirty) flushed = await saveTab(tab);

  if (!flushed && tab.dirty) {
    const proceed = window.confirm(
      `Perubahan pada ${tab.filename} belum tersimpan ke file. Tutup tab dan buang perubahan?`);
    if (!proceed) {
      tab.closing = false;
      return;
    }
  }

  const index = tabs.indexOf(tab);
  const wasActive = id === activeTabId;
  tabs.splice(index, 1);
  if (wasActive) {
    activeTabId = null;
    if (tabs.length) activateTab(tabs[Math.min(index, tabs.length - 1)].id);
    else createTab();
  }
  renderTabs();
  persistTabs();
}

// A tab nobody has touched yet: no disk path and an empty buffer. Reusing one
// keeps a stray "untitled" tab from piling up next to every opened file.
function isPristineTab(tab) {
  return Boolean(tab) && !tab.path && !tab.dirty && !(tab.content || "").trim();
}

async function openFilePath(path, newTab = true) {
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Gagal membuka file");
    const content = (data.content || "").replace(newlinePattern, "\n");
    const canonicalPath = value => value.replace(/\\/g, "/").toLowerCase();
    const existing = tabs.find(tab => tab.path && canonicalPath(tab.path) === canonicalPath(data.path));
    if (existing) {
      activateTab(existing.id);
      return;
    }
    const loaded = {
      content, filename: data.name, path: data.path, dir: dirnameOf(data.path),
      knownRevision: data.revision, diskRevision: data.revision, lastDiskContent: content,
      status: `Dibuka dari ${data.path}`,
    };
    // Take over the current tab only when it is an untouched draft; otherwise
    // the new file opens in its own tab.
    const target = newTab ? null : activeTab();
    if (isPristineTab(target)) {
      Object.assign(target, loaded, { dirty: false });
      tabs.splice(tabs.indexOf(target), 1);
      activeTabId = null;
      tabs.push(target);
      activateTab(target.id);
    } else {
      createTab(loaded);
    }
    startWatching(); initRichEditor();
  } catch (err) { saveStatusEl.textContent = `Gagal membuka file: ${err.message}`; }
}

/* ===================== Rich preview editor =====================
   The preview pane hosts a real rich-text editor (Milkdown Crepe). Markdown
   stays the storage format, so everything below keeps working unchanged:
   `getContent()` is the single place that answers "what is the document text
   right now", whether the user typed in the textarea or in the preview. */

const richHost = document.getElementById("richEditor");

let richHandle = null;         // handle returned by MDEditorRich.createRichEditor
let richReady = false;         // editor finished creating
let richApplying = false;      // we are pushing text into it, ignore echoes
let richDirty = false;         // the rich editor holds edits not yet in the textarea
let richMode = "wysiwyg";      // "wysiwyg" (rich preview) | "code" (textarea)

const RICH_AVAILABLE = typeof window.MDEditorRich !== "undefined";

// Markdown of the document. Either surface may hold the newest edit, so the
// writer of the most recent change marks it with `richDirty` / clears it.
function getContent() {
  if (richMode === "wysiwyg" && richReady && richDirty) {
    try {
      return richHandle.getMarkdown();
    } catch (err) {
      return editor.value;
    }
  }
  return editor.value;
}

// True while the preview editor still holds edits that came from it, not from
// the textarea. Tab switches push a whole new document, so this must be
// recomputed against the buffer instead of trusted blindly.
function refreshRichDirty() {
  if (richMode !== "wysiwyg" || !richReady || !richHandle) {
    richDirty = false;
    return;
  }
  try {
    richDirty = richHandle.getMarkdown() !== editor.value;
  } catch (err) {
    richDirty = false;
  }
}

function setContent(markdown) {
  editor.value = markdown;
  richDirty = false;
  pushToRich(markdown);
}

// Push text into the rich editor without treating it as a user edit.
// Crepe emits `markdownUpdated` asynchronously, so the guard is cleared on a
// later tick rather than immediately.
let richApplyTimer = null;

function pushToRich(markdown) {
  if (!richReady || !richHandle) return;
  let current;
  try {
    current = richHandle.getMarkdown();
  } catch (err) {
    current = null;
  }
  if (current === markdown) {
    richDirty = false;
    return;
  }
  richApplying = true;
  clearTimeout(richApplyTimer);
  try {
    richHandle.setMarkdown(markdown);
  } catch (err) {
    richApplying = false;
    return;
  }
  richDirty = false;
  richApplyTimer = setTimeout(() => { richApplying = false; }, 250);
}

let richInitPromise = null;

async function initRichEditor() {
  if (!RICH_AVAILABLE) return null;
  // Creating the editor is async, so guard the whole attempt rather than just
  // the handle: a second call before the first settles would build a second
  // editor and leave two live instances fighting over the toolbar.
  if (richInitPromise) return richInitPromise;
  if (richHandle) return richHandle;

  richInitPromise = (async () => {
    const handle = await window.MDEditorRich.createRichEditor(richHost, {
      initialValue: editor.value,
      onChange: (markdown) => {
        if (richApplying) return;
        // Mirror rich edits into the textarea so code view, stats, export and
        // saving all read the same text.
        editor.value = markdown;
        richDirty = true;
        updateStats();
        scheduleSave();
      },
    });
    richHandle = handle;
    richReady = true;
    // A file may have been opened while Crepe was still mounting.
    pushToRich(editor.value);
    refreshRichDirty();
    richHost.hidden = false;
    preview.hidden = true;
    applyRichTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
    return handle;
  })();

  return richInitPromise;
}

// Switch the preview pane between the rich editor and the plain rendered view.
function applyRichMode() {
  const useRich = RICH_AVAILABLE;
  if (useRich && !richHandle) {
    initRichEditor();
    return;
  }
  if (!richHandle) return;
  richHost.hidden = !useRich;
  preview.hidden = useRich;
  if (useRich) pushToRich(editor.value);
}

function render() {
  if (richMode === "wysiwyg" && richReady) {
    // The rich editor owns the preview; just refresh the derived readouts.
    updateStats();
    return;
  }
  preview.innerHTML = parseMarkdown(editor.value);
  updateStats();
}

function updateStats() {
  const content = getContent();
  const text = content.trim();
  const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
  const chars = content.length;
  const minutes = Math.max(1, Math.round(words / 200));
  wordCountEl.textContent = `${words} kata`;
  charCountEl.textContent = `${chars} karakter`;
  readTimeEl.textContent = `${minutes} min baca`;
}

function syncTabStatus(tab) {
  if (tab.id === activeTabId) {
    knownRevision = tab.knownRevision;
    diskRevision = tab.diskRevision;
    lastDiskContent = tab.lastDiskContent;
    externalChange = tab.externalChange;
    if (tab.alertMode) showAlert(tab.alertMode);
    else hideAlert();
    saveStatusEl.textContent = tab.status;
  }
  renderTabs();
  persistTabs();
}

function scheduleSave() {
  snapshotActiveTab();
  const tab = activeTab();
  if (!tab) return;
  tab.dirty = true;
  tab.status = "Menyimpan...";
  clearTimeout(tab.saveTimer);
  syncTabStatus(tab);
  tab.saveTimer = setTimeout(() => saveTab(tab), 400);
}

async function saveTab(tab, manual = false) {
  // Serialize writes for each document. Never read the active editor after an
  // await: the user may already be in another tab (or have typed newer text).
  if (tab.savePromise) {
    await tab.savePromise;
    if (!tab.dirty) return true;
  }
  if (tab.id === activeTabId) snapshotActiveTab();
  if (!tab.path) {
    tab.status = "Draft tersimpan otomatis";
    syncTabStatus(tab);
    return true;
  }
  if (tab.externalChange) {
    tab.alertMode = manual ? "conflict" : "changed";
    tab.status = "Perubahan belum disimpan (file berubah di luar)";
    syncTabStatus(tab);
    return false;
  }
  const content = tab.content;
  const path = tab.path;
  tab.status = "Menyimpan...";
  syncTabStatus(tab);
  tab.savePromise = (async () => {
    try {
      const res = await fetch(`/api/save?path=${encodeURIComponent(path)}&base_rev=${encodeURIComponent(tab.knownRevision || "-")}`,
        { method: "POST", body: content });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) {
        tab.diskRevision = data.revision || tab.diskRevision;
        tab.externalChange = true;
        tab.alertMode = manual ? "conflict" : "changed";
        tab.status = "Belum disimpan: file berubah di luar MD Editor";
        return false;
      }
      if (!res.ok) throw new Error(data.error || "Gagal menyimpan");
      if (tab.id === activeTabId) snapshotActiveTab();
      tab.knownRevision = data.revision || tab.knownRevision;
      tab.diskRevision = data.revision || tab.diskRevision;
      tab.lastDiskContent = content.replace(newlinePattern, "\n");
      tab.externalChange = false;
      tab.alertMode = null;
      tab.dirty = tab.content !== content;
      tab.status = tab.dirty ? "Perubahan belum disimpan" : `Tersimpan ke ${path}`;
      return true;
    } catch (err) {
      tab.status = `Gagal menyimpan: ${err.message}`;
      return false;
    } finally {
      syncTabStatus(tab);
    }
  })();
  try { return await tab.savePromise; }
  finally { tab.savePromise = null; }
}

/* ---- External-change detection ---- */
function showAlert(mode) {
  alertMode = mode;
  if (mode === "conflict") {
    fileAlertTextEl.textContent =
      "File berubah di luar MD Editor dan versi di layar belum tersimpan. " +
      "Pilih mana yang dipertahankan:";
    fileAlertPrimaryEl.textContent = "Muat ulang dari disk";
    fileAlertSecondaryEl.textContent = "Timpa dengan versi saya";
  } else {
    fileAlertTextEl.textContent =
      "File ini berubah di luar MD Editor. Versi di layar tidak ikut diperbarui, " +
      "dan autosave dijeda agar perubahan lain tidak tertimpa.";
    fileAlertPrimaryEl.textContent = "Muat ulang dari disk";
    fileAlertSecondaryEl.textContent = "Pertahankan versi saya";
  }
  fileAlertEl.hidden = false;
}

function hideAlert() {
  alertMode = null;
  fileAlertEl.hidden = true;
}

function countNewlines(text) {
  return (text.match(/\n/g) || []).length;
}

async function checkForExternalChange() {
  const tab = activeTab();
  if (!currentFilePath || !tab || tab.savePromise) return;
  const checkedRevision = knownRevision;

  let data;
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent(currentFilePath)}`);
    if (!res.ok) return; // deleted, locked, or temporarily unreadable: stay quiet
    data = await res.json();
  } catch (err) {
    return; // server hiccup; try again on the next tick
  }

  if (activeTabId !== tab.id || tab.savePromise || knownRevision !== checkedRevision) return;
  const incoming = (data.content || "").replace(newlinePattern, "\n");
  const revision = data.revision;

  if (revision === diskRevision && incoming === lastDiskContent) return;

  const previousDisk = lastDiskContent;
  diskRevision = revision;
  lastDiskContent = incoming;

  if (revision === knownRevision) {
    // The change on disk is the one we wrote ourselves.
    externalChange = false;
    if (alertMode === "changed") hideAlert();
    if (activeTab()) { activeTab().diskRevision = revision; activeTab().lastDiskContent = incoming; }
    return;
  }

  externalChange = true;

  if (!getContent().trim() && incoming.trim()) {
    // Nothing typed here yet, so there is nothing to lose: just follow the file.
    loadDiskContent(data);
    hideAlert();
    return;
  }

  let delta = null;
  if (previousDisk !== null) {
    const deltaLines = countNewlines(incoming) - countNewlines(previousDisk);
    const deltaChars = incoming.length - previousDisk.length;
    if (deltaLines || deltaChars) {
      delta = `${deltaLines >= 0 ? "+" : ""}${deltaLines} baris, ` +
             `${deltaChars >= 0 ? "+" : ""}${deltaChars} karakter`;
    }
  }
  saveStatusEl.textContent = `File berubah di luar MD Editor${delta ? ` (${delta})` : ""}`;
  if (alertMode !== "conflict") showAlert("changed");
  if (activeTab()) { activeTab().externalChange = true; activeTab().alertMode = alertMode; activeTab().status = saveStatusEl.textContent; }
}

function startWatching() {
  if (watchTimer || !currentFilePath) return;
  watchTimer = setInterval(checkForExternalChange, WATCH_INTERVAL_MS);
}

function startOpenEventPolling() {
  if (openEventTimer) return;
  openEventTimer = setInterval(async () => {
    if (openEventPolling) return;
    openEventPolling = true;
    try {
      const res = await fetch("/api/open-events");
      if (!res.ok) return;
      const data = await res.json();
      for (const path of (data.paths || [])) await openFilePath(path);
    } catch (_) { /* optional desktop handoff endpoint */ }
    finally { openEventPolling = false; }
  }, 500);
}

function loadDiskContent(data) {
  const incoming = (data.content || "").replace(newlinePattern, "\n");
  const priorLine = editor.value.slice(0, editor.selectionStart).split("\n").length;
  setContent(incoming);
  knownRevision = data.revision;
  diskRevision = data.revision;
  lastDiskContent = incoming;
  externalChange = false;
  filenameInput.value = data.name || filenameInput.value;

  // Keep the caret roughly where it was instead of jumping to the top.
  const totalLines = countNewlines(incoming) + 1;
  const targetLine = Math.min(priorLine, totalLines);
  let offset = 0;
  for (let i = 1; i < targetLine; i++) {
    const nl = incoming.indexOf("\n", offset);
    if (nl === -1) break;
    offset = nl + 1;
  }
  editor.setSelectionRange(offset, offset);

  render();
  localStorage.setItem(STORAGE_KEY, incoming);
  saveStatusEl.textContent = `Dimuat ulang dari disk (${data.path})`;
  if (activeTab()) activeTab().dirty = false;
  persistTabs();
  renderTabs();
}

async function reloadFromDisk({ force = false } = {}) {
  if (!currentFilePath) return;
  const tab = activeTab();
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent(currentFilePath)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Gagal membuka file");
    if (activeTabId !== tab.id) return;
    loadDiskContent(data);
    hideAlert();
    if (force) saveStatusEl.textContent = `Dimuat ulang dari disk (${data.path})`;
  } catch (err) {
    saveStatusEl.textContent = `Gagal memuat ulang: ${err.message}`;
  }
}

// "Keep mine": adopt the on-disk revision so the next autosave is allowed to
// overwrite it, then close the alert. The user has explicitly chosen this.
function keepLocalVersion() {
  const tab = activeTab();
  const revision = diskRevision;
  knownRevision = revision;
  externalChange = false;
  if (tab) { tab.knownRevision = revision; tab.externalChange = false; tab.alertMode = null; }
  hideAlert();
  saveStatusEl.textContent = "Versi di layar dipertahankan; file akan ditimpa saat menyimpan";
  if (getContent().replace(newlinePattern, "\n") !== lastDiskContent) scheduleSave();
}

/* ---- Alert buttons ---- */
fileAlertPrimaryEl.addEventListener("click", () => reloadFromDisk({ force: true }));
fileAlertSecondaryEl.addEventListener("click", keepLocalVersion);
fileAlertDismissEl.addEventListener("click", () => {
  // Dismiss only silences the banner; the autosave guard stays active.
  hideAlert();
  const tab = activeTab();
  if (tab) tab.alertMode = null;
  if (externalChange) {
    saveStatusEl.textContent = "File berubah di luar MD Editor; autosave dijeda";
  }
});


editor.addEventListener("input", () => {
  // Typing in the source pane makes the textarea authoritative again; the rich
  // preview is refreshed from it below.
  richDirty = false;
  pushToRich(editor.value);
  render();
  scheduleSave();
});

filenameInput.addEventListener("input", () => {
  const tab = activeTab();
  if (tab) tab.filename = filenameInput.value;
  renderTabs();
  scheduleSave();
});

/* ---- Load saved state ---- */
function restoreTabs() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_TABS) || "null");
  } catch (_) {
    saved = null;
  }
  if (!saved || !Array.isArray(saved.tabs) || !saved.tabs.length) return false;
  const previousIds = saved.tabs.map(entry => entry && entry.id);
  saved.tabs.forEach(entry => {
    if (!entry || typeof entry !== "object") return;
    entry.id = ++tabSequence;
  });
  saved.tabs.forEach(entry => { if (entry && typeof entry === "object") createTab(entry); });
  const wanted = tabs[previousIds.indexOf(saved.activeId)];
  if (wanted) activateTab(wanted.id);
  return tabs.length > 0;
}

async function init() {
  const savedContent = localStorage.getItem(STORAGE_KEY);
  const savedFilename = localStorage.getItem(STORAGE_FILENAME);
  const savedTheme = localStorage.getItem(STORAGE_THEME);

  if (savedTheme) {
    applyTheme(savedTheme);
  }

  try {
    const res = await fetch("/api/settings");
    if (res.ok) {
      const settings = await res.json();
      if (settings.theme && settings.theme !== savedTheme) {
        applyTheme(settings.theme);
        localStorage.setItem(STORAGE_THEME, settings.theme);
      }
    }
  } catch (e) {
    /* no server settings available yet; localStorage value stands */
  }

  const pathParam = new URLSearchParams(location.search).get("path");

  // Restore the previous session first, even for a ?path= launch. WebView2
  // keeps the launch URL for the window's whole life, so a reload (or a crash
  // recovery) of a window opened by double-click would otherwise discard every
  // tab except the one file in the URL.
  const restored = restoreTabs();

  if (pathParam) {
    saveStatusEl.textContent = "Membuka file...";
    // openFilePath reuses the tab if this exact file is already restored.
    await openFilePath(pathParam, false);
  } else if (!restored) {
    createTab({ content: savedContent !== null ? savedContent : DEFAULT_CONTENT, filename: savedFilename || "untitled.md" });
  }
  render();
  startOpenEventPolling();
  // Bring up the rich preview editor once the initial document is loaded.
  initRichEditor();
}

init();

// WebView2 keeps timers running in the background, but a window that was
// hidden or suspended can miss ticks, so re-check as soon as we get focus.
window.addEventListener("focus", () => {
  if (currentFilePath) checkForExternalChange();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && currentFilePath) checkForExternalChange();
});


/* ---- Toolbar formatting ----
   Two editing surfaces have to share one toolbar. When the caret is in the
   rich preview, the command is handed to the rich editor (which is what makes
   "select text, click Bold" work there); otherwise the textarea path below
   runs, unchanged. */

// `richCommand` receives the ProseMirror command(s) to run in the preview.
const toolbarActions = {
  bold: { rich: ["toggleStrong"], md: () => wrapSelection("**", "**", "teks tebal") },
  italic: { rich: ["toggleEmphasis"], md: () => wrapSelection("*", "*", "teks miring") },
  strike: { rich: ["toggleStrikethrough"], md: () => wrapSelection("~~", "~~", "teks dicoret") },
  h1: { rich: ["setHeading", 1], md: () => prefixLines("# ") },
  h2: { rich: ["setHeading", 2], md: () => prefixLines("## ") },
  h3: { rich: ["setHeading", 3], md: () => prefixLines("### ") },
  quote: { rich: ["wrapInBlockquote"], md: () => prefixLines("> ") },
  code: { rich: ["toggleInlineCode"], md: () => wrapSelection("`", "`", "kode") },
  codeblock: { rich: ["createCodeBlock"], md: () => insertAtCursor("\n```\nkode di sini\n```\n", 5) },
  ul: { rich: ["wrapInBulletList"], md: () => prefixLines("- ") },
  ol: { rich: ["wrapInOrderedList"], md: () => prefixLines("1. ") },
  task: { md: () => prefixLines("- [ ] ") },
  link: { rich: ["toggleLink"], md: () => wrapSelection("[", "](https://)", "teks tautan") },
  image: { md: () => insertAtCursor("![alt teks](https://)", 2) },
  table: { md: () => insertAtCursor(
    "\n| Kolom 1 | Kolom 2 |\n| --- | --- |\n| Isi 1 | Isi 2 |\n", 1
  ) },
  hr: { rich: ["insertHr"], md: () => insertAtCursor("\n---\n", 5) },
  footnote: { md: () => insertFootnote() },
};

// True while the rich preview owns the selection.
function richHasFocus() {
  return richReady && !richHost.hidden && richHost.contains(document.activeElement);
}

// Clicking a toolbar button moves focus out of the preview, which would drop
// the user's selection before the command runs. `mousedown` fires before the
// focus change, so the selection is captured there and restored on click.
let savedRichSelection = null;

function rememberRichSelection() {
  if (!richReady || !richHandle || richHost.hidden) return;
  const sel = document.getSelection();
  if (sel && sel.rangeCount && richHost.contains(sel.anchorNode)) {
    savedRichSelection = sel.getRangeAt(0).cloneRange();
  } else {
    // The preview no longer holds a selection, so a stale range must not be
    // restored later — that would hijack a command meant for the textarea.
    savedRichSelection = null;
  }
}

function restoreRichSelection() {
  if (!savedRichSelection) return false;
  const sel = document.getSelection();
  try {
    sel.removeAllRanges();
    sel.addRange(savedRichSelection);
    return true;
  } catch (err) {
    // The range referred to content that a re-render has replaced.
    savedRichSelection = null;
    return false;
  }
}

document.getElementById("toolbar").addEventListener("mousedown", rememberRichSelection);

// Any interaction with the source pane means the toolbar should act there.
editor.addEventListener("focus", () => { savedRichSelection = null; });
richHost.addEventListener("focusin", rememberRichSelection);

// Apply a ProseMirror command by name inside the rich editor.
function runRichCommand(name, arg) {
  const cmds = window.MDEditorRich.commands;
  const factory = cmds && cmds[name];
  if (!factory || !richHandle) return false;
  richHandle.focus();
  const ok = richHandle.run(factory(arg));
  if (ok) {
    editor.value = richHandle.getMarkdown();
    richDirty = true;
    updateStats();
    scheduleSave();
  }
  return ok;
}

function runToolbarAction(cmd) {
  const action = toolbarActions[cmd];
  if (!action) return;

  // Prefer the preview only when it genuinely holds the selection: either it
  // has focus right now, or a mousedown on the toolbar stashed a live range.
  const previewOwnsSelection = richReady && !richHost.hidden &&
    (richHasFocus() || savedRichSelection !== null);

  if (previewOwnsSelection && action.rich) {
    if (!richHasFocus() && !restoreRichSelection()) {
      // The stashed range went stale; fall through to the textarea path.
      savedRichSelection = null;
    } else if (runRichCommand(action.rich[0], action.rich[1])) {
      return;
    }
  }
  if (action.md) action.md();
}

/* ---- Toolbar formatting: textarea paths ---- */
function wrapSelection(before, after = before, placeholder = "") {
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = editor.value.slice(start, end) || placeholder;
  const newText = editor.value.slice(0, start) + before + selected + after + editor.value.slice(end);
  editor.value = newText;
  editor.focus();
  const cursorStart = start + before.length;
  editor.setSelectionRange(cursorStart, cursorStart + selected.length);
  pushToRich(newText);
  render();
  scheduleSave();
}

function prefixLines(prefix) {
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const value = editor.value;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  let lineEnd = value.indexOf("\n", end);
  if (lineEnd === -1) lineEnd = value.length;
  const block = value.slice(lineStart, lineEnd);
  const newBlock = block.split("\n").map(l => prefix + l).join("\n");
  const next = value.slice(0, lineStart) + newBlock + value.slice(lineEnd);
  editor.value = next;
  editor.focus();
  editor.setSelectionRange(lineStart, lineStart + newBlock.length);
  pushToRich(next);
  render();
  scheduleSave();
}

function insertAtCursor(text, cursorOffset) {
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const next = editor.value.slice(0, start) + text + editor.value.slice(end);
  editor.value = next;
  editor.focus();
  const pos = start + (cursorOffset ?? text.length);
  editor.setSelectionRange(pos, pos);
  pushToRich(next);
  render();
  scheduleSave();
}

function insertFootnote() {
  const existingIds = new Set(
    [...editor.value.matchAll(/\[\^([^\]\s]+)\]:/g)].map((m) => m[1])
  );
  let n = 1;
  while (existingIds.has(String(n))) n++;
  const id = String(n);
  insertAtCursor(`[^${id}]`, 0);
  const withRef = editor.value;
  const sep = withRef.endsWith("\n") ? "" : "\n";
  const next = withRef + `${sep}\n[^${id}]: catatan kaki`;
  editor.value = next;
  pushToRich(next);
  render();
  scheduleSave();
}

document.getElementById("toolbar").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-cmd]");
  if (!btn) return;
  e.preventDefault(); // keep the preview selection alive
  runToolbarAction(btn.dataset.cmd);
});

/* ---- Keyboard shortcuts ---- */
editor.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); runToolbarAction("bold"); }
  else if (mod && e.key.toLowerCase() === "i") { e.preventDefault(); runToolbarAction("italic"); }
  else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); runToolbarAction("link"); }
  else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveFile(); }
  else if (e.key === "Tab") {
    e.preventDefault();
    insertAtCursor("  ");
  }
});

// Same shortcuts while the caret is inside the rich preview.
richHost.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); runToolbarAction("bold"); }
  else if (mod && e.key.toLowerCase() === "i") { e.preventDefault(); runToolbarAction("italic"); }
  else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); runToolbarAction("link"); }
  else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveFile(); }
});

// Clicking a link inside the rich preview should not navigate the app away.
richHost.addEventListener("click", (e) => {
  const link = e.target.closest("a[href]");
  if (!link) return;
  e.preventDefault();
  const href = link.getAttribute("href");
  if (href && /^https?:/i.test(href)) window.open(href, "_blank");
}, true);

/* ---- View switch ---- */
viewSwitch.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (!btn) return;
  [...viewSwitch.children].forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  workspace.classList.remove("view-edit", "view-split", "view-preview");
  workspace.classList.add(`view-${btn.dataset.view}`);
});
workspace.classList.add("view-preview");

/* ---- Theme toggle ---- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeToggle.innerHTML = theme === "dark" ? "&#9728;" : "&#9788;";
  themeToggle.setAttribute("aria-label", theme === "dark" ? "Ganti ke tema terang" : "Ganti ke tema gelap");
  applyRichTheme(theme);
}

/* The dark variant of Crepe's frame theme is scoped to `.milkdown` itself, so
   the flag has to sit on that element rather than on our own wrapper. */
function applyRichTheme(theme) {
  const root = richHost.querySelector(".milkdown");
  if (root) root.classList.toggle("md-editor-dark", theme === "dark");
}

async function saveThemeSetting(theme) {
  localStorage.setItem(STORAGE_THEME, theme);
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
    });
  } catch (e) {
    /* offline settings save is best-effort; localStorage already has it */
  }
}

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  saveThemeSetting(next);
});

/* ---- File open/save ---- */
openBtn.addEventListener("click", () => fileInput.click());

// A second file opened by the desktop shell is delivered as a new tab.
window.addEventListener("md-editor-open-file", e => openFilePath(e.detail, true));

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    // Open into an untouched draft when there is one, so the picker does not
    // leave an empty "untitled" tab behind; otherwise add a tab of its own.
    const draft = activeTab();
    const tab = isPristineTab(draft) ? draft : createTab({ filename: file.name });
    setContent(reader.result);
    tab.content = reader.result;
    tab.filename = file.name;
    filenameInput.value = file.name;
    currentFilePath = null; // files picked via the browser dialog have no writable disk path
    tab.path = null;
    tab.dir = null;
    currentFileDir = null;
    // The watcher only runs for files opened with a real disk path.
    knownRevision = null;
    diskRevision = null;
    lastDiskContent = null;
    externalChange = false;
    hideAlert();
    render();
    renderTabs();
    scheduleSave();
  };
  reader.readAsText(file);
  fileInput.value = "";
});

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function saveFile() {
  if (currentFilePath) {
    saveStatusEl.textContent = "Menyimpan...";
    try {
      const res = await fetch(
        `/api/save?path=${encodeURIComponent(currentFilePath)}&base_rev=${encodeURIComponent(knownRevision || "-")}`,
        { method: "POST", body: getContent() }
      );
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) {
        // Ctrl+S on a file that moved on disk: ask instead of destroying it.
        diskRevision = data.revision || diskRevision;
        externalChange = true;
        showAlert("conflict");
        saveStatusEl.textContent = "Belum disimpan: file berubah di luar MD Editor";
        return;
      }
      if (!res.ok) throw new Error(data.error || "Gagal menyimpan");
      knownRevision = data.revision || knownRevision;
      diskRevision = data.revision || diskRevision;
      externalChange = false;
      lastDiskContent = getContent().replace(newlinePattern, "\n");
      hideAlert();
      saveStatusEl.textContent = `Tersimpan ke ${currentFilePath}`;
      return;
    } catch (err) {
      saveStatusEl.textContent = `Gagal menyimpan: ${err.message}`;
      return;
    }
  }
  let name = filenameInput.value.trim() || "untitled.md";
  if (!/\.(md|markdown|txt)$/i.test(name)) name += ".md";
  downloadBlob(getContent(), name, "text/markdown;charset=utf-8");
}

saveBtn.addEventListener("click", saveFile);

exportHtmlBtn.addEventListener("click", () => {
  let name = filenameInput.value.trim().replace(/\.(md|markdown|txt)$/i, "") || "untitled";
  const theme = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  const fullHtml = `<!DOCTYPE html>
<html lang="id" data-theme="${theme}">
<head>
<meta charset="UTF-8">
<title>${name}</title>
<style>
body{max-width:820px;margin:40px auto;padding:0 20px;font-family:-apple-system,"Segoe UI",Inter,Roboto,sans-serif;line-height:1.7;color:${theme === "dark" ? "#e6e7ea" : "#1c1f24"};background:${theme === "dark" ? "#1a1b1e" : "#ffffff"};}
h1,h2{border-bottom:1px solid ${theme === "dark" ? "#303236" : "#e3e5e8"};padding-bottom:.3em;}
code{background:${theme === "dark" ? "#26282c" : "#f1f2f5"};padding:.15em .4em;border-radius:4px;font-family:Consolas,Menlo,monospace;}
pre{background:${theme === "dark" ? "#26282c" : "#f1f2f5"};padding:14px 16px;border-radius:8px;overflow-x:auto;}
pre code{background:none;padding:0;}
blockquote{border-left:3px solid #4f46e5;margin:1em 0;padding:.3em 1em;color:${theme === "dark" ? "#9ca0a8" : "#6b7280"};}
table{border-collapse:collapse;width:100%;}
th,td{border:1px solid ${theme === "dark" ? "#303236" : "#e3e5e8"};padding:8px 12px;}
img{max-width:100%;}
a{color:#4f46e5;}
.footnotes{margin-top:2em;font-size:.88em;color:${theme === "dark" ? "#9ca0a8" : "#6b7280"};}
.footnotes ol{padding-left:1.4em;}
.footnote-backref{text-decoration:none;margin-left:4px;}
</style>
</head>
<body>
${parseMarkdown(getContent())}
</body>
</html>`;
  downloadBlob(fullHtml, `${name}.html`, "text/html;charset=utf-8");
});

/* ---- Resizable divider ---- */
let dragging = false;
divider.addEventListener("mousedown", () => {
  dragging = true;
  document.body.style.cursor = "col-resize";
});
window.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const rect = workspace.getBoundingClientRect();
  const pct = ((e.clientX - rect.left) / rect.width) * 100;
  const clamped = Math.min(80, Math.max(20, pct));
  editorPane.style.flex = `0 0 ${clamped}%`;
});
window.addEventListener("mouseup", () => {
  dragging = false;
  document.body.style.cursor = "";
});

/* ---- Sync scroll between editor and preview ---- */
editor.addEventListener("scroll", () => {
  const ratio = editor.scrollTop / (editor.scrollHeight - editor.clientHeight || 1);
  const previewPane = document.getElementById("previewPane");
  previewPane.scrollTop = ratio * (previewPane.scrollHeight - previewPane.clientHeight);
});

/* ---- Footnote click: smooth scroll + brief highlight, both directions ---- */
preview.addEventListener("click", (e) => {
  const link = e.target.closest('a[href^="#fn"]');
  if (!link) return;
  const targetId = link.getAttribute("href").slice(1);
  const target = document.getElementById(targetId);
  if (!target) return;
  e.preventDefault();
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("footnote-flash");
  setTimeout(() => target.classList.remove("footnote-flash"), 1200);
});

/* ---- Paste / drag-drop images into the editor ---- */
async function uploadImageBlob(blob, suggestedName) {
  const ext = (blob.type && blob.type.split("/")[1]) || "png";
  const name = suggestedName || `pasted-image.${ext}`;
  const dirParam = currentFileDir ? `&dir=${encodeURIComponent(currentFileDir)}` : "";
  try {
    const res = await fetch(`/api/upload-image?name=${encodeURIComponent(name)}${dirParam}`, {
      method: "POST",
      body: blob,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Gagal mengunggah gambar");
    return data;
  } catch (err) {
    saveStatusEl.textContent = `Gagal menyisipkan gambar: ${err.message}`;
    return null;
  }
}

function insertImageMarkdown(pathOrName, altText) {
  let ref = pathOrName;
  if (currentFileDir && pathOrName.startsWith(currentFileDir)) {
    ref = pathOrName.slice(currentFileDir.length).replace(/^[\\/]+/, "");
  }
  insertAtCursor(`![${altText}](${ref.replace(/\\/g, "/")})`, 0);
}

editor.addEventListener("paste", async (e) => {
  const items = Array.from(e.clipboardData?.items || []);
  const imageItem = items.find((it) => it.type.startsWith("image/"));
  if (!imageItem) return; // let default text paste happen
  e.preventDefault();
  const blob = imageItem.getAsFile();
  saveStatusEl.textContent = "Menyisipkan gambar...";
  const result = await uploadImageBlob(blob);
  if (result) {
    insertImageMarkdown(result.path, "gambar");
    saveStatusEl.textContent = "Gambar disisipkan";
  }
});

editor.addEventListener("dragover", (e) => {
  e.preventDefault();
});

editor.addEventListener("drop", async (e) => {
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => f.type.startsWith("image/"));
  if (!files.length) return; // let default handling occur for non-image drops
  e.preventDefault();
  for (const file of files) {
    saveStatusEl.textContent = "Menyisipkan gambar...";
    const result = await uploadImageBlob(file, file.name);
    if (result) {
      insertImageMarkdown(result.path, file.name.replace(/\.[^.]+$/, ""));
    }
  }
  saveStatusEl.textContent = "Gambar disisipkan";
});
