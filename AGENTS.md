# AGENTS.md

Panduan untuk semua agent AI dan kontributor di repo ini.

## Proyek

MD Editor: aplikasi desktop Windows untuk mengedit file Markdown.

- `app.py`: backend Python (pywebview + server HTTP lokal), dibungkus jadi `.exe` dengan PyInstaller.
- `index.html`, `script.js`, `style.css`: tampilan dan logika editor (multi tab).
- `rich-editor.js`, `rich-editor.css`: bundle Milkdown untuk preview yang bisa diedit. File hasil generate, sengaja di-commit. Cara membuat ulang ada di `vendor/README.md`.
- `test_*.py`: test end-to-end.

## Build

```powershell
python -m PyInstaller "MD Editor.spec" --noconfirm --clean
```

Hasil ada di `dist/MD Editor/`. Tutup `MD Editor.exe` yang sedang berjalan sebelum build, karena file-nya terkunci.

## Wajib: commit dan push

Setiap pekerjaan **wajib di-commit dan di-push** ke `origin` sebelum dianggap selesai.

- Jangan menyudahi sesi dengan perubahan yang masih lokal atau belum di-commit.
- Commit kecil dengan pesan yang jelas.
- Pastikan `git status` bersih dan `main` sama dengan `origin/main` di akhir pekerjaan.
- Alasannya: pekerjaan pernah hilang karena kodenya hanya ada di satu laptop.
