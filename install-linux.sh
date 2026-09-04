#!/usr/bin/env bash
#
# Install a built Linux binary into the current user's desktop environment:
# the app menu, the launcher icon, and $PATH. No root, nothing outside $HOME.
#
#   ./install-linux.sh                     # picks the newest dist/*_linux build
#   ./install-linux.sh path/to/binary      # or name one explicitly
#   ./install-linux.sh --uninstall         # remove everything this installed
#
set -euo pipefail

APP_ID="laces-total-media-downloader"
APP_NAME="Lace's Total Media Downloader"
# Must match VideoDownloaderApp.WM_CLASS_NAME in main.py, or the running window
# won't be tied to this launcher and the taskbar falls back to a generic Tk icon.
# Verified WM_CLASS on X11: "laces-total-media-downloader", "Laces-total-media-downloader".
# This is the instance field, and it also matches this .desktop file's basename,
# which is the other thing desktop environments fall back to.
WM_CLASS="laces-total-media-downloader"

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP_FILE="$DATA_DIR/applications/$APP_ID.desktop"
ICON_FILE="$DATA_DIR/icons/hicolor/32x32/apps/$APP_ID.png"
TARGET="$BIN_DIR/$APP_ID"

here() { cd "$(dirname "${BASH_SOURCE[0]}")" && pwd; }
REPO="$(here)"

refresh_caches() {
    # Best-effort: these are what make the entry show up without a re-login.
    command -v update-desktop-database >/dev/null \
        && update-desktop-database "$DATA_DIR/applications" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null \
        && gtk-update-icon-cache -qtf "$DATA_DIR/icons/hicolor" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$TARGET" "$DESKTOP_FILE" "$ICON_FILE"
    refresh_caches
    echo "Removed $APP_NAME."
    echo "Left alone (they hold your settings and downloaded engines):"
    echo "  ~/.lace_downloader_config.json"
    echo "  ${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID/"
    exit 0
fi

# ---- locate the binary -------------------------------------------------------
if [[ -n "${1:-}" ]]; then
    BINARY="$1"
else
    # Two layouts: a built repo (binary under dist/) and an unpacked release
    # tarball (binary sitting right next to this script). Newest match wins, so
    # this keeps working across version bumps.
    BINARY="$(ls -t "$REPO"/dist/LacesTotalMediaDownloader_v*_linux \
                     "$REPO"/LacesTotalMediaDownloader_v*_linux 2>/dev/null | head -1 || true)"
fi

if [[ -z "$BINARY" || ! -f "$BINARY" ]]; then
    echo "No Linux build found." >&2
    echo "Build one first (see BUILD_LINUX.md):" >&2
    echo "  pyinstaller --noconfirm --clean LacesTotalMediaDownloader.spec" >&2
    exit 1
fi

if ! head -c 4 "$BINARY" | grep -q ELF; then
    echo "$BINARY is not a Linux executable." >&2
    echo "The .exe from a Windows build won't run here — build on Linux." >&2
    exit 1
fi

# ---- install -----------------------------------------------------------------
mkdir -p "$BIN_DIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"

install -Dm755 "$BINARY" "$TARGET"

# assets/icons/ in the repo, or a plain icon.png in a release tarball.
for candidate in "$REPO/assets/icons/icon.png" "$REPO/icon.png"; do
    if [[ -f "$candidate" ]]; then
        install -Dm644 "$candidate" "$ICON_FILE"
        break
    fi
done

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Download video and audio from hundreds of sites
Exec=$TARGET
Icon=$APP_ID
Terminal=false
Categories=AudioVideo;Audio;Video;
Keywords=download;video;audio;youtube;media;yt-dlp;
StartupWMClass=$WM_CLASS
EOF
chmod 644 "$DESKTOP_FILE"

refresh_caches

echo "Installed $APP_NAME"
echo "  binary   $TARGET"
echo "  launcher $DESKTOP_FILE"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo
       echo "Note: $BIN_DIR isn't on your PATH, so the app menu entry works but"
       echo "typing '$APP_ID' in a terminal won't. To fix it, add this to your"
       echo "shell config (~/.config/fish/config.fish, ~/.bashrc, ...):"
       echo "  set -gx PATH $BIN_DIR \$PATH     # fish"
       echo "  export PATH=\"$BIN_DIR:\$PATH\"   # bash / zsh"
       ;;
esac
