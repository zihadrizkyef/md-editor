/* Rich-text (WYSIWYG) editor bridge for MD Editor.
 *
 * Milkdown Crepe renders and edits Markdown directly, so the preview pane
 * becomes a real rich-text editor while the on-disk format stays plain
 * Markdown. esbuild bundles this into rich-editor.js, which index.html loads
 * as a plain <script> so the app keeps working fully offline (and inside the
 * PyInstaller build).
 */
import { Crepe } from '@milkdown/crepe';
import { editorViewCtx, parserCtx, schemaCtx, serializerCtx } from '@milkdown/kit/core';
import { TextSelection } from '@milkdown/kit/prose/state';
import { Slice } from '@milkdown/kit/prose/model';
import { toggleMark, setBlockType, wrapIn } from '@milkdown/kit/prose/commands';

import '@milkdown/crepe/theme/common/style.css';
import '@milkdown/crepe/theme/frame.css';
import '@milkdown/crepe/theme/frame-dark.css';

const handles = new WeakMap();

/* Crepe registers its own keymaps but not every commonmark `$Command` slice,
   so the toolbar drives ProseMirror directly through the live schema. This is
   the same mechanism the editor's own keybindings use, and it keeps working
   regardless of which plugins a feature happened to load. */
const commands = {
  toggleStrong: () => runWithView((state, dispatch, view) => {
    const mark = state.schema.marks.strong;
    return mark ? toggleMark(mark)(state, dispatch, view) : false;
  }),
  toggleEmphasis: () => runWithView((state, dispatch, view) => {
    const mark = state.schema.marks.emphasis;
    return mark ? toggleMark(mark)(state, dispatch, view) : false;
  }),
  toggleInlineCode: () => runWithView((state, dispatch, view) => {
    const mark = state.schema.marks.inlineCode || state.schema.marks.code;
    return mark ? toggleMark(mark)(state, dispatch, view) : false;
  }),
  toggleStrikethrough: () => runWithView((state, dispatch, view) => {
    const mark = state.schema.marks.strike_through || state.schema.marks.strikethrough;
    return mark ? toggleMark(mark)(state, dispatch, view) : false;
  }),
  wrapInBlockquote: () => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.blockquote;
    return type ? wrapIn(type)(state, dispatch, view) : false;
  }),
  wrapInBulletList: () => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.bullet_list || state.schema.nodes.bulletList;
    return type ? wrapIn(type)(state, dispatch, view) : false;
  }),
  wrapInOrderedList: () => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.ordered_list || state.schema.nodes.orderedList;
    return type ? wrapIn(type)(state, dispatch, view) : false;
  }),
  createCodeBlock: () => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.code_block || state.schema.nodes.codeBlock;
    return type ? setBlockType(type)(state, dispatch, view) : false;
  }),
  insertHr: () => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.hr;
    if (!type) return false;
    const { from } = state.selection;
    dispatch(state.tr.replaceSelectionWith(type.create()).scrollIntoView());
    return true;
  }),
  setHeading: (level) => runWithView((state, dispatch, view) => {
    const type = state.schema.nodes.heading;
    if (!type) return false;
    return setBlockType(type, { level })(state, dispatch, view);
  }),
};

// ProseMirror commands are not `$Command` slices, so the active view is read
// from the editor context at call time. Each editor keeps its own getter; a
// module-level one would be hijacked as soon as a second editor is created.
const viewGetters = new WeakMap();

function runWithView(fn) {
  return () => {
    const getter = currentViewGetter;
    if (!getter) return false;
    let ran = false;
    getter((view) => {
      ran = fn(view.state, view.dispatch, view);
    });
    return ran;
  };
}

// The editor that most recently received focus owns toolbar commands.
let currentViewGetter = null;

function setActiveView(getter) {
  currentViewGetter = getter;
}


/**
 * Create a rich-text editor inside `container`.
 *
 * options:
 *   initialValue - markdown to load
 *   onChange     - called with the current markdown after every edit
 */
