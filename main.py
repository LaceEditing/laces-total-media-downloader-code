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
    for _fname in ('BubblegumSans-Regular.ttf', 'bartino.ttf'):
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
    CURRENT_VERSION = "3.6.1"
    # GitHub repository for updates
    GITHUB_REPO = "LaceEditing/laces-total-media-downloader"

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
        self._delete_legacy_cookiefile()

        self._recent_display_to_path = {}  # Populated by update_recent_dropdown
        self.ytdlp_exe_path = None  # Will be set if yt-dlp.exe is downloaded
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
            self.bartino_font_path = os.path.join(base_path, 'assets', 'fonts', 'bartino.ttf')

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

    def update_ytdlp(self):
        """Automatically update yt-dlp to the latest version to prevent HTTP 403 errors"""
        # Skip in sandboxed Linux environments where we can't write or pip install
        if sys.platform.startswith('linux'):
            if os.path.exists('/.flatpak-info') or os.environ.get('SNAP'):
                return

        def update():
            try:
                # Check if we're running as a frozen executable (PyInstaller)
                is_frozen = getattr(sys, 'frozen', False)

                if is_frozen:
                    # For frozen executable, download yt-dlp binary and keep it updated
                    if hasattr(sys, '_MEIPASS'):
                        app_dir = os.path.dirname(sys.executable)
                    else:
                        app_dir = os.path.dirname(os.path.abspath(__file__))

                    # Choose the right STANDALONE binary for the platform. On
                    # Linux/macOS the plain "yt-dlp" asset is a Python zipapp that
                    # needs a system Python — use the self-contained "yt-dlp_linux"
                    # / "yt-dlp_macos" builds so it works on machines without Python.
                    base_url = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/'
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

                    ytdlp_exe_path = os.path.join(app_dir, ytdlp_filename)

                    # If we already have a usable binary, adopt it right away and
                    # only re-download when it's actually out of date — saves the
                    # ~30 MB download on every launch.
                    have_local = (os.path.exists(ytdlp_exe_path)
                                  and os.path.getsize(ytdlp_exe_path) >= min_size)
                    if have_local:
                        self.ytdlp_exe_path = ytdlp_exe_path
                        installed = self._get_local_ytdlp_version(ytdlp_exe_path)
                        latest = self._get_latest_ytdlp_version()
                        if installed and latest and installed == latest:
                            self.after(0, lambda v=installed: self.update_status(
                                f"yt-dlp is up to date ({v})."))
                            return

                    # Download to a temp file first, then rename (atomic-ish)
                    temp_path = ytdlp_exe_path + '.tmp'
                    try:
                        response = requests.get(ytdlp_url, timeout=60)
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
                            self.after(0, lambda: self.update_status("yt-dlp updated successfully!"))
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
                    # For development/unfrozen, update via pip
                    python_executable = sys.executable
                    subprocess.run(
                        [python_executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"],
                        capture_output=True,
                        timeout=60,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
            except Exception as e:
                # Keep using an existing local binary if we have one; only clear
                # the path when there's nothing usable to fall back on.
                if not (getattr(self, 'ytdlp_exe_path', None)
                        and os.path.exists(self.ytdlp_exe_path)):
                    self.ytdlp_exe_path = None
                self.after(0, lambda: self.update_status(f"yt-dlp update failed: {e}"))

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
        """Return the latest yt-dlp release tag from GitHub, or None."""
        try:
            response = requests.get(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", timeout=10)
            if response.status_code == 200:
                return response.json().get('tag_name', '').strip() or None
        except Exception:
            pass
        return None

    def run_ytdlp_download(self, ydl_opts, url):
        """Run yt-dlp download using either external exe or bundled library"""
        is_frozen = getattr(sys, 'frozen', False)

        # If frozen and we have an external yt-dlp.exe, use it via subprocess
        if is_frozen and hasattr(self, 'ytdlp_exe_path') and self.ytdlp_exe_path and os.path.exists(self.ytdlp_exe_path):
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

    def _run_ytdlp_subprocess(self, ydl_opts, url):
        """Run yt-dlp using external executable via subprocess"""
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
        """Attach cookies + bot/age-gate resilience to a yt-dlp options dict."""
        src = self.cookies_source

        if src == 'file' and self.cookies_file and os.path.exists(self.cookies_file):
            ydl_opts['cookiefile'] = self.cookies_file
        elif src == 'none' and self._is_youtube_url(url):
            src = self._get_default_browser()
        if src and src not in ('none', 'file'):
            ydl_opts['cookiesfrombrowser'] = (src,)

        # Extra YouTube clients help with some age gates / bot checks even
        # without cookies; 'default' keeps the normal clients available too.
        extractor_args = ydl_opts.setdefault('extractor_args', {})
        yt_args = extractor_args.setdefault('youtube', {})
        yt_args['player_client'] = ['default', 'tv']
        self._apply_js_runtime_opts(ydl_opts)
        return ydl_opts

    def _get_bundled_base_paths(self):
        """Directories to search for bundled binaries (ffmpeg, deno, etc.)."""
        paths = []
        if getattr(sys, 'frozen', False):
            # PyInstaller onefile self-extracts bundled binaries to _MEIPASS;
            # also check the folder the .exe itself lives in.
            paths.append(sys._MEIPASS)
            paths.append(os.path.dirname(sys.executable))
        else:
            paths.append(os.path.dirname(os.path.abspath(__file__)))
        return paths

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
        """Folder to drop an auto-downloaded deno into (next to the .exe / script)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

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
        """True if the error means the video needs sign-in, or that reading
        browser cookies failed."""
        low = str(e).lower()
        signals = (
            'confirm your age', 'age-restricted', 'age restricted', 'inappropriate',
            "confirm you're not a bot", 'not a bot', 'sign in to confirm', 'sign in to view',
            'members-only', 'members only', 'join this channel', 'private video',
            'this video is private', 'login required', 'requires authentication',
            'use --cookies', 'use --cookies-from-browser', 'cookies are no longer valid',
            'pass cookies to yt-dlp', 'exporting youtube cookies',
            # browser-cookie extraction problems should use the same sign-in prompt
            'could not copy', 'failed to decrypt', 'unable to decrypt', 'cookiesfrombrowser',
        )
        return any(s in low for s in signals)

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

    def prompt_signin(self, url, error_msg=None):
        """Popup shown when a video needs sign-in. Lets the user open their
        browser to log into YouTube, then retries the download using that
        browser's cookies. Runs on the main thread."""
        browser = self._get_default_browser()

        dialog = ctk.CTkToplevel(self)
        dialog.title("Sign-in required")
        dialog.configure(fg_color=self.colors['bg'])
        dialog.geometry("520x240")
        dialog.resizable(False, False)
        dialog.transient(self)
        self.set_toplevel_icon(dialog)

        ctk.CTkLabel(
            dialog,
            text="The video you're trying to download is age-restricted. "
                 "Please sign in to a YouTube account that's able to access it.",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors['text'], justify="left", wraplength=460,
        ).pack(anchor="w", padx=24, pady=(24, 14))

        initial_status = ""
        if error_msg and self.cookies_source != 'none':
            initial_status = (
                "Still couldn't access it with the current sign-in. If you're using "
                "Chrome, Edge, or Brave on Windows, try signing in with Firefox."
            )

        if initial_status:
            ctk.CTkLabel(dialog, text=initial_status, font=ctk.CTkFont(size=11),
                         text_color=self.colors['purple'], justify="left", wraplength=460).pack(
                anchor="w", padx=24, pady=(0, 4))

        def sign_in():
            try:
                webbrowser.open("https://www.youtube.com")
            except Exception:
                pass
            self.cookies_source = browser or 'none'
            dialog.destroy()
            self.update_status("Sign in to YouTube, then try the download again.", append=False)

        def cancel():
            dialog.destroy()
            self.update_status("Download cancelled — sign-in needed for this video.")

        row = ctk.CTkFrame(dialog, fg_color=self.colors['bg'])
        row.pack(fill="x", padx=24, pady=(18, 18))
        ctk.CTkButton(row, text="Cancel", command=cancel, width=120, height=40,
                      fg_color=self.colors['frame_bg'],
                      hover_color=self.colors['dark_purple']).pack(side="left")
        ctk.CTkButton(row, text="Sign In", command=sign_in, width=170, height=40,
                      fg_color=self.colors['button'],
                      hover_color=self.colors['purple']).pack(side="right")

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

    def _handle_download_error(self, e, url=None):
        """Format and display a download error. Must be called from a worker thread."""
        error_msg = str(e)

        # Sign-in / age / bot / members wall: keep these out of the status box and
        # route them through the sign-in dialog, including retry failures.
        if url and self._is_auth_error(error_msg):
            self.after(0, lambda msg=error_msg: self.prompt_signin(url, msg))
            self.after(0, lambda: self.progress_bar.set(0))
            return

        if self._is_js_challenge_error(error_msg):
            runtime_args = self._get_js_runtime_args()
            if runtime_args:
                runtime_note = (
                    "A JavaScript runtime was detected and will be used automatically. "
                    "If this keeps happening, restart the app so yt-dlp can finish updating."
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

        # Check for HTTP 403 errors (common when yt-dlp is outdated)
        if "403" in error_msg or "Forbidden" in error_msg:
            is_frozen = getattr(sys, 'frozen', False)
            if is_frozen:
                error_msg = (
                    "HTTP 403 Error: YouTube has changed something!\n\n"
                    "Please check for app updates (you should see an update notification if available).\n"
                    "If no update is available, please report this issue!\n\n"
                    f"Technical details: {error_msg}"
                )
            else:
                error_msg = (
                    "HTTP 403 Error: YouTube has changed something!\n\n"
                    "yt-dlp is updating in the background. Please try again in a moment.\n"
                    "If the issue persists, restart the application.\n\n"
                    f"Technical details: {error_msg}"
                )

        self.after(0, lambda: self.update_status(f"Error: {error_msg}"))
        self.after(0, lambda: self.progress_bar.set(0))

    def download_media(self, url):
        try:
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
                with yt_dlp.YoutubeDL(ydl_opts_check) as ydl:
                    info = ydl.extract_info(url, download=False)
                    is_playlist = bool(info) and 'entries' in info
            except Exception as pre_e:
                pre_error_msg = str(pre_e)
                # If this looks like a sign-in wall, offer the sign-in popup
                # instead of failing. Capture the text now; Python clears
                # exception variables before delayed Tk callbacks run.
                if self._is_auth_error(pre_error_msg):
                    self.after(0, lambda msg=pre_error_msg: self.prompt_signin(url, msg))
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

        # Start download in separate thread
        thread = threading.Thread(target=self.download_media, args=(url,), daemon=True)
        thread.start()


if __name__ == "__main__":
    app = VideoDownloaderApp()
    app.mainloop()
