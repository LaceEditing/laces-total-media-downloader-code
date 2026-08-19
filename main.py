import os
import sys
import shutil
import subprocess

# On Linux, pre-install custom fonts AND ensure ~/.fonts exists before
# CustomTkinter is imported. CTk will also copy its shapes font + Roboto
# into ~/.fonts during import.  After that we run fc-cache so fontconfig
# (and therefore Tk) can actually find every font before the Tk root window
# is created.  Without this, the shapes font silently fails and widgets
# render "Y" instead of dropdown arrows, wrong radio-button glyphs, and
# rough/jagged rounded corners.
if sys.platform.startswith('linux'):
    _fonts_dir = os.path.expanduser('~/.fonts')
    os.makedirs(_fonts_dir, exist_ok=True)
    # Pre-copy the app's own fonts so they are indexed together with CTk's
    _base = os.path.dirname(os.path.abspath(__file__))
    for _fname in ('BubblegumSans-Regular.ttf', 'Bartino.ttf'):
        _src = os.path.join(_base, 'assets', 'fonts', _fname)
        _dst = os.path.join(_fonts_dir, _fname)
        if os.path.exists(_src) and not os.path.exists(_dst):
            try:
                shutil.copy(_src, _dst)
            except OSError:
                pass

import customtkinter as ctk

