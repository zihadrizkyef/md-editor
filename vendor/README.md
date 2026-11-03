# Rich editor bundle

`rich-editor.js` and `rich-editor.css` in the project root are generated
artifacts: a bundle of [Milkdown Crepe](https://milkdown.dev), the rich-text
editor that makes the preview pane editable.

They are committed so the app stays buildable and runnable without a JS
toolchain, and so PyInstaller can pick them up from `MD Editor.spec`.

## Rebuilding

Only needed after changing `vendor/entry.js` or upgrading Milkdown.

```powershell
cd vendor
npm install            # once, restores node_modules
npx esbuild entry.js --bundle --format=iife --outfile=rich-editor.js `
  --loader:.ttf=empty --loader:.woff=empty --loader:.woff2=empty `
  --loader:.eot=empty --loader:.svg=empty --minify
Move-Item rich-editor.js, rich-editor.css .. -Force
```

The `empty` font loaders keep KaTeX's fonts out of the bundle; the math feature
is disabled because this editor's Markdown dialect does not use it.

After rebuilding, run the checks in the project root:

```powershell
python test_rich_preview.py    # source tree, headless Edge
python test_packaged_exe.py    # the built exe, after launching it
```