async function createRichEditor(container, options = {}) {
  const { initialValue = '', onChange } = options;

  // One editor per container; a second would duplicate the DOM and leave the
  // toolbar pointed at a stale instance.
  const existing = handles.get(container);
  if (existing) return existing;

  const crepe = new Crepe({
    root: container,
    defaultValue: initialValue,
    features: {
      [Crepe.Feature.BlockEdit]: true,
      [Crepe.Feature.Toolbar]: true,
      [Crepe.Feature.Cursor]: true,
      [Crepe.Feature.ListItem]: true,
      [Crepe.Feature.LinkTooltip]: true,
      [Crepe.Feature.ImageBlock]: true,
      [Crepe.Feature.CodeMirror]: true,
      [Crepe.Feature.Table]: true,
      [Crepe.Feature.Placeholder]: false,
      [Crepe.Feature.AI]: false,
      // Math pulls in KaTeX (fonts + ~1MB of CSS) which this editor's
      // Markdown dialect does not support anyway.
      [Crepe.Feature.Latex]: false,
    },
  });

  await crepe.create();

  // Expose this editor's live view; toolbar commands target whoever is last
  // focused, so multiple instances cannot steal each other's commands.
  const viewGetter = (fn) => {
    fn(crepe.editor.ctx.get(editorViewCtx));
  };
  setActiveView(viewGetter);
  container.addEventListener("focusin", () => setActiveView(viewGetter));

  if (typeof onChange === 'function') {
    crepe.on((listener) => {
      listener.markdownUpdated((_ctx, markdown) => onChange(markdown));
    });
  }

  const handle = {
    container,
    lastError: null,
    // Serialize the live document rather than reading Crepe's cached markdown:
    // the cache only refreshes on its own listener, so a programmatic set could
    // leave it stale.
    getMarkdown() {
      try {
        const view = crepe.editor.ctx.get(editorViewCtx);
        const serialize = crepe.editor.ctx.get(serializerCtx);
        return serialize(view.state.doc);
      } catch (err) {
        return crepe.getMarkdown();
      }
    },
    setMarkdown(markdown) {
      // Re-parse into the live schema and replace the whole document. Throwing
      // here would be swallowed by the caller's guard, so failures are reported
      // through the return value and logged for diagnosis.
      let view;
      let parse;
      try {
        view = crepe.editor.ctx.get(editorViewCtx);
        parse = crepe.editor.ctx.get(parserCtx);
      } catch (err) {
        console.error('[rich-editor] editor context not ready:', err);
        return false;
      }
      if (!view || typeof parse !== 'function') {
        console.error('[rich-editor] parser unavailable');
        return false;
      }
      let doc;
      try {
        doc = parse(markdown);
      } catch (err) {
        console.error('[rich-editor] markdown parse failed:', err);
        return false;
      }
      if (!doc) return false;
      const tr = view.state.tr
        .replace(0, view.state.doc.content.size, Slice.maxOpen(doc.content))
        .setMeta('addToHistory', false);
      view.dispatch(tr);
      // Place the caret at the start *after* the replacement has been applied,
      // otherwise the selection would point outside the new document.
      const start = TextSelection.atStart(view.state.doc);
      view.dispatch(view.state.tr.setSelection(start).setMeta('addToHistory', false));
      return true;
    },
    // Keep independent selections and undo stacks for each document without
    // mounting a full Crepe instance per tab.
    //
    // The returned state must be a *snapshot*. All tabs share this one view, so
    // handing back the live `view.state` would make every tab alias the same
    // object and reopen at whatever caret the previous tab left behind.
    captureState() {
      const view = crepe.editor.ctx.get(editorViewCtx);
      const { state } = view;
      return state.constructor.create({
        schema: state.schema,
        doc: state.doc,
        plugins: state.plugins,
        selection: state.selection,
        storedMarks: state.storedMarks,
      });
    },
    // A restored state must keep THIS view's plugins: the stored state carries
    // the plugin instances it was captured with, which are the same ones here
    // because every tab shares this single Crepe instance.
    restoreState(savedState, markdown) {
      const view = crepe.editor.ctx.get(editorViewCtx);
      setActiveView(viewGetter);
      if (savedState) {
        view.updateState(savedState);
        // `updateState` swaps the ProseMirror state but leaves the DOM
        // selection untouched, so the caret the user left in this tab only
        // becomes real once the view re-reads it from the new state.
        if (typeof view.focus === 'function') view.focus();
        return true;
      }
      // No stored state (first visit to a tab): rebuild from the markdown so
      // the document at least matches the tab, exactly like setMarkdown does.
      const parse = crepe.editor.ctx.get(parserCtx);
      let doc;
      try {
        doc = parse(markdown);
      } catch (err) {
        console.error('[rich-editor] restore parse failed:', err);
        return false;
      }
      if (!doc) return false;
      view.updateState(view.state.constructor.create({
        schema: view.state.schema,
        doc,
        plugins: view.state.plugins,
      }));
      return true;
    },
    /** Run a command factory produced by `commands`. */
    run(action) {
      return action();
    },
    /** Resolve a slice by name; used to verify a command exists. */
    resolve(name) {
      return crepe.editor.ctx.get(name);
    },
    focus() {
      crepe.editor.ctx.get(editorViewCtx).focus();
    },
    setReadonly(value) {
      crepe.setReadonly(value);
    },
    destroy: () => crepe.destroy(),
  };

  handles.set(container, handle);
  return handle;
}

function getHandle(container) {
  return handles.get(container) || null;
}

window.MDEditorRich = { createRichEditor, getHandle, commands };