# Rebuild fontconfig cache AFTER CTk copied its fonts to ~/.fonts but
# BEFORE any Tk root window is created (that happens in ctk.CTk.__init__).
if sys.platform.startswith('linux'):
    try:
        subprocess.run(
            ['fc-cache', '-f', os.path.expanduser('~/.fonts')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
    except Exception:
        pass

from tkinter import filedialog, messagebox
import yt_dlp
import threading
from pathlib import Path
import re
import json
from pygame import mixer
import requests
from packaging import version
import tempfile
import webbrowser


class VideoDownloaderApp(ctk.CTk):
    # Version of the app - update this with each release
    CURRENT_VERSION = "3.8.0"
    # GitHub repository for updates
    GITHUB_REPO = "LaceEditing/laces-total-media-downloader"

    # yt-dlp download engine: track the NIGHTLY channel, not stable.
    # Sites (YouTube/TikTok/...) change things on their end constantly; extractor
    # fixes land in nightly within hours, but only reach `stable` at the next cut,
    # which can be 6+ weeks later. yt-dlp's own README calls stable "often stale
    # and prone to external breakage" and recommends nightly for regular users.
    # The nightly repo publishes identical asset names, so only the host differs.
    YTDLP_UPDATE_REPO = "yt-dlp/yt-dlp-nightly-builds"
    YTDLP_RELEASE_BASE = f"https://github.com/{YTDLP_UPDATE_REPO}/releases/latest/download/"
    YTDLP_API_LATEST = f"https://api.github.com/repos/{YTDLP_UPDATE_REPO}/releases/latest"

    def __init__(self, CURRENT_VERSION=CURRENT_VERSION):
        super().__init__()

        # Window setup
        self.title(f"Hey besties let's download those files! (v{CURRENT_VERSION})")
        self.geometry("950x700")
        self.minsize(850, 700)

        # Set window icon
        self.set_icon()

        # Initialize pygame mixer for sounds
        try:
            mixer.init()
        except Exception:
            pass

        # Color scheme (dark mode)
        self.colors = {
            'bg': "#1a1625",
            'purple': "#B88ED8",
            'dark_purple': "#9B6BD8",
            'pink': "#D891E8",
            'button': "#7d5ba6",
            'frame_bg': "#2d2438",
            'text': "#E8E4F3"
        }

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.configure(fg_color=self.colors['bg'])

        # Variables
        self.download_type = ctk.StringVar(value="video")
        self.quality = ctk.StringVar(value="1080p")
        self.audio_quality = ctk.StringVar(value="320")
        self.video_format = ctk.StringVar(value="mp4")
        self.audio_format = ctk.StringVar(value="mp3")
        self.output_folder = ctk.StringVar(value=str(Path.home() / "Downloads"))
        self.is_downloading = False
        self.ffmpeg_available = self.check_ffmpeg()
        self.downloaded_file_path = None

        # Load persisted config (recent folders, high-res notice prefs)
        cfg = self.load_config()
        self.recent_folders = cfg.get('recent_folders', [])
        self.hires_codec_default = cfg.get('hires_codec_default', 'auto')  # auto|h264|hevc
        self.ask_hires_codec = cfg.get('ask_hires_codec', True)
        self.prefer_gpu = True

        # Sign-in source is session-only. Browser cookies are read live by yt-dlp
        # for YouTube auth; the app does not persist/export them.
        self.cookies_source = 'none'   # 'none' | browser name | 'file'
        self.cookies_file = ''
        self._signin_dialog = None     # the open sign-in popup, if any
        self._delete_legacy_cookiefile()

        self._recent_display_to_path = {}  # Populated by update_recent_dropdown
        self.ytdlp_exe_path = None  # Will be set if yt-dlp.exe is downloaded
        # Set once the engine is usable (fresh, already-current, or update failed
        # and we're falling back). Downloads wait on this so a click during the
        # startup update can't silently run on the stale built-in copy.
        self._engine_ready = threading.Event()
        # Set after a YouTube sign-in/age wall so the retry widens player_client.
        self._widen_player_clients = False
        self.hw_encoders = {}  # Populated by _detect_hw_encoders: {'h264': enc, 'hevc': enc}

        # Load custom fonts
        self.load_custom_fonts()

        self.setup_ui()

        # Show ffmpeg warning if not available
        if not self.ffmpeg_available:
            self.after(500, self.show_ffmpeg_warning)

        # Probe usable GPU encoders in the background so high-res transcodes are fast
        if self.ffmpeg_available:
            self.after(200, self._detect_hw_encoders)

        # Update yt-dlp on startup to prevent HTTP 403 errors
        self.after(100, self.update_ytdlp)

        # Ensure a JavaScript runtime (Deno) exists for YouTube's n-challenge;
        # downloads one only if none is available.
        self.after(300, self.ensure_js_runtime)

        # Check for updates on startup
        self.after(1000, self.check_for_updates)

    def destroy(self):
        """Clean up resources before closing."""
        try:
            mixer.quit()
        except Exception:
            pass
        super().destroy()



    def _get_icon_paths(self):
        """Return app icon paths from the bundled assets directory."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(base_path, 'assets', 'icons')
        return {
            'png': os.path.join(icon_dir, 'icon.png'),
            'ico': os.path.join(icon_dir, 'icon.ico'),
        }

    def set_icon(self, window=None, prefer_png=False):
        """Set window icon from assets/icons folder."""
        target = window or self
        try:
            paths = self._get_icon_paths()
            png_path = paths['png']
            ico_path = paths['ico']

            # Windows title bars use iconbitmap; iconphoto alone often leaves
            # CTk/Tk toplevels with the default blue Tk icon.
            if os.path.exists(ico_path):
                try:
                    target.iconbitmap(ico_path)
                except Exception:
                    pass
                try:
                    target.iconbitmap(default=ico_path)
                except Exception:
                    pass

            if os.path.exists(png_path):
                try:
                    # For PNG icons, use PhotoImage (works cross-platform)
                    from PIL import Image, ImageTk
                    img = Image.open(png_path)
                    photo = ImageTk.PhotoImage(img)
                    target.iconphoto(True, photo)
                    # Keep a reference to prevent garbage collection
                    if target is self:
                        self._icon_photo = photo
                    else:
                        target._icon_photo = photo
                except Exception:
                    pass
        except Exception:
            # Fallback: try iconbitmap method
            try:
                if getattr(sys, 'frozen', False):
                    base_path = sys._MEIPASS
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))

                icon_path = os.path.join(base_path, 'assets', 'icons', 'icon.png')
                if os.path.exists(icon_path):
                    from PIL import Image, ImageTk
                    img = Image.open(icon_path)
                    photo = ImageTk.PhotoImage(img)
                    target.iconphoto(True, photo)
                    if target is self:
                        self._icon_photo = photo
                    else:
                        target._icon_photo = photo
            except Exception:
                pass

    def set_toplevel_icon(self, dialog):
        """Apply the app icon to a CTkToplevel, including the Windows title bar."""
        self.set_icon(dialog)

        try:
            ico_path = self._get_icon_paths()['ico']
        except Exception:
            ico_path = None
        if not ico_path or not os.path.exists(ico_path):
            return

        def apply_ico():
            try:
                dialog.iconbitmap(ico_path)
            except Exception:
                pass
            try:
                dialog.wm_iconbitmap(ico_path)
            except Exception:
                pass
            try:
                dialog.tk.call('wm', 'iconbitmap', dialog._w, ico_path)
            except Exception:
                pass

        dialog.after_idle(apply_ico)
        dialog.after(100, apply_ico)
        dialog.after(300, apply_ico)

    def load_custom_fonts(self):
        """Load custom fonts from assets/fonts folder"""
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            # Font paths
            self.bubblegum_font_path = os.path.join(base_path, 'assets', 'fonts', 'BubblegumSans-Regular.ttf')
            # Must match the file's real case — Linux filesystems are case-sensitive,
            # so 'bartino.ttf' silently failed to load there and the whole UI fell
            # back to the default font.
            self.bartino_font_path = os.path.join(base_path, 'assets', 'fonts', 'Bartino.ttf')

            # On Linux, copy fonts to ~/.fonts so Tk/fontconfig can find them
            if sys.platform.startswith('linux'):
                linux_font_dir = os.path.expanduser('~/.fonts')
                os.makedirs(linux_font_dir, exist_ok=True)
                for font_file in (self.bubblegum_font_path, self.bartino_font_path):
                    if os.path.exists(font_file):
                        dest = os.path.join(linux_font_dir, os.path.basename(font_file))
                        if not os.path.exists(dest):
                            try:
                                shutil.copy(font_file, dest)
                            except OSError:
                                pass

            # Check if fonts exist
            self.has_bubblegum = os.path.exists(self.bubblegum_font_path)
            self.has_bartino = os.path.exists(self.bartino_font_path)
        except Exception:
            self.has_bubblegum = False
            self.has_bartino = False

    def check_for_updates(self):
        """Check for updates from GitHub releases"""
        # Skip auto-update on Linux (especially in Flatpak/Snap)
        # Linux apps should be updated through their package manager
        if sys.platform.startswith('linux'):
            # Check if running in Flatpak or Snap
            if os.path.exists('/.flatpak-info') or os.environ.get('SNAP'):
                return  # Don't check for updates in containerized environments

        def check():
            try:
                # Check GitHub API for latest release
                api_url = f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest"
                response = requests.get(api_url, timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    latest_version = data['tag_name'].lstrip('v')

                    # Compare versions
                    if version.parse(latest_version) > version.parse(self.CURRENT_VERSION):
                        # Found newer version
                        download_url = None
                        for asset in data.get('assets', []):
                            if asset['name'].endswith('.exe'):
                                download_url = asset['browser_download_url']
                                break

                        if download_url:
                            self.after(0, lambda: self.show_update_dialog(latest_version, download_url,
                                                                          data.get('body', '')))
            except Exception:
                pass  # Silently fail if update check fails

        # Run update check in background thread
        thread = threading.Thread(target=check, daemon=True)
        thread.start()

    def manual_check_for_updates(self):
        """Manually check for updates when user clicks the button"""
        default_status = "Quivering in anticipation...\nSlap that URL up above and smash that download button!"

        def check():
            try:
                # Update the status bar instead of showing a blocking dialog
                self.after(0, lambda: self.update_status("Checking for updates...", append=False))

                # Check GitHub API for latest release
                api_url = f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest"
                response = requests.get(api_url, timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    latest_version = data['tag_name'].lstrip('v')

                    # Compare versions
                    if version.parse(latest_version) > version.parse(self.CURRENT_VERSION):
                        # Found newer version
                        download_url = None
                        for asset in data.get('assets', []):
                            if asset['name'].endswith('.exe'):
                                download_url = asset['browser_download_url']
                                break

                        if download_url:
                            self.after(0, lambda: self.show_update_dialog(latest_version, download_url,
                                                                          data.get('body', '')))
                        else:
                            self.after(0, lambda: messagebox.showinfo(
                                "No Update Available",
                                f"No downloadable update found for version {latest_version}."
                            ))
                    else:
                        # Already on latest version
                        self.after(0, lambda: messagebox.showinfo(
                            "No Updates Available",
                            f"You're already on the latest version ({self.CURRENT_VERSION})!"
                        ))
                elif response.status_code == 404:
                    self.after(0, lambda: messagebox.showinfo(
                        "No Releases Found",
                        "No releases are published yet for this app.\n\n"
                        f"You're running version {self.CURRENT_VERSION}."
                    ))
                else:
                    self.after(0, lambda: messagebox.showerror(
                        "Update Check Failed",
                        f"Failed to check for updates (HTTP {response.status_code}).\nPlease try again later."
                    ))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Update Check Failed",
                    f"Failed to check for updates:\n{str(e)}"
                ))
            finally:
                self.after(0, lambda: self.update_status(default_status, append=False))

        # Run update check in background thread
        thread = threading.Thread(target=check, daemon=True)
        thread.start()

    def _engine_dir(self):
        """Writable per-user directory for downloaded engine binaries.

        These used to be written next to the .exe, which silently fails whenever
        the app lives somewhere unwritable (Program Files, a read-only drive, a
        network share) — leaving it stuck forever on the stale yt-dlp copy frozen
        into the build. A per-user data dir is always writable, and matches where
        the app already keeps its config.
        """
        if sys.platform == 'win32':
            root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
            path = os.path.join(root, 'LacesTotalMediaDownloader', 'bin')
        elif sys.platform == 'darwin':
            path = os.path.expanduser(
                '~/Library/Application Support/LacesTotalMediaDownloader/bin')
        else:
            root = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
            path = os.path.join(root, 'laces-total-media-downloader', 'bin')
        os.makedirs(path, exist_ok=True)
        return path

    def _legacy_engine_dir(self):
        """Where engine binaries used to live (next to the .exe / script).

        Still searched read-only, so a yt-dlp/deno downloaded by an older build
        keeps working after the move. Nothing is ever written here any more.
        """
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _set_engine_label(self, text):
        """Update the header engine readout. Safe to call from any thread."""
        def apply():
            label = getattr(self, 'engine_label', None)
            if label is not None:
                try:
                    label.configure(text=f"engine: {text}")
                except Exception:
                    pass
        self.after(0, apply)

    def _await_engine(self, timeout=45):
        """Block until the startup engine update settles (or times out).

        Safe to call only from a download worker thread -- never the Tk thread.
        Without this, clicking DOWNLOAD during the startup update found
        ytdlp_exe_path still unset and silently fell back to the yt-dlp frozen
        into the build, producing stale-extractor errors (403s, "Unexpected
        response from webpage request") that looked like the site's fault.

        On timeout we proceed anyway rather than blocking forever -- a slow
        download of the engine shouldn't make the app unusable.
        """
        if self._engine_ready.is_set():
            return True
        self.after(0, lambda: self.update_status(
            "Updating download engine, one moment...", append=False))
        ready = self._engine_ready.wait(timeout=timeout)
        if not ready:
            self.after(0, lambda: self.update_status(
                "Download engine is still updating; continuing with the current one.",
                append=False))
        return ready

    def update_ytdlp(self):
        """Keep the yt-dlp download engine current, from the NIGHTLY channel.

        Sites changing things on their end is what breaks downloads, and nightly
        is where those extractor fixes land first. Running this on every launch is
        what keeps downloads working without the user updating anything by hand.
        """
        # Skip in sandboxed Linux environments where we can't write or pip install
        if sys.platform.startswith('linux'):
            if os.path.exists('/.flatpak-info') or os.environ.get('SNAP'):
                # Nothing to download here, so never make downloads wait on us.
                self._set_engine_label(self._library_version_label())
                self._engine_ready.set()
                return

        def update():
            try:
                # Check if we're running as a frozen executable (PyInstaller)
                is_frozen = getattr(sys, 'frozen', False)

                if is_frozen:
                    # For frozen executable, download yt-dlp binary and keep it updated
                    engine_dir = self._engine_dir()

                    # Choose the right STANDALONE binary for the platform. On
                    # Linux/macOS the plain "yt-dlp" asset is a Python zipapp that
                    # needs a system Python — use the self-contained "yt-dlp_linux"
                    # / "yt-dlp_macos" builds so it works on machines without Python.
                    base_url = self.YTDLP_RELEASE_BASE
                    min_size = 1_000_000  # Expect at least ~1MB
                    if sys.platform == 'win32':
                        ytdlp_filename = 'yt-dlp.exe'
                        ytdlp_url = base_url + 'yt-dlp.exe'
                    elif sys.platform == 'darwin':
                        ytdlp_filename = 'yt-dlp'
                        ytdlp_url = base_url + 'yt-dlp_macos'
                    else:
                        import platform as _platform
                        machine = _platform.machine().lower()
                        asset = 'yt-dlp_linux_aarch64' if machine in ('aarch64', 'arm64') else 'yt-dlp_linux'
                        ytdlp_filename = 'yt-dlp'
                        ytdlp_url = base_url + asset

                    ytdlp_exe_path = os.path.join(engine_dir, ytdlp_filename)

                    # Adopt a binary we already have — new location first, then the
                    # legacy next-to-exe spot — and open the download gate straight
                    # away, so only a genuine first run ever has to wait.
                    existing = None
                    for candidate in (ytdlp_exe_path,
                                      os.path.join(self._legacy_engine_dir(), ytdlp_filename)):
                        try:
                            if os.path.exists(candidate) and os.path.getsize(candidate) >= min_size:
                                existing = candidate
                                break
                        except OSError:
                            continue

                    installed = None
                    if existing:
                        self.ytdlp_exe_path = existing
                        self._engine_ready.set()
                        installed = self._get_local_ytdlp_version(existing)

                        # Checked on every launch, deliberately: it's one small
                        # API call, and it's what makes "reopen the app to pick up
                        # the fix" actually true after a site breaks something.
                        latest = self._get_latest_ytdlp_version()
                        if latest is None:
                            # API unreachable or rate-limited (60 req/hr/IP for
                            # anonymous callers). Keep what we have rather than
                            # re-pulling ~30MB on nothing but a failed lookup.
                            self._set_engine_label(f"{installed or 'unknown'} (check failed)")
                            self.after(0, lambda v=installed or 'unknown': self.update_status(
                                f"Download engine ready ({v}); update check unavailable."))
                            return
                        if installed and installed == latest:
                            self._set_engine_label(installed)
                            self.after(0, lambda v=installed: self.update_status(
                                f"Download engine is up to date ({v})."))
                            return

                    # Download to a temp file first, then rename (atomic-ish)
                    temp_path = ytdlp_exe_path + '.tmp'
                    try:
                        self.after(0, lambda: self.update_status(
                            "Updating download engine (yt-dlp nightly)..."))
                        response = requests.get(ytdlp_url, timeout=120)
                        if response.status_code == 200:
                            with open(temp_path, 'wb') as f:
                                f.write(response.content)

                            # Verify the download isn't truncated/corrupt
                            if os.path.getsize(temp_path) < min_size:
                                os.remove(temp_path)
                                raise Exception("Downloaded yt-dlp binary is too small, possibly corrupt")

                            # Replace the real file
                            shutil.move(temp_path, ytdlp_exe_path)

                            # Make executable on Linux/Mac
                            if sys.platform != 'win32':
                                os.chmod(ytdlp_exe_path, 0o755)

                            self.ytdlp_exe_path = ytdlp_exe_path
                            new_version = self._get_local_ytdlp_version(ytdlp_exe_path)
                            self._set_engine_label(new_version or 'updated')
                            self.after(0, lambda v=new_version: self.update_status(
                                f"Download engine updated ({v})!" if v
                                else "Download engine updated!"))
                        else:
                            raise Exception(f"Download failed with status {response.status_code}")
                    finally:
                        # Clean up temp file if it still exists
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except Exception:
                                pass
                else:
                    # Development/unfrozen: refresh the installed library. `--pre`
                    # is what selects nightly on PyPI; without it pip stays on
                    # stable, which is exactly the staleness we're avoiding.
                    python_executable = sys.executable
                    result = subprocess.run(
                        [python_executable, "-m", "pip", "install", "-U", "--pre", "yt-dlp[default]"],
                        capture_output=True,
                        text=True,
                        timeout=180,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    if result.returncode == 0:
                        # yt_dlp is already imported, so a fresh install only takes
                        # effect next launch — say so rather than implying otherwise.
                        self._set_engine_label(self._library_version_label())
                        self.after(0, lambda: self.update_status(
                            "Download engine checked (restart to use a newer version)."))
                    else:
                        tail = (result.stderr or result.stdout or '').strip().splitlines()
                        detail = tail[-1] if tail else f"pip exited {result.returncode}"
                        self.after(0, lambda d=detail: self.update_status(
                            f"Download engine update skipped: {d}"))
            except Exception as e:
                # Keep using an existing local binary if we have one; only clear
                # the path when there's nothing usable to fall back on.
                if not (getattr(self, 'ytdlp_exe_path', None)
                        and os.path.exists(self.ytdlp_exe_path)):
                    self.ytdlp_exe_path = None
                self._set_engine_label(
                    (self._get_local_ytdlp_version(self.ytdlp_exe_path) or 'unknown')
                    if self._have_ytdlp_exe() else self._library_version_label())
                self.after(0, lambda: self.update_status(f"Download engine update failed: {e}"))
            finally:
                # Whatever happened, never leave a download blocked waiting on us.
                self._engine_ready.set()

        # Run update in background thread so it doesn't block UI
        thread = threading.Thread(target=update, daemon=True)
        thread.start()

    def _get_local_ytdlp_version(self, exe_path):
        """Return the version string of the local yt-dlp binary, or None."""
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            result = subprocess.run([exe_path, '--version'], capture_output=True,
                                    text=True, timeout=15, creationflags=creationflags)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _get_latest_ytdlp_version(self):
        """Return the latest yt-dlp nightly release tag from GitHub, or None."""
        try:
            response = requests.get(self.YTDLP_API_LATEST, timeout=10)
            if response.status_code == 200:
                return response.json().get('tag_name', '').strip() or None
        except Exception:
            pass
        return None

    @staticmethod
    def _library_version_label():
        """Version of the yt-dlp frozen into this build, as a bare string."""
        try:
            return f"{yt_dlp.version.__version__} (built in)"
        except Exception:
            return "built in"

    def engine_version_label(self):
        """Short description of which engine is in use, for status/error text."""
        if self._have_ytdlp_exe():
            version_str = self._get_local_ytdlp_version(self.ytdlp_exe_path) or 'unknown'
            return f"yt-dlp {version_str} (auto-updating)"
        return f"yt-dlp {self._library_version_label()}"
    def run_ytdlp_download(self, ydl_opts, url):
        """Run yt-dlp download using either external exe or bundled library"""
        is_frozen = getattr(sys, 'frozen', False)

        # If frozen and we have an external yt-dlp.exe, use it via subprocess
        if is_frozen and self._have_ytdlp_exe():
            return self._run_ytdlp_subprocess(ydl_opts, url)
        else:
            # Use bundled library
            return self._run_ytdlp_library(ydl_opts, url)

    def _run_ytdlp_library(self, ydl_opts, url):
        """Run yt-dlp using the bundled Python library"""
        # Make a copy of options to avoid modifying the original
        opts = ydl_opts.copy()
        self._apply_js_runtime_opts(opts)
        # Add progress hook for library version
        if 'progress_hooks' not in opts:
            opts['progress_hooks'] = [self.progress_hook]

        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url, download=True)
            return result

    def _build_ytdlp_argv(self, ydl_opts):
        """Translate a ydl_opts dict into CLI args for the external yt-dlp binary.

        Shared by the real download and the pre-scan probe so both run through the
        same engine with the same cookies/extractor/JS-runtime settings — if these
        two ever disagree, a URL can pre-scan fine and then fail to download (or
        the reverse). Returns argv without the URL or any progress flags; callers
        append what they need.

        Note this translation is deliberately partial: only the options below are
        forwarded, so anything else in ydl_opts is ignored on this path.
        """
        # Build command line arguments from ydl_opts
        cmd = [self.ytdlp_exe_path]

        # Add output template
        if 'outtmpl' in ydl_opts:
            cmd.extend(['-o', ydl_opts['outtmpl']])

        # Add format
        if 'format' in ydl_opts:
            cmd.extend(['-f', ydl_opts['format']])

        # Add format sorting (prefer highest res, then H.264/AAC)
        if 'format_sort' in ydl_opts:
            cmd.extend(['-S', ','.join(ydl_opts['format_sort'])])

        # Add cookies (browser login or cookies.txt) for age/bot/members-gated videos
        if 'cookiesfrombrowser' in ydl_opts:
            cmd.extend(['--cookies-from-browser', ydl_opts['cookiesfrombrowser'][0]])
        if 'cookiefile' in ydl_opts:
            cmd.extend(['--cookies', ydl_opts['cookiefile']])

        # Add extractor args (e.g. YouTube player_client selection)
        if 'extractor_args' in ydl_opts:
            for extractor, args in ydl_opts['extractor_args'].items():
                for key, value in args.items():
                    value_str = ','.join(value) if isinstance(value, (list, tuple)) else str(value)
                    cmd.extend(['--extractor-args', f'{extractor}:{key}={value_str}'])

        # Add JavaScript runtimes for YouTube EJS/n-challenge solving
        for runtime_arg in self._get_js_runtime_args():
            cmd.extend(['--js-runtimes', runtime_arg])
        for component in ydl_opts.get('remote_components', []):
            cmd.extend(['--remote-components', component])

        # Add merge output format
        if 'merge_output_format' in ydl_opts:
            cmd.extend(['--merge-output-format', ydl_opts['merge_output_format']])

        # Add ffmpeg location
        if 'ffmpeg_location' in ydl_opts:
            cmd.extend(['--ffmpeg-location', ydl_opts['ffmpeg_location']])

        # Add postprocessor args
        if 'postprocessor_args' in ydl_opts:
            for pp_name, args in ydl_opts['postprocessor_args'].items():
                cmd.extend(['--postprocessor-args', f'{pp_name}:{" ".join(args)}'])

        # Add postprocessors
        if 'postprocessors' in ydl_opts:
            for pp in ydl_opts['postprocessors']:
                if pp['key'] == 'FFmpegExtractAudio':
                    cmd.append('-x')
                    if 'preferredcodec' in pp:
                        cmd.extend(['--audio-format', pp['preferredcodec']])
                    if 'preferredquality' in pp:
                        cmd.extend(['--audio-quality', pp['preferredquality']])
                elif pp['key'] == 'FFmpegVideoConvertor':
                    if 'preferedformat' in pp:
                        cmd.extend(['--recode-video', pp['preferedformat']])

        # Add noplaylist option
        if ydl_opts.get('noplaylist'):
            cmd.append('--no-playlist')

        return cmd

    def _have_ytdlp_exe(self):
        """True if the auto-updated external engine is available to run."""
        exe = getattr(self, 'ytdlp_exe_path', None)
        return bool(exe) and os.path.exists(exe)

    def _probe_with_exe(self, ydl_opts, url):
        """Pre-scan a URL with the external (auto-updated) engine.

        The probe used to always run through the yt-dlp library frozen into the
        build, so extraction ran on months-old code even when a fresh binary was
        sitting right there. Extraction is exactly what breaks when a site changes
        its pages, so the probe has to use the current engine too.

        Returns a dict shaped like extract_info(download=False) -- 'entries'
        present means a playlist -- or raises so the caller's existing error
        handling (sign-in routing, fallback) still applies.
        """
        cmd = self._build_ytdlp_argv(ydl_opts)
        cmd.extend(['-J', '--flat-playlist', '--no-warnings', url])

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=120, creationflags=creationflags)
        if result.returncode != 0:
            detail = (result.stderr or '').strip().splitlines()
            detail = [ln for ln in detail if ln.lower().startswith(('error:', 'warning:'))]
            raise Exception("\n".join(detail[-5:]).strip()
                            or f"yt-dlp probe failed with return code {result.returncode}")
        return json.loads(result.stdout)

    def _run_ytdlp_subprocess(self, ydl_opts, url):
        """Run yt-dlp using external executable via subprocess"""
        cmd = self._build_ytdlp_argv(ydl_opts)

        # Add progress reporting
        cmd.append('--newline')
        cmd.append('--progress')

        # Add URL
        cmd.append(url)

        # Track the last downloaded file path from output
        last_filepath = None
        last_error_lines = []

        # Run the command
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            creationflags=creationflags
        )

        # Read output and update progress
        for line in process.stdout:
            line = line.strip()
            if line and (
                line.lower().startswith(('error:', 'warning:'))
                or self._is_auth_error(line)
                or self._is_js_challenge_error(line)
            ):
                last_error_lines.append(line)
                last_error_lines = last_error_lines[-5:]
            if '[download]' in line:
                # Parse progress from output
                if '%' in line:
                    try:
                        # Extract percentage
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if '%' in part:
                                percent_str = part
                                percent = float(percent_str.replace('%', '')) / 100.0

                                # Thread-safe progress update
                                self.after(0, lambda p=percent: self.progress_bar.set(p))

                                # Try to get speed and ETA
                                status_msg = f"Downloading: {percent_str}"
                                if i + 2 < len(parts) and 'iB/s' in parts[i + 2]:
                                    status_msg += f" | Speed: {parts[i + 2]}"
                                if 'ETA' in line:
                                    eta_idx = parts.index('ETA')
                                    if eta_idx + 1 < len(parts):
                                        status_msg += f" | ETA: {parts[eta_idx + 1]}"

                                # Thread-safe status update
                                self.after(0, lambda msg=status_msg: self.update_status(msg, append=False))
                                break
                    except Exception:
                        pass
                elif 'Destination:' in line:
                    # Capture the file path from "Destination: /path/to/file"
                    dest_match = line.split('Destination:', 1)
                    if len(dest_match) > 1:
                        last_filepath = dest_match[1].strip()
                    self.after(0, lambda l=line: self.update_status(l, append=False))
                elif 'has already been downloaded' in line:
                    self.after(0, lambda l=line: self.update_status(l, append=False))
            elif line:
                # Show other important messages
                if 'Extracting' in line or 'Merging' in line or 'Converting' in line:
                    # Thread-safe status update
                    self.after(0, lambda l=line: self.update_status(l, append=False))

        process.wait()

        if process.returncode != 0:
            error_detail = "\n".join(last_error_lines).strip()
            if error_detail:
                raise Exception(error_detail)
            raise Exception(f"yt-dlp failed with return code {process.returncode}")

        # Return result with actual file path if captured
        result = {'title': 'Downloaded'}
        if last_filepath:
            result['requested_downloads'] = [{'filepath': last_filepath}]
        return result

    def show_update_dialog(self, new_version, download_url, release_notes):
        """Show dialog asking user if they want to update"""
        message = f"A new version ({new_version}) is available!\n\n"
        message += f"Current version: {self.CURRENT_VERSION}\n\n"

        if release_notes:
            # Limit release notes length
            notes = release_notes[:300]
            if len(release_notes) > 300:
                notes += "..."
            message += f"What's new:\n{notes}\n\n"

        message += "Do you wanna download and install the update?"

        result = messagebox.askyesno("Omg a potential update!", message)

        if result:
            self.download_and_install_update(download_url)

    def download_and_install_update(self, download_url):
        """Download and install the update"""

        def download():
            temp_fd = None
            temp_path = None
            try:
                # Show download progress
                self.after(0, lambda: self.update_status("Downloading update...", append=False))

                # Download the new exe
                response = requests.get(download_url, stream=True)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))

                # Get current exe path
                if getattr(sys, 'frozen', False):
                    current_exe = os.path.abspath(sys.executable)
                else:
                    current_exe = os.path.abspath(__file__)

                current_dir = os.path.dirname(current_exe)
                final_path = os.path.join(current_dir, 'LacesTotalMediaDownloader_new.exe')

                # Download to a temp file first, then rename on success
                temp_fd, temp_path = tempfile.mkstemp(suffix='.exe.tmp', dir=current_dir)
                os.close(temp_fd)
                temp_fd = None

                # Download with progress
                downloaded = 0
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                self.after(0, lambda p=percent: self.update_status(f"Downloading update: {p:.1f}%",
                                                                                   append=False))

                # Verify download completed
                if total_size > 0 and downloaded != total_size:
                    raise Exception("Download incomplete - file size mismatch")

                # Verify file exists and has content
                if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 1000000:
                    raise Exception("Downloaded file is invalid or too small")

                # Move temp file to final location
                shutil.move(temp_path, final_path)
                temp_path = None  # Prevent cleanup since it's been moved

                self.after(0, lambda: self.update_status("Verifying download...", append=False))

                # Create update script
                if sys.platform == 'win32':
                    script_path = os.path.join(current_dir, 'update_installer.bat')
                    old_exe_backup = os.path.join(current_dir, 'LacesTotalMediaDownloader_old.exe')

                    with open(script_path, 'w') as f:
                        f.write('@echo off\n')
                        f.write('echo Waiting for application to close...\n')
                        f.write('timeout /t 3 /nobreak > nul\n')
                        f.write('echo Backing up current version...\n')
                        f.write(f'if exist "{current_exe}" move /Y "{current_exe}" "{old_exe_backup}" 2>nul\n')
                        f.write('timeout /t 1 /nobreak > nul\n')
                        f.write('echo Installing update...\n')
                        f.write(f'move /Y "{final_path}" "{current_exe}"\n')
                        f.write('if errorlevel 1 (\n')
                        f.write('    echo Update failed! Restoring backup...\n')
                        f.write(f'    if exist "{old_exe_backup}" move /Y "{old_exe_backup}" "{current_exe}"\n')
                        f.write('    echo Update failed. Original version restored.\n')
                        f.write('    pause\n')
                        f.write('    exit /b 1\n')
                        f.write(')\n')
                        f.write('echo Update complete! Restarting application...\n')
                        f.write('timeout /t 2 /nobreak > nul\n')
                        f.write(f'if exist "{old_exe_backup}" del /F /Q "{old_exe_backup}" 2>nul\n')
                        f.write(f'start "" "{current_exe}"\n')
                        f.write(f'del "{script_path}"\n')

                    self.after(0, lambda: messagebox.showinfo(
                        "Update Complete!",
                        "Update will be installed and the application will restart automatically.\n\nClick OK to continue."
                    ))

                    subprocess.Popen(
                        ['cmd.exe', '/c', script_path],
                        cwd=current_dir,
                        shell=False,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    )

                    import time
                    time.sleep(0.5)

                    self.after(100, self.destroy)
                else:
                    self.after(0, lambda: messagebox.showinfo(
                        "Update Downloaded",
                        f"Update downloaded to:\n{final_path}\n\nPlease manually replace the current executable and restart."
                    ))

            except Exception as e:
                # Clean up temp file on failure
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                self.after(0, lambda: messagebox.showerror("Update Failed",
                                                           f"Failed to download update:\n{str(e)}\n\nPlease download the update manually from GitHub."))

        thread = threading.Thread(target=download, daemon=True)
        thread.start()

    def load_config(self):
        """Load the full app config dict from the config file."""
        try:
            config_path = Path.home() / '.lace_downloader_config.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self):
        """Persist all app settings (recent folders, sign-in, codec prefs)."""
        try:
            config_path = Path.home() / '.lace_downloader_config.json'
            data = {
                'recent_folders': self.recent_folders,
                'hires_codec_default': self.hires_codec_default,
                'ask_hires_codec': self.ask_hires_codec,
                'prefer_gpu': self.prefer_gpu,
            }
            with open(config_path, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _delete_legacy_cookiefile(self):
        """Remove the old app-managed cookie export, if a previous run made one."""
        try:
            legacy_path = Path.home() / '.lace_downloader_youtube_cookies.txt'
            if legacy_path.exists():
                legacy_path.unlink()
        except Exception:
            pass

    def add_recent_folder(self, folder):
        """Add folder to recent list"""
        if folder in self.recent_folders:
            self.recent_folders.remove(folder)
        self.recent_folders.insert(0, folder)
        self.recent_folders = self.recent_folders[:10]  # Keep 10 recent
        self.save_config()
        self.update_recent_dropdown()

    def check_ffmpeg(self):
        """Check if ffmpeg is available locally or on the system"""
        # Check local directory first (for bundled exe)
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            base_path = sys._MEIPASS
        else:
            # Running as script
            base_path = os.path.dirname(os.path.abspath(__file__))

        # Check common local paths
        local_paths = [
            os.path.join(base_path, 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg', 'ffmpeg.exe'),
            os.path.join(base_path, 'bin', 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg'),  # Linux/Mac
            os.path.join(base_path, 'ffmpeg', 'ffmpeg'),
            os.path.join(base_path, 'bin', 'ffmpeg'),
        ]

        for path in local_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                # Found local ffmpeg, store the path
                self.ffmpeg_path = path
                return True

        # Fall back to system PATH
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            self.ffmpeg_path = ffmpeg_path
            return True

        self.ffmpeg_path = None
        return False

    def show_ffmpeg_warning(self):
        """Show a warning dialog if ffmpeg is not installed"""
        if sys.platform == 'win32':
            install_hint = (
                "To add FFmpeg:\n"
                "1. Download ffmpeg from https://ffmpeg.org/download.html\n"
                "2. Place ffmpeg.exe in the same folder as this app\n"
                "   OR install it system-wide\n\n"
                "Then restart the app!"
            )
        else:
            install_hint = (
                "To install FFmpeg:\n"
                "  sudo apt install ffmpeg   (Debian/Ubuntu)\n"
                "  sudo dnf install ffmpeg   (Fedora)\n"
                "  sudo pacman -S ffmpeg     (Arch)\n\n"
                "Then restart the app!"
            )

        msg = (
            "FFmpeg Not Found!\n\n"
            "FFmpeg is required for:\n"
            "• Merging video + audio for best quality\n"
            "• Converting to MP3 for audio downloads\n\n"
            "The app will still work but will download single-format files.\n\n"
            + install_hint
        )
        messagebox.showwarning("FFmpeg Not Found", msg)

    # ------------------------------------------------------------------ #
    #  Hardware (GPU) encoder detection + selection                       #
    # ------------------------------------------------------------------ #
    def _detect_hw_encoders(self):
        """Probe which GPU encoders actually initialize on this machine/driver.

        Runs a tiny real encode for each candidate so brand-new GPUs (e.g.
        RTX 50-series) that the bundled ffmpeg supports but the installed driver
        might not are detected correctly — anything that fails is dropped and we
        fall back to CPU.  Runs in a background thread; result cached in
        self.hw_encoders as {'h264': encoder, 'hevc': encoder}.
        """
        def probe():
            if not self.ffmpeg_available or not getattr(self, 'ffmpeg_path', None):
                return
            candidates = {
                'h264': ['h264_nvenc', 'h264_qsv', 'h264_amf'],
                'hevc': ['hevc_nvenc', 'hevc_qsv', 'hevc_amf'],
            }
            found = {}
            for codec, encoders in candidates.items():
                for enc in encoders:
                    if self._test_encoder(enc):
                        found[codec] = enc
                        break
            self.hw_encoders = found
            if found:
                msg = "GPU encoder ready: " + ", ".join(sorted(set(found.values())))
            else:
                msg = "No GPU encoder available — high-res transcodes will use CPU."
            self.after(0, lambda m=msg: self.update_status(m))

        threading.Thread(target=probe, daemon=True).start()

    def _test_encoder(self, encoder):
        """Return True if ffmpeg can actually encode one tiny frame with `encoder`
        using the *same* rate-control flags we'll use for real, so an encoder that
        exists but rejects our settings (e.g. a driver mismatch) is rejected here."""
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            result = subprocess.run(
                [self.ffmpeg_path, '-hide_banner', '-loglevel', 'error',
                 '-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.1',
                 '-c:v', encoder] + self._encoder_quality_args(encoder) + ['-f', 'null', '-'],
                capture_output=True, timeout=25, creationflags=creationflags
            )
            return result.returncode == 0
        except Exception:
            return False

    def _resolve_encoder(self, codec, prefer_gpu=True):
        """Return the ffmpeg encoder name for `codec` ('h264'|'hevc')."""
        codec = 'hevc' if codec == 'hevc' else 'h264'
        if prefer_gpu and self.hw_encoders.get(codec):
            return self.hw_encoders[codec]
        return 'libx265' if codec == 'hevc' else 'libx264'

    @staticmethod
    def _encoder_quality_args(encoder):
        """Rate-control + pixel-format flags for an encoder (one source of truth,
        shared by the startup probe and the real transcode)."""
        table = {
            'h264_nvenc': ['-preset', 'p5', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-pix_fmt', 'yuv420p'],
            'hevc_nvenc': ['-preset', 'p5', '-rc', 'vbr', '-cq', '21', '-b:v', '0', '-pix_fmt', 'yuv420p'],
            'h264_qsv':   ['-global_quality', '21', '-pix_fmt', 'nv12'],
            'hevc_qsv':   ['-global_quality', '23', '-pix_fmt', 'nv12'],
            'h264_amf':   ['-rc', 'cqp', '-qp_i', '20', '-qp_p', '22', '-quality', 'quality', '-pix_fmt', 'yuv420p'],
            'hevc_amf':   ['-rc', 'cqp', '-qp_i', '22', '-qp_p', '24', '-quality', 'quality', '-pix_fmt', 'yuv420p'],
            'libx265':    ['-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p'],
            'libx264':    ['-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p'],
        }
        return list(table.get(encoder, ['-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p']))

    def _video_encoder_args(self, codec, prefer_gpu=None):
        """Build the FFmpegVideoConvertor postprocessor args for an editor-ready mp4.

        Output is always Premiere-friendly: H.264/HEVC in mp4, 8-bit yuv420p,
        AAC audio, faststart.  HEVC is tagged hvc1 so Premiere/QuickTime accept it.
        """
        if prefer_gpu is None:
            prefer_gpu = True
        encoder = self._resolve_encoder(codec, prefer_gpu)

        args = ['-c:v', encoder] + self._encoder_quality_args(encoder)
        if encoder in ('hevc_nvenc', 'hevc_qsv', 'hevc_amf', 'libx265'):
            args += ['-tag:v', 'hvc1']  # required so Premiere/QuickTime accept HEVC-in-mp4
        args += ['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart']
        return args

    # ------------------------------------------------------------------ #
    #  Quality / codec / auth helpers                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _quality_to_height(quality):
        """Map a quality dropdown label to a max height, or None for 'Best'.

        Handles labels like '1080p', '2160p (4K)', '4320p (8K)'.
        """
        if not quality or quality.lower().startswith('best'):
            return None
        digits = re.findall(r'\d+', quality)
        return int(digits[0]) if digits else None

    def _decide_codec(self, target_h):
        """Pick the transcode codec for an mp4 of height `target_h`.

        Respects a remembered default; otherwise H.264 for <=4K and HEVC for 8K
        (8K H.264 is impractically slow/large and most GPUs can't encode it).
        """
        pref = self.hires_codec_default
        if pref in ('h264', 'hevc'):
            return pref
        if target_h and target_h >= 4320:
            return 'hevc'
        return 'h264'

    def _apply_auth_opts(self, ydl_opts, url=None):
        """Attach cookies + bot/age-gate resilience to a yt-dlp options dict.

        Cookies are only attached once the user has actually signed in through
        prompt_signin(). Reaching for the default browser's cookies on every
        YouTube URL used to break *every* download instead of helping: Chromium
        browsers (Chrome/Edge/Brave) keep their cookie database locked while
        they're running, and yt-dlp treats that as a fatal error, so nothing
        downloaded until the user closed their browser. Most videos need no
        cookies at all, so the first attempt is always made without them.
        """
        src = self.cookies_source

        # The sign-in flow is YouTube-only, so keep the cookie store out of
        # every other site's downloads — a browser that later reopens would
        # otherwise start breaking unrelated downloads too.
        if self._is_youtube_url(url):
            if src == 'file' and self.cookies_file and os.path.exists(self.cookies_file):
                ydl_opts['cookiefile'] = self.cookies_file
            elif src and src not in ('none', 'file'):
                ydl_opts['cookiesfrombrowser'] = (src,)

        # Deliberately DON'T pin player_client on the first attempt. yt-dlp
        # maintains that list against YouTube's changes, so hardcoding it here
        # overrides the very fix a freshly-updated engine is shipping -- a way to
        # keep getting 403s on an otherwise current engine. The extra 'tv' client
        # still helps with age gates, so it goes on the retry after a sign-in
        # wall, where we already know a plain attempt didn't work.
        if getattr(self, '_widen_player_clients', False) and self._is_youtube_url(url):
            extractor_args = ydl_opts.setdefault('extractor_args', {})
            yt_args = extractor_args.setdefault('youtube', {})
            yt_args['player_client'] = ['default', 'tv']
        self._apply_js_runtime_opts(ydl_opts)
        return ydl_opts

    def _get_bundled_base_paths(self):
        """Directories to search for bundled binaries (ffmpeg, deno, etc.)."""
        paths = []
        # Anything we downloaded ourselves lives here (writable on every install
        # location), so look here first.
        try:
            paths.append(self._engine_dir())
        except Exception:
            pass
        if getattr(sys, 'frozen', False):
            # PyInstaller onefile self-extracts bundled binaries to _MEIPASS;
            # also check the folder the .exe itself lives in -- older builds
            # downloaded deno/yt-dlp there, and those should keep working.
            paths.append(sys._MEIPASS)
            paths.append(os.path.dirname(sys.executable))
        else:
            paths.append(os.path.dirname(os.path.abspath(__file__)))
        # De-dupe while preserving order (the dirs can coincide in dev runs).
        seen = set()
        return [p for p in paths if p and not (p in seen or seen.add(p))]

    def _find_bundled_executable(self, names):
        """Return the path to a bundled binary matching any of `names`, if present."""
        for base in self._get_bundled_base_paths():
            for name in names:
                for candidate in (
                    os.path.join(base, name),
                    os.path.join(base, 'bin', name),
                ):
                    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                        return candidate
        return None

    def _get_js_runtime_args(self):
        """Return CLI-style JS runtime args for yt-dlp's YouTube EJS solver.

        YouTube's n-challenge needs an actual JS engine. A self-contained Deno
        binary is bundled with the build, so this searches the bundled location
        FIRST and only then falls back to whatever the user may have installed on
        PATH. That keeps YouTube downloads working on machines with neither Node
        nor Deno installed (previously this relied on shutil.which() alone, so it
        silently depended on the build machine having Node/Deno on PATH).
        """
        runtime_candidates = (
            ('deno', ('deno.exe', 'deno')),
            ('node', ('node.exe', 'node')),
            ('quickjs', ('qjs.exe', 'qjs')),
            ('bun', ('bun.exe', 'bun')),
        )

        args = []
        for runtime_name, executables in runtime_candidates:
            # Prefer a binary we shipped inside the build, then fall back to PATH.
            exe_path = self._find_bundled_executable(executables)
            if not exe_path:
                for exe_name in executables:
                    exe_path = shutil.which(exe_name)
                    if exe_path:
                        break
            if not exe_path:
                continue
            # Deno is enabled by default, but passing the detected path makes
            # frozen builds and unusual PATH setups more predictable.
            args.append(f'{runtime_name}:{exe_path}')
        return args

    def _apply_js_runtime_opts(self, ydl_opts):
        """Attach JS runtime/EJS options for Python-library yt-dlp runs."""
        runtimes = {}
        for runtime_arg in self._get_js_runtime_args():
            name, _, path = runtime_arg.partition(':')
            runtimes[name] = {'path': path or None}
        if runtimes:
            ydl_opts['js_runtimes'] = runtimes

        # Official yt-dlp executables already bundle EJS, and pip installs should
        # use yt-dlp[default]. This is a fallback for older local environments.
        ydl_opts.setdefault('remote_components', ['ejs:github'])

    def _runtime_download_dir(self):
        """Folder to drop an auto-downloaded deno into.

        Same per-user location as the yt-dlp engine, so it still works when the
        app is installed somewhere unwritable.
        """
        return self._engine_dir()

    @staticmethod
    def _deno_download_url():
        """Latest-release Deno asset URL for this platform (zip archive)."""
        base = 'https://github.com/denoland/deno/releases/latest/download/'
        if sys.platform == 'win32':
            return base + 'deno-x86_64-pc-windows-msvc.zip'
        if sys.platform == 'darwin':
            import platform
            arch = 'aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
            return base + f'deno-{arch}-apple-darwin.zip'
        return base + 'deno-x86_64-unknown-linux-gnu.zip'

    def ensure_js_runtime(self):
        """Make sure a JavaScript runtime is available for YouTube's n-challenge.

        Runs in the background on startup. If a runtime is already available
        (bundled deno, or deno/node/etc. on PATH) this does nothing. Otherwise it
        downloads a self-contained Deno into the app folder — the same pattern the
        app already uses for yt-dlp.exe — so YouTube works on machines that have
        neither Node nor Deno installed.
        """
        def work():
            # Already have a runtime (bundled, previously downloaded, or on PATH)?
            if self._get_js_runtime_args():
                return

            deno_name = 'deno.exe' if sys.platform == 'win32' else 'deno'
            deno_path = os.path.join(self._runtime_download_dir(), deno_name)
            if os.path.exists(deno_path):
                return

            import io
            import zipfile
            temp_path = deno_path + '.tmp'
            try:
                self.after(0, lambda: self.update_status(
                    "Setting up YouTube support (one-time Deno download)..."))
                resp = requests.get(self._deno_download_url(), timeout=180)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    member = next((n for n in z.namelist()
                                   if os.path.basename(n) in ('deno.exe', 'deno')), None)
                    if not member:
                        raise Exception("deno binary not found in the downloaded archive")
                    data = z.read(member)
                if len(data) < 20_000_000:  # deno is ~95 MB; guard against a bad download
                    raise Exception("downloaded Deno looks too small / corrupt")
                with open(temp_path, 'wb') as f:
                    f.write(data)
                if sys.platform != 'win32':
                    os.chmod(temp_path, 0o755)
                os.replace(temp_path, deno_path)
                self.after(0, lambda: self.update_status(
                    "YouTube support ready (Deno installed)."))
            except Exception as e:
                self.after(0, lambda err=e: self.update_status(
                    f"Couldn't set up Deno automatically: {err}\n"
                    "YouTube may still work; if not, install Deno or Node.js 22+ and restart."))
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _is_js_challenge_error(e):
        """True if YouTube formats failed because EJS/JS runtime support is missing."""
        low = str(e).lower()
        signals = (
            'n challenge solving failed',
            'supported javascript runtime',
            'challenge solver script',
            'only images are available',
            'js runtimes: none',
        )
        return any(s in low for s in signals) or (
            'requested format is not available' in low and '[youtube]' in low
        )

    @staticmethod
    def _is_youtube_url(url):
        """True when a URL should use YouTube browser auth automatically."""
        if not url:
            return False
        low = str(url).lower()
        return any(host in low for host in (
            'youtube.com/',
            'youtu.be/',
            'youtube-nocookie.com/',
        ))

    def setup_ui(self):
        # Main container with padding
        self.main_frame = ctk.CTkFrame(self, fg_color=self.colors['bg'])
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Header row with title and update check button
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['bg'])
        self.header_frame.pack(fill="x", pady=(0, 20))

        # Title with custom font — centered
        if self.has_bubblegum:
            title_font = ctk.CTkFont(family="Bubblegum Sans", size=40, weight="bold")
        else:
            title_font = ctk.CTkFont(size=40, weight="bold")

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="Lace's Total Media Downloader",
            font=title_font,
            text_color=self.colors['purple']
        )
        self.title_label.pack(side="left", expand=True)

        # Check for Updates button
        self.check_updates_btn = ctk.CTkButton(
            self.header_frame,
            text="🔄",
            command=self.manual_check_for_updates,
            width=50,
            height=50,
            font=ctk.CTkFont(size=20),
            fg_color=self.colors['button'],
            hover_color=self.colors['purple'],
            corner_radius=25
        )
        self.check_updates_btn.pack(side="right", padx=(0, 10))

        # Which download engine is actually running. Site breakage is the most
        # common failure, and "how old is my engine?" is the first thing worth
        # knowing when it happens -- so keep the answer on screen.
        self.engine_label = ctk.CTkLabel(
            self.header_frame,
            text="engine: checking…",
            font=ctk.CTkFont(size=11),
            text_color=self.colors['purple']
        )
        self.engine_label.pack(side="right", padx=(0, 10))

        # Default font for the rest of the UI
        if self.has_bartino:
            default_font = ("Bartino", 13)
            label_font = ctk.CTkFont(family="Bartino", size=15, weight="bold")
            small_font = ctk.CTkFont(family="Bartino", size=12)
            button_font = ctk.CTkFont(family="Bartino", size=13)
        else:
            default_font = ("", 13)
            label_font = ctk.CTkFont(size=15, weight="bold")
            small_font = ctk.CTkFont(size=12)
            button_font = ctk.CTkFont(size=13)

        # URL Input Section
        self.url_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['frame_bg'], corner_radius=10)
        self.url_frame.pack(fill="x", pady=(0, 10))

        self.url_label = ctk.CTkLabel(
            self.url_frame,
            text="Media URL:",
            font=label_font,
            text_color=self.colors['text']
        )
        self.url_label.pack(anchor="w", padx=15, pady=(12, 5))

        self.url_entry = ctk.CTkEntry(
            self.url_frame,
            placeholder_text="Supports nearly every major video / audio website",
            height=42,
            font=small_font,
            border_color=self.colors['purple'],
            fg_color=self.colors['frame_bg']
        )
        self.url_entry.pack(fill="x", padx=15, pady=(0, 15))

        # Download Options Section
        self.options_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['frame_bg'], corner_radius=10)
        self.options_frame.pack(fill="x", pady=(0, 10))

        self.options_label = ctk.CTkLabel(
            self.options_frame,
            text="Download Options:",
            font=label_font,
            text_color=self.colors['text']
        )
        self.options_label.pack(anchor="w", padx=15, pady=(15, 10))

        # Type and Quality row
        self.type_quality_frame = ctk.CTkFrame(self.options_frame, fg_color=self.colors['frame_bg'])
        self.type_quality_frame.pack(fill="x", padx=15, pady=(0, 12))

        # Download type
        self.type_frame = ctk.CTkFrame(self.type_quality_frame, fg_color=self.colors['frame_bg'])
        self.type_frame.pack(side="left", padx=(0, 15))

        self.type_label = ctk.CTkLabel(self.type_frame, text="Type:", font=small_font, text_color=self.colors['text'])
        self.type_label.pack(side="left", padx=(0, 10))

        self.video_radio = ctk.CTkRadioButton(
            self.type_frame,
            text="Video",
            variable=self.download_type,
            value="video",
            command=self.on_type_change,
            font=small_font,
            fg_color=self.colors['purple'],
            hover_color=self.colors['dark_purple']
        )
        self.video_radio.pack(side="left", padx=5)

        self.audio_radio = ctk.CTkRadioButton(
            self.type_frame,
            text="Audio",
            variable=self.download_type,
            value="audio",
            command=self.on_type_change,
            font=small_font,
            fg_color=self.colors['purple'],
            hover_color=self.colors['dark_purple']
        )
        self.audio_radio.pack(side="left", padx=5)

        # Quality selection
        self.quality_frame = ctk.CTkFrame(self.type_quality_frame, fg_color=self.colors['frame_bg'])
        self.quality_frame.pack(side="left", padx=(0, 15))

        self.quality_label = ctk.CTkLabel(self.quality_frame, text="Quality:", font=small_font,
                                          text_color=self.colors['text'])
        self.quality_label.pack(side="left", padx=(0, 10))

        self.video_quality_menu = ctk.CTkOptionMenu(
            self.quality_frame,
            values=["Best", "4320p (8K)", "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p"],
            variable=self.quality,
            width=130,
            height=32,
            font=small_font,
            fg_color=self.colors['button'],
            button_color=self.colors['purple'],
            button_hover_color=self.colors['dark_purple']
        )
        self.video_quality_menu.pack(side="left", padx=(0, 10))

        self.audio_quality_menu = ctk.CTkOptionMenu(
            self.quality_frame,
            values=["320 kbps", "256 kbps", "192 kbps", "128 kbps"],
            variable=self.audio_quality,
            width=100,
            height=32,
            font=small_font,
            fg_color=self.colors['button'],
            button_color=self.colors['purple'],
            button_hover_color=self.colors['dark_purple']
        )

        # Format selection
        self.format_frame = ctk.CTkFrame(self.type_quality_frame, fg_color=self.colors['frame_bg'])
        self.format_frame.pack(side="left")

        self.format_label = ctk.CTkLabel(self.format_frame, text="Format:", font=small_font,
                                         text_color=self.colors['text'])
        self.format_label.pack(side="left", padx=(0, 10))

        self.video_format_menu = ctk.CTkOptionMenu(
            self.format_frame,
            values=["mp4", "mkv", "webm", "avi", "mov", "flv"],
            variable=self.video_format,
            width=90,
            height=32,
            font=small_font,
            fg_color=self.colors['button'],
            button_color=self.colors['purple'],
            button_hover_color=self.colors['dark_purple']
        )
        self.video_format_menu.pack(side="left")

        self.audio_format_menu = ctk.CTkOptionMenu(
            self.format_frame,
            values=["mp3", "m4a", "opus", "ogg", "wav", "flac", "aac"],
            variable=self.audio_format,
            width=90,
            height=32,
            font=small_font,
            fg_color=self.colors['button'],
            button_color=self.colors['purple'],
            button_hover_color=self.colors['dark_purple']
        )

        # Download button
        self.download_btn = ctk.CTkButton(
            self.main_frame,
            text="DOWNLOAD",
            command=self.start_download,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=self.colors['button'],
            hover_color=self.colors['purple'],
            corner_radius=10
        )
        self.download_btn.pack(fill="x", pady=(0, 12))

        # Progress Section
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['frame_bg'], corner_radius=10)
        self.progress_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Download Progress:",
            font=label_font,
            text_color=self.colors['text']
        )
        self.progress_label.pack(anchor="w", padx=15, pady=(15, 10))

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            height=20,
            progress_color=self.colors['purple'],
            fg_color="#E0D4F0"
        )
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 10))
        self.progress_bar.set(0)

        self.status_text = ctk.CTkTextbox(
            self.progress_frame,
            height=110,
            font=small_font,
            wrap="word"
        )
        self.status_text.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.status_text.insert("1.0",
                                "Quivering in anticipation...\nSlap that URL up above and smash that download button!")
        self.status_text.configure(state="disabled")

        # Output Location Section
        self.output_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['frame_bg'], corner_radius=10)
        self.output_frame.pack(fill="x", pady=(0, 10))

        self.output_label = ctk.CTkLabel(
            self.output_frame,
            text="Output Folder:",
            font=label_font,
            text_color=self.colors['text']
        )
        self.output_label.pack(anchor="w", padx=15, pady=(12, 8))

        self.output_row = ctk.CTkFrame(self.output_frame, fg_color=self.colors['frame_bg'])
        self.output_row.pack(fill="x", padx=15, pady=(0, 12))

        self.output_entry = ctk.CTkEntry(
            self.output_row,
            textvariable=self.output_folder,
            height=36,
            font=small_font,
            border_color=self.colors['purple'],
            fg_color=self.colors['frame_bg']
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # Recent folders dropdown
        self.recent_dropdown = ctk.CTkOptionMenu(
            self.output_row,
            values=["Recent..."],
            command=self.on_recent_selected,
            width=110,
            height=36,
            font=small_font,
            fg_color=self.colors['button'],
            button_color=self.colors['purple'],
            button_hover_color=self.colors['dark_purple']
        )
        self.recent_dropdown.pack(side="left", padx=(0, 10))
        self.update_recent_dropdown()

        self.browse_btn = ctk.CTkButton(
            self.output_row,
            text="Browse",
            command=self.browse_folder,
            width=90,
            height=36,
            font=button_font,
            fg_color=self.colors['pink'],
            hover_color=self.colors['purple']
        )
        self.browse_btn.pack(side="left")

    def on_type_change(self):
        if self.download_type.get() == "video":
            self.audio_quality_menu.pack_forget()
            self.audio_format_menu.pack_forget()
            self.video_quality_menu.pack(side="left", padx=(0, 8))
            self.video_format_menu.pack(side="left")
            self.quality_label.configure(text="Quality:")
            self.format_label.configure(text="Format:")
        else:
            self.video_quality_menu.pack_forget()
            self.video_format_menu.pack_forget()
            self.audio_quality_menu.pack(side="left", padx=(0, 8))
            self.audio_format_menu.pack(side="left")
            self.quality_label.configure(text="Bitrate:")
            self.format_label.configure(text="Format:")

    # ------------------------------------------------------------------ #
    #  On-demand sign-in (shown only when a video needs authentication)   #
    # ------------------------------------------------------------------ #
    def _is_auth_error(self, e):
        """True if the site is refusing the video without a signed-in account.

        Cookie *plumbing* failures are deliberately not included — see
        _is_cookie_source_error(). Treating "I couldn't read your cookies" as
        "this video is age-restricted" is what made the sign-in popup appear on
        every single download.
        """
        low = str(e).lower()
        signals = (
            'confirm your age', 'age-restricted', 'age restricted', 'inappropriate',
            "confirm you're not a bot", 'not a bot', 'sign in to confirm', 'sign in to view',
            'members-only', 'members only', 'join this channel', 'private video',
            'this video is private', 'login required', 'requires authentication',
            'use --cookies', 'use --cookies-from-browser', 'cookies are no longer valid',
            'pass cookies to yt-dlp', 'exporting youtube cookies',
        )
        return any(s in low for s in signals)

    @staticmethod
    def _is_cookie_source_error(e):
        """True if yt-dlp could not read the cookie source we handed it.

        That's a local problem (browser running and holding its cookie database
        open, Windows refusing to decrypt it, missing profile, unreadable
        cookies.txt) — not the site asking for a login.
        """
        low = str(e).lower()
        signals = (
            'could not copy', 'cookie database', 'failed to decrypt', 'unable to decrypt',
            'failed to load cookies', 'cookieloaderror', 'could not find local state',
            'no encrypted key', 'unknown browser', 'unsupported browser',
            'does not support profiles', 'could not find firefox', 'invalid netscape format',
        )
        return any(s in low for s in signals)

    @staticmethod
    def _auth_reason(error_msg):
        """One-line explanation of why the site wants a signed-in account."""
        low = str(error_msg or '').lower()
        if 'age' in low or 'inappropriate' in low:
            return "This video is age-restricted."
        if 'not a bot' in low:
            return "YouTube wants to confirm you're not a bot."
        if 'members' in low or 'join this channel' in low:
            return "This video is for channel members only."
        if 'private' in low:
            return "This video is private."
        return "This video needs a signed-in YouTube account."

    # yt-dlp browser names -> display names
    BROWSER_LABELS = {
        'firefox': 'Firefox', 'chrome': 'Chrome', 'edge': 'Edge', 'brave': 'Brave',
        'chromium': 'Chromium', 'opera': 'Opera', 'vivaldi': 'Vivaldi', 'safari': 'Safari',
    }
    # Browsers whose cookie store yt-dlp cannot read while the browser is open
    CHROMIUM_BROWSERS = ('chrome', 'edge', 'brave', 'chromium', 'opera', 'vivaldi')

    @classmethod
    def _browser_label(cls, source):
        if source == 'file':
            return 'the cookies.txt file'
        return cls.BROWSER_LABELS.get(source, str(source).title())

    def _browser_profile_dirs(self):
        """Where each browser keeps the profile yt-dlp reads cookies from."""
        home = str(Path.home())
        if sys.platform == 'win32':
            local = os.environ.get('LOCALAPPDATA', os.path.join(home, 'AppData', 'Local'))
            roaming = os.environ.get('APPDATA', os.path.join(home, 'AppData', 'Roaming'))
            return {
                'firefox': [os.path.join(roaming, 'Mozilla', 'Firefox')],
                'chrome': [os.path.join(local, 'Google', 'Chrome', 'User Data')],
                'edge': [os.path.join(local, 'Microsoft', 'Edge', 'User Data')],
                'brave': [os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data')],
                'chromium': [os.path.join(local, 'Chromium', 'User Data')],
                'opera': [os.path.join(roaming, 'Opera Software', 'Opera Stable')],
                'vivaldi': [os.path.join(local, 'Vivaldi', 'User Data')],
            }
        if sys.platform == 'darwin':
            support = os.path.join(home, 'Library', 'Application Support')
            return {
                'firefox': [os.path.join(support, 'Firefox')],
                'chrome': [os.path.join(support, 'Google', 'Chrome')],
                'edge': [os.path.join(support, 'Microsoft Edge')],
                'brave': [os.path.join(support, 'BraveSoftware', 'Brave-Browser')],
                'chromium': [os.path.join(support, 'Chromium')],
                'opera': [os.path.join(support, 'com.operasoftware.Opera')],
                'vivaldi': [os.path.join(support, 'Vivaldi')],
                'safari': [os.path.join(home, 'Library', 'Cookies')],
            }
        # Linux (including the flatpak sandbox's view of the host dirs)
        cfg = os.environ.get('XDG_CONFIG_HOME', os.path.join(home, '.config'))
        return {
            'firefox': [os.path.join(home, '.mozilla', 'firefox'),
                        os.path.join(home, 'snap', 'firefox', 'common', '.mozilla', 'firefox'),
                        os.path.join(home, '.var', 'app', 'org.mozilla.firefox', '.mozilla', 'firefox')],
            'chrome': [os.path.join(cfg, 'google-chrome')],
            'edge': [os.path.join(cfg, 'microsoft-edge')],
            'brave': [os.path.join(cfg, 'BraveSoftware', 'Brave-Browser'),
                      os.path.join(home, '.var', 'app', 'com.brave.Browser', 'config',
                                   'BraveSoftware', 'Brave-Browser')],
            'chromium': [os.path.join(cfg, 'chromium'),
                         os.path.join(home, 'snap', 'chromium', 'common', 'chromium')],
            'opera': [os.path.join(cfg, 'opera')],
            'vivaldi': [os.path.join(cfg, 'vivaldi')],
        }

    def _available_browsers(self):
        """Installed browsers yt-dlp can read cookies from, best choice first.

        Firefox leads because it is the only browser whose cookies stay
        readable on Windows while it's running.
        """
        found = [name for name, dirs in self._browser_profile_dirs().items()
                 if any(os.path.isdir(d) for d in dirs)]
        default = self._get_default_browser()
        order = {'firefox': 0}
        found.sort(key=lambda n: (order.get(n, 1), n != default, n))
        return found

    def _browser_executable(self, browser):
        """Path to a browser's executable, so we can open YouTube in *that* one."""
        if sys.platform == 'win32':
            prog = os.environ.get('ProgramFiles', r'C:\Program Files')
            prog86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
            local = os.environ.get('LOCALAPPDATA', '')
            candidates = {
                'firefox': [os.path.join(p, 'Mozilla Firefox', 'firefox.exe') for p in (prog, prog86)],
                'chrome': [os.path.join(p, 'Google', 'Chrome', 'Application', 'chrome.exe')
                           for p in (prog, prog86, local)],
                'edge': [os.path.join(p, 'Microsoft', 'Edge', 'Application', 'msedge.exe')
                         for p in (prog86, prog)],
                'brave': [os.path.join(p, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe')
                          for p in (prog, prog86, local)],
                'chromium': [os.path.join(p, 'Chromium', 'Application', 'chrome.exe')
                             for p in (prog, prog86, local)],
                'opera': [os.path.join(local, 'Programs', 'Opera', 'opera.exe')],
                'vivaldi': [os.path.join(p, 'Vivaldi', 'Application', 'vivaldi.exe')
                            for p in (prog, local)],
            }.get(browser, [])
            for path in candidates:
                if path and os.path.isfile(path):
                    return path
            return None
        names = {
            'firefox': ('firefox',), 'chrome': ('google-chrome', 'google-chrome-stable', 'chrome'),
            'edge': ('microsoft-edge', 'microsoft-edge-stable'), 'brave': ('brave-browser', 'brave'),
            'chromium': ('chromium', 'chromium-browser'), 'opera': ('opera',), 'vivaldi': ('vivaldi',),
        }.get(browser, ())
        for name in names:
            path = shutil.which(name)
            if path:
                return path
        return None

    def _open_youtube_in(self, browser):
        """Open YouTube in `browser`, falling back to the system default."""
        exe = self._browser_executable(browser)
        if exe:
            try:
                subprocess.Popen([exe, 'https://www.youtube.com'])
                return
            except Exception:
                pass
        try:
            webbrowser.open('https://www.youtube.com')
        except Exception:
            pass

    class _QuietCookieLogger:
        """Swallow yt-dlp's cookie chatter while we're only probing."""

        def debug(self, message, **kwargs):
            pass

        info = warning = error = debug

    @staticmethod
    def _has_youtube_login(jar):
        """True if a cookie jar actually carries a signed-in YouTube session."""
        login_names = {'sid', 'sapisid', 'hsid', 'ssid', 'apisid',
                       '__secure-1psid', '__secure-3psid'}
        for cookie in jar:
            domain = (cookie.domain or '').lower()
            if cookie.name.lower() in login_names and (
                    'youtube.com' in domain or 'google.com' in domain):
                return True
        return False

    def _cookie_problem_message(self, source, error):
        """Turn a cookie-reading failure into advice the user can act on."""
        low = str(error).lower()
        label = self._browser_label(source)
        if 'could not find' in low or 'no such file' in low or 'unknown browser' in low \
                or 'unsupported' in low or 'no encrypted key' in low:
            return f"No {label} profile with saved cookies was found on this computer."
        if 'could not copy' in low or 'cookie database' in low or 'permission' in low:
            return (f"{label} is still running, so it's holding its cookie database open. "
                    f"Close {label} completely (check the system tray), then click "
                    f"Retry Download — or sign in with Firefox instead, which doesn't "
                    f"have to be closed.")
        if 'decrypt' in low:
            return (f"Windows won't let yt-dlp decrypt {label}'s saved cookies. "
                    f"Sign in with Firefox instead, or use a cookies.txt file.")
        if 'netscape' in low or (source == 'file' and 'invalid' in low):
            return ("That cookies.txt file couldn't be read. Export it again in "
                    "Netscape format.")
        return f"Couldn't read cookies from {label}: {error}"

    def _verify_cookie_source(self, source):
        """Check we can read a signed-in session from `source` before retrying.

        Returns (ok, problem). Verifying up front is what keeps the popup from
        looping: a source that can't be read is explained here instead of
        failing the download all over again.
        """
        from yt_dlp.cookies import extract_cookies_from_browser, YoutubeDLCookieJar
        try:
            if source == 'file':
                if not self.cookies_file or not os.path.exists(self.cookies_file):
                    return False, "Choose a cookies.txt file first."
                jar = YoutubeDLCookieJar(self.cookies_file)
                jar.load()
            else:
                jar = extract_cookies_from_browser(source, logger=self._QuietCookieLogger())
        except Exception as e:
            return False, self._cookie_problem_message(source, e)

        if not self._has_youtube_login(jar):
            return False, (f"{self._browser_label(source)} doesn't have a YouTube sign-in "
                           f"saved. Click Open YouTube, sign in there, then click "
                           f"Retry Download.")
        return True, ''

    def _use_signin_source(self, url, source, dialog=None, on_problem=None):
        """Switch to `source` and restart the download for `url` with it.

        Returns True when the retry actually started. A source we can't read is
        reported through `on_problem` and left unset, so the download is never
        retried with cookies that are already known to fail.
        """
        ok, problem = self._verify_cookie_source(source)
        if not ok:
            if on_problem:
                on_problem(problem)
            return False

        self.cookies_source = source
        if dialog is not None:
            try:
                dialog.destroy()
            except Exception:
                pass
        self._restart_download(url)
        return True

    def _get_default_browser(self):
        """Detect the user's default browser as a yt-dlp browser name (Windows)."""
        if sys.platform != 'win32':
            return None
        try:
            import winreg
            key = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                progid = (winreg.QueryValueEx(k, 'ProgId')[0] or '').lower()
            for needle, name in (('firefox', 'firefox'), ('brave', 'brave'), ('msedge', 'edge'),
                                 ('edge', 'edge'), ('opera', 'opera'), ('vivaldi', 'vivaldi'),
                                 ('chromium', 'chromium'), ('chrome', 'chrome')):
                if needle in progid:
                    return name
        except Exception:
            pass
        return None

    def _route_auth_failure(self, url, error_msg):
        """Show the sign-in dialog when a failure is about authentication.

        Returns True when the error was handled, so callers stop treating it as
        an ordinary download error. Cookie-reading failures get their own
        explanation and drop the unusable source, so the next plain attempt
        isn't poisoned by it.
        """
        # The popup can only help with YouTube; anything else gets the plain
        # error message rather than a sign-in prompt it can't act on.
        if not self._is_youtube_url(url):
            return False

        source = self.cookies_source
        if source != 'none' and self._is_cookie_source_error(error_msg):
            problem = self._cookie_problem_message(source, error_msg)
            self.cookies_source = 'none'
            self.after(0, lambda: self.prompt_signin(
                url, cookie_problem=problem, preselect=source))
            return True

        if self._is_auth_error(error_msg):
            # A plain attempt hit a wall, so let the retry try extra clients too.
            self._widen_player_clients = True
            self.after(0, lambda msg=error_msg: self.prompt_signin(url, msg))
            return True
        return False

    def prompt_signin(self, url, error_msg=None, cookie_problem=None, preselect=None):
        """Popup shown when a video needs a signed-in YouTube account.

        The user picks a browser they're signed into (or a cookies.txt export),
        signs in there, and Retry Download restarts the download with those
        cookies. The choice is checked before the retry, so a cookie store we
        can't read explains itself here instead of failing the download again.
        Runs on the main thread.
        """
        existing = getattr(self, '_signin_dialog', None)
        if existing is not None:
            try:
                existing.lift()
                existing.focus_force()
                return
            except Exception:
                self._signin_dialog = None

        browsers = self._available_browsers()
        cookies_label = "cookies.txt file..."
        labels = [self._browser_label(b) for b in browsers]
        label_to_browser = dict(zip(labels, browsers))
        labels.append(cookies_label)

        if preselect in browsers:
            initial = self._browser_label(preselect)
        elif preselect == 'file' or (self.cookies_source == 'file' and self.cookies_file):
            initial = cookies_label
        elif self.cookies_source in browsers:
            initial = self._browser_label(self.cookies_source)
        else:
            initial = labels[0]

        dialog = ctk.CTkToplevel(self)
        self._signin_dialog = dialog
        dialog.title("Sign-in required")
        dialog.configure(fg_color=self.colors['bg'])
        dialog.geometry("560x400")
        dialog.resizable(False, False)
        dialog.transient(self)
        self.set_toplevel_icon(dialog)

        ctk.CTkLabel(
            dialog,
            text=f"{self._auth_reason(error_msg)} Sign in to a YouTube account "
                 f"that can watch it and the download will pick up from there.",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors['text'], justify="left", wraplength=500,
        ).pack(anchor="w", padx=24, pady=(24, 12))

        choice = ctk.StringVar(value=initial)

        row = ctk.CTkFrame(dialog, fg_color=self.colors['bg'])
        row.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(row, text="Sign in with:", font=ctk.CTkFont(size=12),
                     text_color=self.colors['text']).pack(side="left", padx=(0, 10))
        ctk.CTkOptionMenu(row, variable=choice, values=labels, width=170,
                          fg_color=self.colors['frame_bg'],
                          button_color=self.colors['button'],
                          button_hover_color=self.colors['purple'],
                          command=lambda _=None: refresh_hint()).pack(side="left")
        ctk.CTkButton(row, text="Open YouTube", width=140, height=32,
                      command=lambda: open_browser(),
                      fg_color=self.colors['frame_bg'],
                      hover_color=self.colors['dark_purple']).pack(side="left", padx=(10, 0))

        hint = ctk.CTkLabel(dialog, text="", font=ctk.CTkFont(size=11),
                            text_color=self.colors['text'], justify="left", wraplength=500)
        hint.pack(anchor="w", padx=24, pady=(6, 0))

        status = ctk.CTkLabel(dialog, text="", font=ctk.CTkFont(size=11),
                              text_color=self.colors['purple'], justify="left", wraplength=500)
        status.pack(anchor="w", padx=24, pady=(10, 0))
        if cookie_problem:
            status.configure(text=cookie_problem)
        elif error_msg and self.cookies_source != 'none':
            status.configure(text=f"{self._browser_label(self.cookies_source)}'s sign-in "
                                  f"couldn't open this video. Try another account or browser.")

        def current_source():
            return label_to_browser.get(choice.get(), 'file')

        def refresh_hint():
            src = current_source()
            if src == 'file':
                hint.configure(text="Export cookies.txt from a browser you're signed into "
                                    "YouTube with (any \"Get cookies.txt\" extension), then "
                                    "click Retry Download.")
            elif src in self.CHROMIUM_BROWSERS:
                hint.configure(text=f"{self._browser_label(src)} has to be closed completely "
                                    f"before its cookies can be read — Windows keeps the "
                                    f"cookie file locked while it's open.")
            else:
                hint.configure(text=f"{self._browser_label(src)} can stay open while the "
                                    f"download runs.")

        def pick_cookie_file():
            path = filedialog.askopenfilename(
                parent=dialog, title="Select cookies.txt",
                filetypes=[("Cookie files", "*.txt"), ("All files", "*.*")])
            if path:
                self.cookies_file = path
                choice.set(cookies_label)
                refresh_hint()
                status.configure(text=f"{os.path.basename(path)} selected — "
                                      f"click Retry Download.")

        def open_browser():
            src = current_source()
            if src == 'file':
                pick_cookie_file()
                return
            self._open_youtube_in(src)
            status.configure(text=f"Sign in to YouTube in {self._browser_label(src)}, "
                                  f"then click Retry Download.")

        def retry():
            src = current_source()
            if src == 'file' and not self.cookies_file:
                pick_cookie_file()
                return
            status.configure(text=f"Checking your {self._browser_label(src)} sign-in...")
            retry_btn.configure(state="disabled")
            dialog.update_idletasks()
            started = self._use_signin_source(
                url, src, dialog=dialog,
                on_problem=lambda msg: status.configure(text=msg))
            if started:
                self._signin_dialog = None
            else:
                retry_btn.configure(state="normal")

        def cancel():
            self._signin_dialog = None
            dialog.destroy()
            self.update_status("Download cancelled — this video needs a YouTube sign-in.")

        row2 = ctk.CTkFrame(dialog, fg_color=self.colors['bg'])
        row2.pack(fill="x", side="bottom", padx=24, pady=(18, 20))
        ctk.CTkButton(row2, text="Cancel", command=cancel, width=110, height=40,
                      fg_color=self.colors['frame_bg'],
                      hover_color=self.colors['dark_purple']).pack(side="left")
        retry_btn = ctk.CTkButton(row2, text="Retry Download", command=retry, width=170,
                                  height=40, fg_color=self.colors['button'],
                                  hover_color=self.colors['purple'])
        retry_btn.pack(side="right")

        refresh_hint()

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.after(120, dialog.grab_set)  # modal once the window exists

    def _restart_download(self, url):
        """Re-run a download for `url` (used after the user signs in)."""
        self.is_downloading = True
        self.download_btn.configure(state="disabled", text="Downloading...")
        self.progress_bar.set(0)
        self.update_status("Retrying with your YouTube sign-in...", append=False)
        threading.Thread(target=self.download_media, args=(url,), daemon=True).start()

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.set(folder)
            self.add_recent_folder(folder)

    def update_recent_dropdown(self):
        """Update the recent folders dropdown"""
        if self.recent_folders:
            # Use full paths as values to avoid name collisions between
            # different folders that happen to share the same leaf name
            display_paths = []
            for folder in self.recent_folders[:10]:
                display = folder
                if len(display) > 40:
                    display = "..." + display[-37:]
                display_paths.append(display)

            # Store mapping from display string to full path
            self._recent_display_to_path = {}
            for display, full_path in zip(display_paths, self.recent_folders[:10]):
                self._recent_display_to_path[display] = full_path

            self.recent_dropdown.configure(values=display_paths)
        else:
            self._recent_display_to_path = {}
            self.recent_dropdown.configure(values=["No recent folders"])

    def on_recent_selected(self, choice):
        """Handle recent folder selection"""
        if choice and choice != "No recent folders":
            full_path = self._recent_display_to_path.get(choice)
            if full_path:
                self.output_folder.set(full_path)

    def open_folder(self, path):
        """Open folder in file explorer (cross-platform)"""
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':  # macOS
                subprocess.run(['open', path])
            else:  # Linux
                subprocess.run(['xdg-open', path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {str(e)}")

    def play_notification_sound(self):
        """Play notification sound from assets/sounds folder"""
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            sound_path = os.path.join(base_path, 'assets', 'sounds', 'notification.mp3')

            if os.path.exists(sound_path):
                mixer.music.load(sound_path)
                mixer.music.play()
        except Exception:
            pass

    def show_completion_dialog(self):
        """Show completion dialog and ask if user wants to open folder"""
        # Play notification sound
        self.play_notification_sound()

        result = messagebox.askyesno(
            "You did it!",
            "Good job!\n\n"
            "Do you wanna open the output folder? 🥺",
            icon='info'
        )

        if result:
            self.open_folder(self.output_folder.get())

    def update_status(self, message, append=True):
        self.status_text.configure(state="normal")
        if not append:
            self.status_text.delete("1.0", "end")
        else:
            # Ensure a newline separator before appending
            current = self.status_text.get("1.0", "end-1c")
            if current and not current.endswith("\n"):
                self.status_text.insert("end", "\n")
        self.status_text.insert("end", f"{message}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def progress_hook(self, d):
        """Called from yt-dlp worker thread — schedule all UI updates on the main thread."""
        if d['status'] == 'downloading':
            try:
                percent_str = d.get('_percent_str', '0%').strip()
                percent = float(percent_str.replace('%', '')) / 100.0

                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                downloaded = d.get('_downloaded_bytes_str', 'N/A')
                total = d.get('_total_bytes_str', 'N/A')

                status_msg = f"Downloading: {percent_str} ({downloaded}/{total})\n"
                status_msg += f"Speed: {speed} | ETA: {eta}"

                # Thread-safe UI updates via self.after
                self.after(0, lambda p=percent: self.progress_bar.set(p))
                self.after(0, lambda msg=status_msg: self.update_status(msg, append=False))
            except Exception:
                pass
        elif d['status'] == 'finished':
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.update_status("So Close! Almost done...", append=False))

    def _build_ydl_opts(self, noplaylist, target_height=None, url=None):
        """Build yt-dlp options dict from the current UI settings.

        Shared by download_media() and download_with_playlist_choice() so that
        format / postprocessor logic is defined in exactly one place.

        target_height is the resolved/probed height of the video (used to decide
        whether a high-res mp4 request should be saved as mkv instead). None
        means "Best / unknown" and is treated as high-res.
        """
        output_template = os.path.join(self.output_folder.get(), "%(title)s.%(ext)s")
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': noplaylist,
        }

        # Attach cookies + bot/age-gate resilience
        self._apply_auth_opts(ydl_opts, url)

        # Add ffmpeg location if available
        if self.ffmpeg_available and self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = os.path.dirname(self.ffmpeg_path)

        if self.download_type.get() == "video":
            quality = self.quality.get()
            video_format = self.video_format.get()
            cap = self._quality_to_height(quality)  # None == Best (no cap)
            # Effective height: prefer the probed value when we have it.
            eff_h = cap if target_height is None else target_height
            # YouTube only serves H.264 up to 1080p; anything taller is usually
            # VP9/AV1. Instead of slow MP4 transcoding, save those as MKV.
            needs_mkv_fallback = (eff_h is None) or (eff_h > 1080)

            if self.ffmpeg_available:
                # Pick the highest available resolution; prefer native H.264/AAC
                # only as a tie-breaker *within* a resolution, so ≤1080p still
                # grabs H.264 (no re-encode) while 1440p/4K/8K correctly fetch
                # the VP9/AV1 streams YouTube only offers above 1080p.
                ydl_opts['format_sort'] = ['res', 'vcodec:h264', 'acodec:aac']
                if cap is None:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                else:
                    ydl_opts['format'] = (f'bestvideo[height<={cap}]+bestaudio/'
                                          f'best[height<={cap}]')

                if video_format == 'mp4':
                    if needs_mkv_fallback:
                        # 4K+ YouTube streams are commonly VP9/AV1. Muxing to MKV
                        # keeps the original quality and avoids a long transcode.
                        ydl_opts['merge_output_format'] = 'mkv'
                        self.after(0, lambda: self.update_status(
                            "High-res video will be saved as MKV to avoid a slow MP4 conversion."))
                    else:
                        # ≤1080p: native H.264 is available, so just mux into mp4 with
                        # no video re-encode (audio is forced to AAC for mp4).
                        ydl_opts['merge_output_format'] = 'mp4'
                elif video_format in ('mkv', 'webm'):
                    ydl_opts['merge_output_format'] = video_format
                else:
                    # For other formats (avi, mov, flv), merge as mp4 first then convert
                    ydl_opts['merge_output_format'] = 'mp4'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': video_format,  # Note: yt-dlp uses 'prefered' (one r)
                    }]
            else:
                # Without ffmpeg, download pre-merged formats only
                if cap is None:
                    ydl_opts['format'] = 'best'
                else:
                    ydl_opts['format'] = f'best[height<={cap}]/best'
                self.after(0, lambda: self.update_status(
                    "Note: Without ffmpeg, using pre-merged format (may have lower quality)"))
        else:
            audio_format = self.audio_format.get()

            if self.ffmpeg_available:
                # With ffmpeg, extract and convert to chosen format
                bitrate = self.audio_quality.get().split()[0]
                ydl_opts['format'] = 'bestaudio/best'

                # Map format names to codec names
                codec_map = {
                    'mp3': 'mp3',
                    'm4a': 'm4a',
                    'wav': 'wav',
                    'flac': 'flac',
                    'opus': 'opus',
                    'aac': 'aac',
                    'ogg': 'vorbis'  # ogg uses vorbis codec
                }

                acodec = codec_map.get(audio_format, audio_format)

                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': acodec,
                    'preferredquality': bitrate,
                }]
            else:
                # Without ffmpeg, just download best audio
                ydl_opts['format'] = 'bestaudio/best'
                self.after(0, lambda: self.update_status(
                    "Note: Without ffmpeg, downloading audio as-is (no conversion)"))

        return ydl_opts

    def _run_download_and_finish(self, ydl_opts, url, success_message):
        """Run the download with the given options and handle result / errors.

        Shared by download_media() and download_with_playlist_choice().
        Must be called from a worker thread.
        """
        self.after(0, lambda: self.update_status("Download starting..."))

        # Add folder to recent list (touches the dropdown — must run on main thread)
        self.after(0, lambda: self.add_recent_folder(self.output_folder.get()))

        result = self.run_ytdlp_download(ydl_opts, url)
        # Try to get the filename
        if 'requested_downloads' in result and result['requested_downloads']:
            self.downloaded_file_path = result['requested_downloads'][0].get('filepath')

        self.after(0, lambda: self.update_status(success_message))
        self.after(0, lambda: self.progress_bar.set(1))

        # Show completion dialog
        self.after(100, self.show_completion_dialog)

    # Signs that a site changed its pages and the extractor hasn't caught up.
    # These are the errors a fresh engine fixes, so they get the same advice.
    _SITE_BREAKAGE_MARKERS = (
        'unexpected response from webpage request',
        'unable to extract',
        'failed to parse json',
        'unable to download webpage',
    )

    def _is_site_breakage_error(self, error_msg):
        """True if this reads like an extractor that a site update has outrun."""
        low = error_msg.lower()
        return any(marker in low for marker in self._SITE_BREAKAGE_MARKERS)

    @staticmethod
    def _is_http_403_error(error_msg):
        """True for a real HTTP 403, not any message that merely contains '403'.

        The old bare `"403" in error_msg` test also fired on unrelated text --
        including a message an earlier branch had already rewritten -- and on any
        video id or byte count that happened to contain those digits.
        """
        low = error_msg.lower()
        return 'http error 403' in low or '403: forbidden' in low

    def _engine_advice(self):
        """Explain the engine situation in terms the user can act on."""
        return (
            f"Engine in use: {self.engine_version_label()}.\n"
            "The app updates this engine from yt-dlp's nightly channel every time "
            "it starts, so the usual fix is to reopen the app in a day or two, "
            "once a fix has shipped. Updating the app itself won't change this."
        )

    def _handle_download_error(self, e, url=None):
        """Format and display a download error. Must be called from a worker thread."""
        error_msg = str(e)

        # Sign-in / age / bot / members wall (and unreadable cookie stores): keep
        # these out of the status box and route them through the sign-in dialog.
        if self._route_auth_failure(url, error_msg):
            self.after(0, lambda: self.progress_bar.set(0))
            return

        handled = False

        if self._is_js_challenge_error(error_msg):
            runtime_args = self._get_js_runtime_args()
            if runtime_args:
                runtime_note = (
                    "A JavaScript runtime was detected and will be used automatically. "
                    "If this keeps happening, restart the app so the engine can finish updating."
                )
            else:
                runtime_note = (
                    "No JavaScript runtime was found yet. The app downloads Deno "
                    "automatically the first time it's needed — give it a moment and "
                    "try again. If it keeps failing, install Deno or Node.js 22+ and "
                    "restart the app."
                )
            error_msg = (
                "YouTube needs extra JavaScript challenge support for this video.\n\n"
                f"{runtime_note}\n\n"
                f"Technical details: {error_msg}"
            )
            handled = True

        # A real 403 almost always means the engine is behind what the site now
        # serves. Point at the engine, not at an app update -- an app release does
        # nothing for this unless one happens to be cut.
        elif self._is_http_403_error(error_msg):
            error_msg = (
                "HTTP 403: the site refused the download.\n\n"
                "This usually means the site changed how it serves video and the "
                "download engine hasn't caught up yet.\n\n"
                f"{self._engine_advice()}\n\n"
                f"Technical details: {error_msg}"
            )
            handled = True

        # Same root cause, different symptom -- and not necessarily YouTube, so
        # this must not blame it the way the old message did unconditionally.
        elif self._is_site_breakage_error(error_msg):
            error_msg = (
                "This site changed something and the download engine couldn't read "
                "the page.\n\n"
                f"{self._engine_advice()}\n\n"
                f"Technical details: {error_msg}"
            )
            handled = True

        if not handled:
            error_msg = f"{error_msg}\n\n(Engine in use: {self.engine_version_label()}.)"

        self.after(0, lambda: self.update_status(f"Error: {error_msg}"))
        self.after(0, lambda: self.progress_bar.set(0))

    def download_media(self, url):
        try:
            self._await_engine()
            self.after(0, lambda: self.update_status(f"Peeping that URL: {url}", append=False))

            # Pre-scan: detect playlists and (for single videos) the max available
            # resolution.  extract_flat='in_playlist' keeps playlist scans fast while
            # still returning full formats for a single video.
            ydl_opts_check = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',
            }
            self._apply_auth_opts(ydl_opts_check, url)

            info = None
            is_playlist = False
            try:
                # Prefer the auto-updated engine: extraction is the part that
                # breaks when a site changes, so probing with the frozen-in
                # library would reintroduce the staleness we just fixed.
                if getattr(sys, 'frozen', False) and self._have_ytdlp_exe():
                    info = self._probe_with_exe(ydl_opts_check, url)
                else:
                    with yt_dlp.YoutubeDL(ydl_opts_check) as ydl:
                        info = ydl.extract_info(url, download=False)
                is_playlist = bool(info) and 'entries' in info
            except Exception as pre_e:
                pre_error_msg = str(pre_e)
                # If this looks like a sign-in wall, offer the sign-in popup
                # instead of failing. Capture the text now; Python clears
                # exception variables before delayed Tk callbacks run.
                if self._route_auth_failure(url, pre_error_msg):
                    return
                # Otherwise (network/other) don't abort — fall back to a single-item
                # download with the fresh engine, which may still succeed.
                self.after(0, lambda: self.update_status(
                    "Couldn't pre-scan the URL; trying as a single download..."))

            # Handle playlist - always ask user
            if is_playlist:
                playlist_title = info.get('title', 'Unknown Playlist')
                entry_count = len(list(info.get('entries', [])))

                self.after(0, lambda: self.update_status(
                    f"Playlist detected: '{playlist_title}' ({entry_count} items)"))

                # Ask user in a dialog
                self.after(0, lambda: self.ask_playlist_download(url, playlist_title, entry_count))
                return

            # Single video: work out the target height so we can warn when a
            # high-res mp4 request will be saved as mkv to avoid conversion.
            # target_h is None when we couldn't determine it (Best on a URL we
            # failed to pre-scan) — treated downstream as high-res.
            cap = self._quality_to_height(self.quality.get())
            max_h = 0
            if info and info.get('formats'):
                try:
                    max_h = max((f.get('height') or 0) for f in info['formats'])
                except ValueError:
                    max_h = 0
            if max_h:
                target_h = max_h if cap is None else min(cap, max_h)
            else:
                target_h = cap  # couldn't probe — fall back to the cap (None == Best)

            wants_highres_notice = (
                self.download_type.get() == "video"
                and self.video_format.get() == "mp4"
                and self.ffmpeg_available
                and self.ask_hires_codec
                and target_h is not None and target_h >= 2160
            )
            if wants_highres_notice:
                self.after(0, lambda h=target_h: self.ask_highres_mkv_notice(url, h))
                return

            ydl_opts = self._build_ydl_opts(noplaylist=True, target_height=target_h, url=url)
            self._run_download_and_finish(ydl_opts, url,
                                          "Download completed! Yummy output folder so stuffed mmm!")

        except Exception as e:
            self._handle_download_error(e, url)
        finally:
            self.is_downloading = False
            self.after(0, lambda: self.download_btn.configure(state="normal", text="DOWNLOAD"))

    def ask_playlist_download(self, url, playlist_title, count):
        result = messagebox.askyesnocancel(
            "Playlist Detected",
            f"'{playlist_title}' contains {count} items.\n\n"
            f"Yes = Download entire playlist\n"
            f"No = Download single video only\n"
            f"Cancel = Cancel download"
        )

        if result is None:  # Cancel
            self.update_status("Download cancelled")
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="DOWNLOAD")
            self.progress_bar.set(0)
            return

        # Continue download in thread
        thread = threading.Thread(
            target=self.download_with_playlist_choice,
            args=(url, result),
            daemon=True
        )
        thread.start()

    def download_with_playlist_choice(self, url, download_all):
        try:
            ydl_opts = self._build_ydl_opts(noplaylist=not download_all, url=url)
            self._run_download_and_finish(ydl_opts, url,
                                          "You did it you downloaded yay! Check your output folder!")

        except Exception as e:
            self._handle_download_error(e, url)
        finally:
            self.is_downloading = False
            self.after(0, lambda: self.download_btn.configure(state="normal", text="DOWNLOAD"))

    def ask_highres_mkv_notice(self, url, target_h):
        """Warn that a high-res mp4 request will be saved as mkv.

        Runs on the main thread. On confirm it kicks off the download in a worker
        thread and lets yt-dlp mux high-res streams without conversion.
        """
        res_label = "8K" if target_h >= 4320 else "4K" if target_h >= 2160 else f"{target_h}p"

        dialog = ctk.CTkToplevel(self)
        dialog.title("Woah there big guy!")
        dialog.configure(fg_color=self.colors['bg'])
        dialog.geometry("500x250")
        dialog.resizable(False, False)
        dialog.transient(self)
        self.set_toplevel_icon(dialog)

        remember_var = ctk.BooleanVar(value=False)

        content = ctk.CTkFrame(dialog, fg_color=self.colors['bg'])
        content.pack(expand=True, fill="both", padx=28, pady=(22, 16))

        ctk.CTkLabel(
            content,
            text=f"This is a {res_label} video.\n"
                 "4K+ videos will be downloaded as .mkv in order to ensure compatibility with video editing software.",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors['text'], justify="center", wraplength=430,
        ).pack(anchor="center", pady=(0, 18))

        ctk.CTkCheckBox(content, text="Don't ask again",
                        variable=remember_var, font=ctk.CTkFont(size=12),
                        fg_color=self.colors['purple']).pack(anchor="center", pady=(14, 2))

        btn_row = ctk.CTkFrame(content, fg_color=self.colors['bg'])
        btn_row.pack(anchor="center", pady=(16, 0))

        def cancel():
            dialog.destroy()
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="DOWNLOAD")
            self.progress_bar.set(0)
            self.update_status("Download cancelled")

        def confirm():
            if remember_var.get():
                self.ask_hires_codec = False
                self.save_config()
            dialog.destroy()
            threading.Thread(
                target=self._download_single_highres_mkv,
                args=(url, target_h),
                daemon=True,
            ).start()

        ctk.CTkButton(btn_row, text="Cancel", command=cancel, width=120, height=38,
                      fg_color=self.colors['frame_bg'], hover_color=self.colors['dark_purple']).pack(side="left", padx=(0, 36))
        ctk.CTkButton(btn_row, text="Download MKV", command=confirm, width=130, height=38,
                      fg_color=self.colors['button'], hover_color=self.colors['purple']).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.after(120, dialog.grab_set)  # modal once the window exists

    def _download_single_highres_mkv(self, url, target_height=None):
        """Worker: download a single high-res video as mkv without transcoding."""
        try:
            ydl_opts = self._build_ydl_opts(noplaylist=True, target_height=target_height, url=url)
            self._run_download_and_finish(ydl_opts, url,
                                          "Download completed! Yummy output folder so stuffed mmm!")
        except Exception as e:
            self._handle_download_error(e, url)
        finally:
            self.is_downloading = False
            self.after(0, lambda: self.download_btn.configure(state="normal", text="DOWNLOAD"))

    def start_download(self):
        url = self.url_entry.get().strip()

        if not url:
            messagebox.showwarning("No URL", "kinda need a URL to download lol!")
            return

        if self.is_downloading:
            messagebox.showinfo("Download in Progress", "Please wait for the current download to finish!")
            return

        output_dir = self.output_folder.get()
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception:
                messagebox.showerror("bruh", "Kinda need a valid output folder to output into a folder...")
                return

        self.is_downloading = True
        self.download_btn.configure(state="disabled", text="Downloading...")
        self.progress_bar.set(0)
        # Fresh attempt: go back to yt-dlp's own default clients. Only the
        # sign-in retry widens them (see _apply_auth_opts).
        self._widen_player_clients = False

        # Start download in separate thread
        thread = threading.Thread(target=self.download_media, args=(url,), daemon=True)
        thread.start()


if __name__ == "__main__":
    app = VideoDownloaderApp()
    app.mainloop()
