# Building the Linux version (PyInstaller onefile)

This produces a single self-contained executable, the same way the Windows build
works — no Flatpak, no system Python dependencies for end users. It must be built
**on Linux** (PyInstaller doesn't cross-compile). Build on the oldest Linux you
want to support (glibc is forward-compatible, not backward), e.g. Ubuntu 22.04.

> The same `LacesTotalMediaDownloader.spec` is used on both Windows and Linux — it
> branches on the OS internally.

## 1. System packages (the important one is tkinter)

The whole UI is customtkinter → **tkinter**, which is part of Python itself and is
*not* pulled in by pip. Your build Python must have it:

```bash
# Debian / Ubuntu
sudo apt install python3-tk python3-venv python3-dev

# Fedora
sudo dnf install python3-tkinter python3-devel

# Arch / CachyOS
sudo pacman -S tk
```

Use **Python 3.11 or 3.12** (3.13 is fine too). Avoid 3.14 — pygame has no wheel
for it yet, exactly like on Windows.

## 2. Project environment

```bash
cd laces-total-media-downloader-code
python3 -m venv .venv-linux
source .venv-linux/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

# sanity check tkinter is present in THIS interpreter:
python -c "import tkinter, customtkinter; print('tkinter OK')"
```

## 3. Drop in static ffmpeg + ffprobe

The spec bundles `ffmpeg` and `ffprobe` if they sit next to it (they're
git-ignored so they don't bloat the repo). Grab the static GPL build (includes
libx264 / libx265 / aac, and NVENC/VAAPI when the user's drivers are present):

```bash
curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz
tar xf ffmpeg.tar.xz
cp ffmpeg-*-amd64-static/ffmpeg  ./ffmpeg
cp ffmpeg-*-amd64-static/ffprobe ./ffprobe
chmod +x ffmpeg ffprobe
rm -rf ffmpeg.tar.xz ffmpeg-*-amd64-static
```

(If you skip this, the build still succeeds and the app falls back to the
system `ffmpeg` on PATH — but bundling makes it self-contained.)

## 4. Build

```bash
pyinstaller --noconfirm --clean LacesTotalMediaDownloader.spec
```

Output: `dist/LacesTotalMediaDownloader_v<VERSION>` (an ELF binary, no extension).

## 5. Run

```bash
chmod +x dist/LacesTotalMediaDownloader_v*
./dist/LacesTotalMediaDownloader_v*
```

Run it from a **writable folder** (e.g. your home / Downloads). On first use the
app downloads Deno into its own folder for YouTube's JS challenge — same as
Windows — so it needs to be able to write next to itself.

## Notes / gotchas

- **Deno:** auto-downloaded at runtime (`ensure_js_runtime()` picks the Linux
  build) only if no `deno`/`node` is already on PATH. Nothing to bundle.
- **GPU transcoding:** the static ffmpeg supports NVENC/VAAPI, but the startup
  probe currently only tests `*_nvenc`/`*_qsv`/`*_amf`. On NVIDIA boxes NVENC may
  work; otherwise it falls back to CPU (libx264/libx265). VAAPI isn't wired up yet.
- **Portability:** build on an old glibc (22.04). A binary built on a newer distro
  may not start on older ones.
- **Optional desktop entry:** to get an app-menu launcher, install a `.desktop`
  pointing `Exec=` at the binary and `Icon=` at `assets/icons/icon.png`.
- **Flatpak:** the `flatpak/` manifest is currently non-functional for this app
  (the freedesktop runtime ships no tkinter); this PyInstaller path is the
  supported Linux build.
