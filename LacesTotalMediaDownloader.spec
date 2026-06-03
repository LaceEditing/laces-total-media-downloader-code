# -*- mode: python ; coding: utf-8 -*-
#
# Windows ONEFILE build spec for Lace's Total Media Downloader.
# Build with:   pyinstaller LacesTotalMediaDownloader.spec
# Produces a single self-contained dist\LacesTotalMediaDownloader_v<VERSION>.exe
#
import os
import re
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Read CURRENT_VERSION straight from main.py without importing it (avoids pulling
# in customtkinter / tk just to read one constant at build time).
with open('main.py', 'r', encoding='utf-8') as _f:
    _m = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)["\']', _f.read())
VERSION = _m.group(1) if _m else '0.0.0'

block_cipher = None

# Bundle ffmpeg + ffprobe (ffprobe is used by yt-dlp for media probing).
# ffplay is intentionally NOT bundled — nothing in the app uses it (~98 MB saved).
binaries = [
    ('ffmpeg.exe', '.'),
    ('ffprobe.exe', '.'),
]

# App assets + customtkinter's themes/fonts (the hooks-contrib hook normally
# collects these, but bundling them explicitly keeps the build working even
# without that hook installed).
datas = [('assets', 'assets')]
datas += collect_data_files('customtkinter')
datas += collect_data_files('yt_dlp_ejs')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'customtkinter',
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ONEFILE: passing a.binaries + a.datas into EXE() (with no COLLECT step) bundles
# everything into a single .exe that self-extracts to a temp dir at launch.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'LacesTotalMediaDownloader_v{VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX on the ~200 MB ffmpeg payload is slow and trips antivirus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/icon.ico',
)
