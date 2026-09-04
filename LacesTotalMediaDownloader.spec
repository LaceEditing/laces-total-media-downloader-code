# -*- mode: python ; coding: utf-8 -*-
#
# Cross-platform ONEFILE build spec for Lace's Total Media Downloader.
# Build with:   pyinstaller LacesTotalMediaDownloader.spec
#   Windows -> dist/LacesTotalMediaDownloader_v<VERSION>.exe
#   Linux   -> dist/LacesTotalMediaDownloader_v<VERSION>_linux  (ELF, no extension)
#
# Linux build prerequisites (see BUILD_LINUX.md): a tkinter-enabled Python
# (apt install python3-tk), the deps from requirements.txt + pyinstaller, and
# the static `ffmpeg`/`ffprobe` Linux binaries dropped next to this spec.
#
import os
import re
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

IS_WIN = sys.platform == 'win32'

# Read CURRENT_VERSION straight from main.py without importing it (avoids pulling
# in customtkinter / tk just to read one constant at build time).
with open('main.py', 'r', encoding='utf-8') as _f:
    _m = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']', _f.read())
VERSION = _m.group(1) if _m else '0.0.0'

block_cipher = None

# Bundle ffmpeg + ffprobe (ffprobe is used by yt-dlp for media probing).
# ffplay is intentionally NOT bundled — nothing in the app uses it.
#
# Deno (the JavaScript engine yt-dlp uses to solve YouTube's n-challenge) is NOT
# bundled — the app downloads it on first run (see ensure_js_runtime() in main.py)
# only when no runtime is already available. That keeps the build small and means
# it never fails for a missing deno binary.
if IS_WIN:
    # Windows static binaries live in the repo root (committed).
    binaries = [
        ('ffmpeg.exe', '.'),
        ('ffprobe.exe', '.'),
    ]
else:
    # Linux/macOS: bundle the static `ffmpeg`/`ffprobe` if they've been placed
    # next to this spec (see BUILD_LINUX.md). If they're absent, the build still
    # succeeds and the app falls back to the system ffmpeg on PATH at runtime.
    binaries = [(_b, '.') for _b in ('ffmpeg', 'ffprobe') if os.path.exists(_b)]

# App assets + customtkinter's themes/fonts (the hooks-contrib hook normally
# collects these, but bundling them explicitly keeps the build working even
# without that hook installed).
datas = [('assets', 'assets')]
datas += collect_data_files('customtkinter')
datas += collect_data_files('yt_dlp_ejs')

# NOTE: whatever yt-dlp is in the build venv gets frozen in permanently. The app
# auto-updates its engine from the nightly channel at runtime, but this copy is
# still the fallback (dev runs, Flatpak, and the moments before the first update
# lands), so refresh it right before building:
#     pip install -U --pre "yt-dlp[default]"

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'customtkinter',
        # NB: these stay 'pygame' even though requirements.txt installs pygame-ce
        # -- the fork provides the `pygame` module, so the import names are right.
        'pygame',
        'pygame.mixer',
        'requests',
        'packaging',
        'packaging.version',
        'packaging.specifiers',
        'packaging.requirements',
        'yt_dlp',
        'yt_dlp_ejs',
        'PIL._tkinter_finder',
    ] + collect_submodules('yt_dlp') + collect_submodules('yt_dlp_ejs'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

if not IS_WIN:
    # Never ship the BUILD machine's font stack. fontconfig reads the *host's*
    # /etc/fonts at runtime, so a copy from an older build container fails to
    # parse a newer distro's config and quietly loses font fallback -- which on
    # a current Arch host emptied the toolbar button of its glyph. Every desktop
    # Linux already has these, and the system copy always matches its own config.
    #
    # Only the bare sonames are dropped: pygame ships a privately-versioned
    # libfreetype-<hash>.so that only it loads, and that one has to stay.
    _use_system = ('libfontconfig.so', 'libfreetype.so')
    a.binaries = [entry for entry in a.binaries
                  if not os.path.basename(entry[0]).startswith(_use_system)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ONEFILE: passing a.binaries + a.datas into EXE() (with no COLLECT step) bundles
# everything into a single executable that self-extracts to a temp dir at launch.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    # The '_linux' suffix is load-bearing: the in-app updater picks a release
    # asset by name, and only takes a Linux one that says so
    # (see _platform_release_asset in main.py).
    name=f'LacesTotalMediaDownloader_v{VERSION}'
         + ('' if IS_WIN else '_linux'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX on the big ffmpeg payload is slow and trips antivirus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # PyInstaller only embeds an icon into the Windows PE; on Linux the window
    # icon is set at runtime from assets/icons/icon.png (see set_icon()).
    icon='assets/icons/icon.ico' if IS_WIN else None,
)
