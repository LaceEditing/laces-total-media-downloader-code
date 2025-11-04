import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp
import threading
import os
import sys
from pathlib import Path
import re
import shutil
import subprocess
import json
from pygame import mixer
import requests
from packaging import version
import tempfile


class VideoDownloaderApp(ctk.CTk):
    # Version of the app - update this with each release
    CURRENT_VERSION = "3.1.3"
    # GitHub repository for updates
    GITHUB_REPO = "LaceEditing/laces-total-media-downloader"

    def __init__(self, CURRENT_VERSION=CURRENT_VERSION):
        super().__init__()

        # Window setup
        self.title(f"Hey besties let's download those files! (v{CURRENT_VERSION})")
        self.geometry("950x700")
        self.minsize(900, 650)

        # Set window icon
        self.set_icon()

        # Initialize pygame mixer for sounds
        try:
            mixer.init()
        except:
            pass

        # Dark mode state - default to dark mode
        self.is_dark_mode = True

        # Color schemes - Light mode
        self.light_colors = {
            'bg': "#E8E4F3",
            'purple': "#9B6BD8",
            'dark_purple': "#8055C4",
            'pink': "#D891E8",
            'button': "#B88ED8",
            'frame_bg': "white",
            'text': "#333333"
        }

        # Color schemes - Dark mode
        self.dark_colors = {
            'bg': "#1a1625",
            'purple': "#B88ED8",
            'dark_purple': "#9B6BD8",
            'pink': "#D891E8",
            'button': "#7d5ba6",
            'frame_bg': "#2d2438",
            'text': "#E8E4F3"
        }

        # Set initial colors to dark mode
        self.colors = self.dark_colors

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
        self.recent_folders = self.load_recent_folders()
        self.ytdlp_exe_path = None  # Will be set if yt-dlp.exe is downloaded

        # Load custom fonts
        self.load_custom_fonts()

        self.setup_ui()

        # Show ffmpeg warning if not available
        if not self.ffmpeg_available:
            self.after(500, self.show_ffmpeg_warning)

        # Update yt-dlp on startup to prevent HTTP 403 errors
        self.after(100, self.update_ytdlp)

        # Check for updates on startup
        self.after(1000, self.check_for_updates)

    def toggle_dark_mode(self):
        """Toggle between light and dark mode"""
        self.is_dark_mode = not self.is_dark_mode
        self.colors = self.dark_colors if self.is_dark_mode else self.light_colors

        # Update appearance mode
        ctk.set_appearance_mode("dark" if self.is_dark_mode else "light")

        # Update all UI elements
        self.configure(fg_color=self.colors['bg'])
        self.main_frame.configure(fg_color=self.colors['bg'])
        self.header_frame.configure(fg_color=self.colors['bg'])

        # Update title
        self.title_label.configure(text_color=self.colors['purple'])

        # Update all frames
        for frame in [self.url_frame, self.options_frame, self.progress_frame, self.output_frame]:
            frame.configure(fg_color=self.colors['frame_bg'])

        # Update labels
        for label in [self.url_label, self.options_label, self.progress_label, self.output_label]:
            label.configure(text_color=self.colors['text'])

        # Update small labels
        for label in [self.type_label, self.quality_label, self.format_label]:
            label.configure(text_color=self.colors['text'])

        # Update entry fields
        self.url_entry.configure(border_color=self.colors['purple'], fg_color=self.colors['frame_bg'])
        self.output_entry.configure(border_color=self.colors['purple'], fg_color=self.colors['frame_bg'])

        # Update radio buttons
        self.video_radio.configure(fg_color=self.colors['purple'], hover_color=self.colors['dark_purple'])
        self.audio_radio.configure(fg_color=self.colors['purple'], hover_color=self.colors['dark_purple'])

        # Update option menus
        for menu in [self.video_quality_menu, self.audio_quality_menu,
                     self.video_format_menu, self.audio_format_menu, self.recent_dropdown]:
            menu.configure(fg_color=self.colors['button'],
                           button_color=self.colors['purple'],
                           button_hover_color=self.colors['dark_purple'])

        # Update buttons
        self.download_btn.configure(fg_color=self.colors['button'], hover_color=self.colors['purple'])
        self.browse_btn.configure(fg_color=self.colors['pink'], hover_color=self.colors['purple'])

        # Update progress bar
        self.progress_bar.configure(progress_color=self.colors['purple'])

        # Update dark mode button
        self.dark_mode_btn.configure(
            text="☀️" if self.is_dark_mode else "🌙",
            fg_color=self.colors['button'],
            hover_color=self.colors['purple']
        )

        # Update container frames
        for frame in [self.type_quality_frame, self.type_frame, self.quality_frame,
                      self.format_frame, self.output_row]:
            frame.configure(fg_color=self.colors['frame_bg'])

    def set_icon(self):
        """Set window icon from assets/icons folder"""
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            # On Linux, prefer PNG icons
            if sys.platform.startswith('linux'):
                icon_paths = [
                    os.path.join(base_path, 'assets', 'icons', 'icon.png'),
                    os.path.join(base_path, 'assets', 'icons', 'icon.ico'),
                ]
            else:
                # On Windows, prefer ICO
                icon_paths = [
                    os.path.join(base_path, 'assets', 'icons', 'icon.ico'),
                    os.path.join(base_path, 'assets', 'icons', 'icon.png'),
                ]

            for icon_path in icon_paths:
                if os.path.exists(icon_path):
                    if icon_path.endswith('.png'):
                        # For PNG icons, use PhotoImage (works cross-platform)
                        from PIL import Image, ImageTk
                        img = Image.open(icon_path)
                        photo = ImageTk.PhotoImage(img)
                        self.iconphoto(True, photo)
                        # Keep a reference to prevent garbage collection
                        self._icon_photo = photo
                    else:
                        # For ICO icons (Windows)
                        self.iconbitmap(icon_path)
                    break
        except:
            # Fallback: try iconbitmap method
            try:
                if getattr(sys, 'frozen', False):
                    base_path = sys._MEIPASS
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))

                icon_path = os.path.join(base_path, 'assets', 'icons', 'icon.png')
                if os.path.exists(icon_path):
                    self.iconphoto(True, icon_path)
            except:
                pass

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

            # Check if fonts exist
            self.has_bubblegum = os.path.exists(self.bubblegum_font_path)
            self.has_bartino = os.path.exists(self.bartino_font_path)
        except:
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
            except:
                pass  # Silently fail if update check fails

        # Run update check in background thread
        thread = threading.Thread(target=check, daemon=True)
        thread.start()

    def update_ytdlp(self):
        """Automatically update yt-dlp to the latest version to prevent HTTP 403 errors"""
        def update():
            try:
                # Check if we're running as a frozen executable (PyInstaller)
                is_frozen = getattr(sys, 'frozen', False)

                if is_frozen:
                    # For frozen executable, download yt-dlp.exe and keep it updated
                    # Determine the directory where the exe is located
                    if hasattr(sys, '_MEIPASS'):
                        # Running from temp folder
                        app_dir = os.path.dirname(sys.executable)
                    else:
                        app_dir = os.path.dirname(os.path.abspath(__file__))

                    ytdlp_exe_path = os.path.join(app_dir, 'yt-dlp.exe')

                    # Download latest yt-dlp.exe
                    ytdlp_url = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'

                    response = requests.get(ytdlp_url, timeout=30)
                    if response.status_code == 200:
                        with open(ytdlp_exe_path, 'wb') as f:
                            f.write(response.content)

                        # Store the path for later use
                        self.ytdlp_exe_path = ytdlp_exe_path
                        # Thread-safe status update
                        self.after(0, lambda: self.update_status("yt-dlp updated successfully!"))
                else:
                    # For development/unfrozen, update via pip
                    python_executable = sys.executable
                    subprocess.run(
                        [python_executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                        capture_output=True,
                        timeout=30,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
            except Exception as e:
                # Store None if update fails
                self.ytdlp_exe_path = None

        # Run update in background thread so it doesn't block UI
        thread = threading.Thread(target=update, daemon=True)
        thread.start()

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

        # Add merge output format
        if 'merge_output_format' in ydl_opts:
            cmd.extend(['--merge-output-format', ydl_opts['merge_output_format']])

        # Add ffmpeg location
        if 'ffmpeg_location' in ydl_opts:
            cmd.extend(['--ffmpeg-location', ydl_opts['ffmpeg_location']])

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
                    except:
                        pass
                elif 'has already been downloaded' in line or 'Destination:' in line:
                    # Thread-safe status update
                    self.after(0, lambda l=line: self.update_status(l, append=False))
            elif line:
                # Show other important messages
                if 'Extracting' in line or 'Merging' in line or 'Converting' in line:
                    # Thread-safe status update
                    self.after(0, lambda l=line: self.update_status(l, append=False))

        process.wait()

        if process.returncode != 0:
            raise Exception(f"yt-dlp.exe failed with return code {process.returncode}")

        # Return a minimal result object
        return {'title': 'Downloaded'}

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
            try:
                # Show download progress
                self.after(0, lambda: self.update_status("Downloading update...", append=False))

                # Download the new exe
                response = requests.get(download_url, stream=True)
                total_size = int(response.headers.get('content-length', 0))

                # Get current exe path
                if getattr(sys, 'frozen', False):
                    current_exe = os.path.abspath(sys.executable)
                else:
                    current_exe = os.path.abspath(__file__)

                current_dir = os.path.dirname(current_exe)
                temp_new_exe = os.path.join(current_dir, 'LacesTotalMediaDownloader_new.exe')

                # Download with progress
                downloaded = 0
                with open(temp_new_exe, 'wb') as f:
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
                if not os.path.exists(temp_new_exe) or os.path.getsize(temp_new_exe) < 1000000:
                    raise Exception("Downloaded file is invalid or too small")

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
                        f.write(f'move /Y "{temp_new_exe}" "{current_exe}"\n')
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
                        f"Update downloaded to:\n{temp_new_exe}\n\nPlease manually replace the current executable and restart."
                    ))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Update Failed",
                                                           f"Failed to download update:\n{str(e)}\n\nPlease download the update manually from GitHub."))

        thread = threading.Thread(target=download, daemon=True)
        thread.start()

    def load_recent_folders(self):
        """Load recent folders from config file"""
        try:
            config_path = Path.home() / '.lace_downloader_config.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    data = json.load(f)
                    return data.get('recent_folders', [])
        except:
            pass
        return []

    def save_recent_folders(self):
        """Save recent folders to config file"""
        try:
            config_path = Path.home() / '.lace_downloader_config.json'
            with open(config_path, 'w') as f:
                json.dump({'recent_folders': self.recent_folders}, f)
        except:
            pass

    def add_recent_folder(self, folder):
        """Add folder to recent list"""
        if folder in self.recent_folders:
            self.recent_folders.remove(folder)
        self.recent_folders.insert(0, folder)
        self.recent_folders = self.recent_folders[:10]  # Keep 10 recent
        self.save_recent_folders()
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
        msg = (
            "FFmpeg Not Found!\n\n"
            "FFmpeg is required for:\n"
            "• Merging video + audio for best quality\n"
            "• Converting to MP3 for audio downloads\n\n"
            "The app will still work but will download single-format files.\n\n"
            "To add FFmpeg:\n"
            "1. Download ffmpeg from https://ffmpeg.org/download.html\n"
            "2. Place ffmpeg.exe in the same folder as this app\n"
            "   OR install it system-wide\n\n"
            "Then restart the app!"
        )
        messagebox.showwarning("FFmpeg Not Found", msg)

    def setup_ui(self):
        # Main container with padding
        self.main_frame = ctk.CTkFrame(self, fg_color=self.colors['bg'])
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Header row with title and dark mode toggle
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color=self.colors['bg'])
        self.header_frame.pack(fill="x", pady=(0, 20))

        # Title with custom font
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

        # Dark mode toggle button
        self.dark_mode_btn = ctk.CTkButton(
            self.header_frame,
            text="🌙",
            command=self.toggle_dark_mode,
            width=50,
            height=50,
            font=ctk.CTkFont(size=24),
            fg_color=self.colors['button'],
            hover_color=self.colors['purple'],
            corner_radius=25
        )
        self.dark_mode_btn.pack(side="right")

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
            values=["Best", "1080p", "720p", "480p", "360p"],
            variable=self.quality,
            width=100,
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

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.set(folder)
            self.add_recent_folder(folder)

    def update_recent_dropdown(self):
        """Update the recent folders dropdown"""
        if self.recent_folders:
            # Get folder names for display
            folder_names = []
            for folder in self.recent_folders[:10]:
                folder_name = Path(folder).name or folder
                # Truncate if too long
                if len(folder_name) > 20:
                    folder_name = folder_name[:17] + "..."
                folder_names.append(folder_name)

            self.recent_dropdown.configure(values=folder_names)
        else:
            self.recent_dropdown.configure(values=["No recent folders"])

    def on_recent_selected(self, choice):
        """Handle recent folder selection"""
        if choice and choice != "No recent folders":
            # Find the full path from the display name
            for i, folder in enumerate(self.recent_folders[:10]):
                folder_name = Path(folder).name or folder
                if len(folder_name) > 20:
                    folder_name = folder_name[:17] + "..."
                if folder_name == choice:
                    self.output_folder.set(self.recent_folders[i])
                    break

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
        except:
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
        self.status_text.insert("end", f"{message}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            try:
                # Parse percentage
                percent_str = d.get('_percent_str', '0%').strip()
                percent = float(percent_str.replace('%', '')) / 100.0

                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                downloaded = d.get('_downloaded_bytes_str', 'N/A')
                total = d.get('_total_bytes_str', 'N/A')

                # Update progress bar with actual percentage
                self.progress_bar.set(percent)

                status_msg = f"Downloading: {percent_str} ({downloaded}/{total})\n"
                status_msg += f"Speed: {speed} | ETA: {eta}"
                self.update_status(status_msg, append=False)
            except Exception as e:
                pass
        elif d['status'] == 'finished':
            self.progress_bar.set(1.0)
            self.update_status("So Close! Almost done...", append=False)

    def download_media(self, url):
        try:
            self.update_status(f"Peeping that URL: {url}", append=False)

            # Check if it's a playlist
            ydl_opts_check = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts_check) as ydl:
                info = ydl.extract_info(url, download=False)
                is_playlist = 'entries' in info

            # Handle playlist - always ask user
            if is_playlist:
                playlist_title = info.get('title', 'Unknown Playlist')
                entry_count = len(list(info.get('entries', [])))

                self.update_status(f"Playlist detected: '{playlist_title}' ({entry_count} items)")

                # Ask user in a dialog
                self.after(0, lambda: self.ask_playlist_download(url, playlist_title, entry_count))
                return
            else:
                noplaylist = True

            # Download options
            output_template = f"{self.output_folder.get()}/%(title)s.%(ext)s"
            ydl_opts = {
                'outtmpl': output_template,
                'noplaylist': noplaylist,
            }

            # Add ffmpeg location if available
            if self.ffmpeg_available and self.ffmpeg_path:
                ydl_opts['ffmpeg_location'] = os.path.dirname(self.ffmpeg_path)

            if self.download_type.get() == "video":
                quality = self.quality.get()
                video_format = self.video_format.get()

                if self.ffmpeg_available:
                    # With ffmpeg, we can merge video+audio for best quality
                    if quality == "Best":
                        ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    else:
                        height = quality.replace('p', '')
                        ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'

                    # Set merge output format
                    if video_format in ['mp4', 'mkv', 'webm']:
                        ydl_opts['merge_output_format'] = video_format
                    else:
                        # For other formats, merge as mp4 first then convert
                        ydl_opts['merge_output_format'] = 'mp4'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': video_format,  # Note: yt-dlp uses 'prefered' (one r)
                        }]

                    # For MP4 format, ensure H.264+AAC codecs for Premiere Pro compatibility
                    # This prevents issues with VP9/Opus codecs that Premiere Pro doesn't support
                    if video_format == 'mp4':
                        if 'postprocessors' not in ydl_opts:
                            ydl_opts['postprocessors'] = []
                        ydl_opts['postprocessors'].append({
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        })
                        # Force re-encode to H.264 (libx264) video + AAC audio for maximum compatibility
                        # preset=fast for reasonable encoding speed, crf=23 for good quality
                        ydl_opts['postprocessor_args'] = {
                            'videoconvertor': ['-c:v', 'libx264', '-c:a', 'aac', '-preset', 'fast', '-crf', '23']
                        }
                else:
                    # Without ffmpeg, download pre-merged formats only
                    if quality == "Best":
                        ydl_opts['format'] = 'best'
                    else:
                        height = quality.replace('p', '')
                        ydl_opts['format'] = f'best[height<={height}]/best'
                    self.update_status("Note: Without ffmpeg, using pre-merged format (may have lower quality)")
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

                    codec = codec_map.get(audio_format, audio_format)

                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': codec,
                        'preferredquality': bitrate,
                    }]
                else:
                    # Without ffmpeg, just download best audio
                    ydl_opts['format'] = 'bestaudio/best'
                    self.update_status("Note: Without ffmpeg, downloading audio as-is (no conversion)")

            self.update_status("Download starting...")

            # Add folder to recent list
            self.add_recent_folder(self.output_folder.get())

            result = self.run_ytdlp_download(ydl_opts, url)
            # Try to get the filename
            if 'requested_downloads' in result and result['requested_downloads']:
                self.downloaded_file_path = result['requested_downloads'][0].get('filepath')

            self.update_status("Download completed! Yummy output folder so stuffed mmm!")
            self.progress_bar.set(1)

            # Show completion dialog
            self.after(100, self.show_completion_dialog)

        except Exception as e:
            error_msg = str(e)

            # Check for HTTP 403 errors (common when yt-dlp is outdated)
            if "403" in error_msg or "Forbidden" in error_msg:
                is_frozen = getattr(sys, 'frozen', False)
                if is_frozen:
                    # For frozen builds, suggest updating the app
                    error_msg = (
                        "HTTP 403 Error: YouTube has changed something!\n\n"
                        "Please check for app updates (you should see an update notification if available).\n"
                        "If no update is available, please report this issue!\n\n"
                        f"Technical details: {error_msg}"
                    )
                else:
                    # For development builds, yt-dlp should auto-update
                    error_msg = (
                        "HTTP 403 Error: YouTube has changed something!\n\n"
                        "yt-dlp is updating in the background. Please try again in a moment.\n"
                        "If the issue persists, restart the application.\n\n"
                        f"Technical details: {error_msg}"
                    )

            self.update_status(f"Error: {error_msg}")
            self.progress_bar.set(0)
        finally:
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="DOWNLOAD")

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
            output_template = f"{self.output_folder.get()}/%(title)s.%(ext)s"
            ydl_opts = {
                'outtmpl': output_template,
                'noplaylist': not download_all,
            }

            # Add ffmpeg location if available
            if self.ffmpeg_available and self.ffmpeg_path:
                ydl_opts['ffmpeg_location'] = os.path.dirname(self.ffmpeg_path)

            if self.download_type.get() == "video":
                quality = self.quality.get()
                video_format = self.video_format.get()

                if self.ffmpeg_available:
                    if quality == "Best":
                        ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    else:
                        height = quality.replace('p', '')
                        ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'

                    if video_format in ['mp4', 'mkv', 'webm']:
                        ydl_opts['merge_output_format'] = video_format
                    else:
                        ydl_opts['merge_output_format'] = 'mp4'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': video_format,
                        }]

                    # For MP4 format, ensure H.264+AAC codecs for Premiere Pro compatibility
                    # This prevents issues with VP9/Opus codecs that Premiere Pro doesn't support
                    if video_format == 'mp4':
                        if 'postprocessors' not in ydl_opts:
                            ydl_opts['postprocessors'] = []
                        ydl_opts['postprocessors'].append({
                            'key': 'FFmpegVideoConvertor',
                            'preferedformat': 'mp4',
                        })
                        # Force re-encode to H.264 (libx264) video + AAC audio for maximum compatibility
                        # preset=fast for reasonable encoding speed, crf=23 for good quality
                        ydl_opts['postprocessor_args'] = {
                            'videoconvertor': ['-c:v', 'libx264', '-c:a', 'aac', '-preset', 'fast', '-crf', '23']
                        }
                else:
                    if quality == "Best":
                        ydl_opts['format'] = 'best'
                    else:
                        height = quality.replace('p', '')
                        ydl_opts['format'] = f'best[height<={height}]/best'
                    self.update_status("Note: Without ffmpeg, using pre-merged format")
            else:
                audio_format = self.audio_format.get()

                if self.ffmpeg_available:
                    bitrate = self.audio_quality.get().split()[0]
                    ydl_opts['format'] = 'bestaudio/best'

                    codec_map = {
                        'mp3': 'mp3',
                        'm4a': 'm4a',
                        'wav': 'wav',
                        'flac': 'flac',
                        'opus': 'opus',
                        'aac': 'aac',
                        'ogg': 'vorbis'
                    }

                    codec = codec_map.get(audio_format, audio_format)

                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': codec,
                        'preferredquality': bitrate,
                    }]
                else:
                    ydl_opts['format'] = 'bestaudio/best'
                    self.update_status("Note: Without ffmpeg, downloading audio as-is")

            self.update_status("Starting download...")

            # Add folder to recent list
            self.add_recent_folder(self.output_folder.get())

            result = self.run_ytdlp_download(ydl_opts, url)
            if 'requested_downloads' in result and result['requested_downloads']:
                self.downloaded_file_path = result['requested_downloads'][0].get('filepath')

            self.update_status("You did it you downloaded yay! Check your output folder!")
            self.progress_bar.set(1)

            # Show completion dialog
            self.after(100, self.show_completion_dialog)

        except Exception as e:
            error_msg = str(e)

            # Check for HTTP 403 errors (common when yt-dlp is outdated)
            if "403" in error_msg or "Forbidden" in error_msg:
                is_frozen = getattr(sys, 'frozen', False)
                if is_frozen:
                    # For frozen builds, suggest updating the app
                    error_msg = (
                        "HTTP 403 Error: YouTube has changed something!\n\n"
                        "Please check for app updates (you should see an update notification if available).\n"
                        "If no update is available, please report this issue!\n\n"
                        f"Technical details: {error_msg}"
                    )
                else:
                    # For development builds, yt-dlp should auto-update
                    error_msg = (
                        "HTTP 403 Error: YouTube has changed something!\n\n"
                        "yt-dlp is updating in the background. Please try again in a moment.\n"
                        "If the issue persists, restart the application.\n\n"
                        f"Technical details: {error_msg}"
                    )

            self.update_status(f"Error: {error_msg}")
            self.progress_bar.set(0)
        finally:
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="DOWNLOAD")

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
            except:
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