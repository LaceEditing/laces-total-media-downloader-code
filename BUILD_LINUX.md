# Building the Linux version

This produces a single self-contained executable, the same way the Windows build
does — one file, no system Python, no runtime dependencies for end users. It must
be built **on Linux** (PyInstaller doesn't cross-compile).

**If you just want the file to hand to other people, skip to section 4** —
`packaging/release-linux.sh` does the whole thing in one command. Sections 1-3
are for building on your own machine.

> The same `LacesTotalMediaDownloader.spec` is used on Windows and Linux — it
> branches on the OS internally.

## 1. System packages — read this part, it's the one that bites

The whole UI is customtkinter → **tkinter**, which is part of Python itself and
is *not* installed by pip. Your build Python needs it:

```bash
# Debian / Ubuntu
sudo apt install python3-tk python3-venv python3-dev

# Fedora
sudo dnf install python3-tkinter python3-devel

# Arch / CachyOS / Garuda
sudo pacman -S tk
```

**Use your distro's Python.** Do *not* build with a Python from `uv python
install`, `pyenv`, `conda`, or any other python-build-standalone distribution.
Those ship their own Tcl/Tk compiled **without Xft/fontconfig**, which is not a
theoretical problem — the app builds and starts fine, and then:

- `tkinter.font.families()` returns exactly one family, `fixed`
- every custom font silently falls back to an X11 bitmap font
- CustomTkinter's shapes font can't load, so dropdown arrows render as a
  literal letter `Y` and radio buttons render as loose corner marks

None of that shows up as an error anywhere. Check the interpreter you're about
to build with:

```bash
python3 -c "import tkinter, tkinter.font as f; r=tkinter.Tk(); print(len(f.families()), 'font families')"
```

A real Tk reports a few hundred. If it reports `1`, that Python will produce a
broken-looking build — install your distro's tk and use the system interpreter.

Any Python from **3.11 onwards** works, 3.14 included — `pygame-ce` publishes
cp314 wheels (upstream `pygame` does not, which is exactly why `requirements.txt`
asks for the fork).

## 2. Project environment

```bash
cd laces-total-media-downloader-code
python3 -m venv .venv-linux
source .venv-linux/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

# Freeze a CURRENT yt-dlp into the build. The app auto-updates its engine at
# runtime, but this copy is the fallback used in dev and in the moments before
# the first update lands -- so it should not be months old. `--pre` selects the
# nightly channel, matching what the app downloads at runtime.
pip install -U --pre "yt-dlp[default]"

# sanity check, per section 1:
python -c "import tkinter, tkinter.font as f, customtkinter; r=tkinter.Tk(); print(len(f.families()), 'font families')"
```

If your distro's `python3-venv` refuses to give you pip (some do), `uv venv
--python /usr/bin/python3` works too — the thing that matters is that the
*interpreter* is the distro one, not where the venv came from.

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

If you skip this the build still succeeds and the app falls back to the system
`ffmpeg` on PATH — but bundling is what makes it self-contained. It costs about
55 MB of final binary (~48 MB without, ~104 MB with).

## 4. Build

Two different jobs here — pick the right one.

### Building a release for other people

```bash
packaging/release-linux.sh
```

Needs docker. It compiles inside an Ubuntu 22.04 container and writes both the
binary and the upload-ready tarball into `dist/`. Sections 1 and 2 don't apply
to this path — the container brings its own Python and tk.

**Build a release this way, not with your own Python.** glibc is forward
compatible only, so a binary linked against a current Arch/Fedora glibc will not
start on anything older, and "anything older" is most machines you'd ship to. A
build made on Arch here demanded glibc 2.44; the container build demands 2.35,
which covers Ubuntu 22.04+, Debian 12+, Fedora 36+ and everything since.

### Building for yourself, to test a change

```bash
pyinstaller --noconfirm --clean LacesTotalMediaDownloader.spec
```

Faster, no docker, and fine for a machine you're sitting at — it just won't run
anywhere older than the one that built it.

Output: `dist/LacesTotalMediaDownloader_v<VERSION>_linux` (an ELF binary, no
extension).

> The `_linux` suffix is load-bearing. The in-app updater picks a GitHub release
> asset by name and only accepts a Linux one that says `linux`, so it can never
> hand a Linux user the Windows `.exe`. Keep the suffix when you upload the
> release asset.

## 5. Run

```bash
chmod +x dist/LacesTotalMediaDownloader_v*_linux
./dist/LacesTotalMediaDownloader_v*_linux
```

## 6. Install it into the desktop (optional)

`install-linux.sh` works both from a built repo and from an unpacked release
tarball.

```bash
./install-linux.sh                 # picks the newest dist/*_linux build
./install-linux.sh --uninstall     # removes it again
```

That drops the binary in `~/.local/bin`, installs the icon, and writes a
`.desktop` entry so the app shows up in the application menu with its own name
and icon. Nothing goes outside `$HOME` and it never asks for root.

## Notes / gotchas

- **Where it writes:** config at `~/.lace_downloader_config.json`, downloaded
  engines (yt-dlp, Deno) under `~/.local/share/laces-total-media-downloader/`,
  fonts copied into `~/.fonts`. The binary itself can live anywhere, including a
  read-only location.
- **Fonts:** on startup the app copies its own fonts plus CustomTkinter's into
  `~/.fonts` and runs `fc-cache` *before* creating the Tk window. That ordering
  matters; without it the first run comes up with the wrong glyphs.
- **Window size:** Linux opens at `VideoDownloaderApp.LINUX_WINDOW_SIZE`
  (1430x1063) rather than the Windows 950x700, because X11 lays this layout out
  considerably wider. It's a floor — a system with wider fonts gets fitted up
  automatically rather than cropped.
- **Deno:** auto-downloaded at runtime for YouTube's JS challenge, and only if
  no `deno`/`node` is already on PATH. Nothing to bundle.
- **GPU transcoding:** the static ffmpeg supports NVENC/VAAPI, but the startup
  probe only tests `*_nvenc`/`*_qsv`/`*_amf`. On NVIDIA boxes NVENC may work;
  otherwise it falls back to CPU (libx264/libx265). VAAPI isn't wired up yet.
- **Portability:** see section 4 — this is what `packaging/release-linux.sh`
  exists for.
- **The build machine's font stack is deliberately not bundled.** The spec drops
  `libfontconfig.so` and `libfreetype.so` from the Linux bundle, because
  fontconfig reads the *host's* `/etc/fonts` at runtime and an older bundled copy
  fails to parse a newer distro's config — which silently costs you font
  fallback. pygame's privately-versioned `libfreetype-<hash>.so` is kept.
- **No emoji in the UI on Linux.** The refresh button's glyph is U+21BB, not
  U+1F504: the emoji lives only in Noto Color Emoji, a colour bitmap font that
  older X font stacks can't draw, and the button rendered empty. See
  `VideoDownloaderApp.REFRESH_GLYPH`.
- **Flatpak:** not supported, and the manifest that used to live in `flatpak/`
  has been removed. `org.freedesktop.Platform` ships no tkinter, so a working
  Flatpak would have to build Tcl, Tk and a whole CPython inside the sandbox —
  and the sandbox also blocks the runtime yt-dlp updates that keep downloads
  working. This PyInstaller build is the supported Linux path.
