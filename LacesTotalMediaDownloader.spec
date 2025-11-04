# -*- mode: python ; coding: utf-8 -*-

# Import main to get version number
import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from main import VideoDownloaderApp

# Get version number from main.py
VERSION = VideoDownloaderApp.CURRENT_VERSION

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('ffmpeg.exe', '.'),
        ('ffplay.exe', '.'),
        ('ffprobe.exe', '.'),
    ],
    datas=[
        ('assets', 'assets'),
    ],
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
        'PIL._tkinter_finder',
    ],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'LacesTotalMediaDownloader_v{VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
