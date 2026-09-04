# Lace's Total Media Downloader

A friendly desktop app for downloading video and audio from hundreds of sites,
built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) with a customtkinter UI.

- Video up to 8K (`mp4`, `mkv`, `webm`, `avi`, `mov`, `flv`) or audio-only
  (`mp3`, `m4a`, `opus`, `ogg`, `wav`, `flac`, `aac`)
- Playlists — grab a single item or the whole thing
- **Self-updating download engine.** Sites break extractors constantly, so the
  app pulls the current yt-dlp *nightly* on every launch. That's what keeps
  downloads working without you reinstalling anything.
- YouTube sign-in by reading cookies live from a browser you're already logged
  into, for age-restricted and members-only videos. No cookies are stored.
- GPU-accelerated transcoding when a usable encoder is present, CPU otherwise
- Bundled ffmpeg, so merging and conversion work out of the box

## Installing

Grab the release asset for your platform:

| Platform | Asset | Notes |
|----------|-------|-------|
| Windows | `LacesTotalMediaDownloader_v<VERSION>.exe` | Run it. |
| Linux | `LacesTotalMediaDownloader_v<VERSION>_linux` | `chmod +x` it and run it. |

Both are single self-contained files — no Python, no ffmpeg, nothing else to
install. The app updates itself in place from GitHub releases and only ever
offers you the build for the platform you're on.

On Linux, to get it into your application menu with a proper icon:

```bash
./install-linux.sh /path/to/LacesTotalMediaDownloader_v3.8.0_linux
```

## Where it keeps things

| | Windows | Linux |
|---|---|---|
| Settings | `~/.lace_downloader_config.json` | `~/.lace_downloader_config.json` |
| Downloaded engines (yt-dlp, Deno) | `%LOCALAPPDATA%\LacesTotalMediaDownloader\bin` | `~/.local/share/laces-total-media-downloader/bin` |

Both are per-user and always writable, so the app works fine installed somewhere
read-only.

## Building

Requires Python 3.11+ and PyInstaller. The same
`LacesTotalMediaDownloader.spec` builds both platforms and branches on the OS
internally; each has to be built on its own OS, since PyInstaller can't
cross-compile.

**Windows** — `ffmpeg.exe` and `ffprobe.exe` are committed to the repo, so:

```bash
pip install -r requirements.txt pyinstaller
pip install -U --pre "yt-dlp[default]"
pyinstaller --noconfirm --clean LacesTotalMediaDownloader.spec
```

**Linux** — to produce the file you actually ship:

```bash
packaging/release-linux.sh      # needs docker
```

That builds inside an Ubuntu 22.04 container and writes both the binary and an
upload-ready `.tar.gz` to `dist/`. Building it with your own Python instead
gives you something that won't start on any distro older than yours.

For building locally to test a change, and for the two traps that produce a
build which starts fine and looks broken, see **[BUILD_LINUX.md](BUILD_LINUX.md)**.

## Requirements (running from source)

```bash
pip install -r requirements.txt
python main.py
```

`ffmpeg` needs to be on your PATH, or sitting next to `main.py`. Without it the
app still runs but can only fetch single-format files — no merging, no
conversion to mp3.
