# Building the Flatpak

> **Note:** Flatpak builds must be done on a Linux machine. You cannot build a
> Flatpak on Windows. See the [CachyOS setup guide](#setting-up-a-linux-build-machine-cachyos)
> below if you need to spin up a Linux environment first.

---

## Setting up a Linux build machine (CachyOS)

CachyOS is an Arch-based distro that works great as a build machine. These steps
take you from a fresh install to a working Flatpak build.

### 1. Install CachyOS

Download the ISO from [cachyos.org](https://cachyos.org), flash it to a USB
(Rufus on Windows works fine), boot from it, and follow the graphical installer.
KDE is the default desktop — pick whatever you like.

### 2. Get your code onto the machine

Open a terminal and either clone the repo (once it's public):

```bash
sudo pacman -S git
git clone https://github.com/LaceEditing/laces-total-media-downloader.git
cd laces-total-media-downloader
```

Or copy the project folder over via USB drive / network share if the repo is
still private.

### 3. Install Flatpak tooling

CachyOS may already have Flatpak installed, but make sure both tools are present:

```bash
sudo pacman -S flatpak flatpak-builder
```

### 4. Add Flathub and install the SDK + runtime

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08
```

This downloads the Freedesktop runtime (~600 MB) and SDK (~1.4 GB). The SDK is
what `flatpak-builder` uses to compile everything inside the sandbox. Say `y`
when prompted.

### 5. Build the Flatpak

From the root of your project directory (not inside `flatpak/`):

```bash
flatpak-builder --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
```

This will:
- Download and compile SDL2, SDL2_mixer, SDL2_image (required by pygame)
- `pip install` all Python dependencies (customtkinter, yt-dlp, pygame, requests, etc.)
- Copy `main.py`, assets, the desktop entry, icon, and launcher script into place

The first build takes a while due to SDL compilation. Subsequent builds use the
cache and are much faster.

### 6. Install and test locally

```bash
flatpak-builder --user --install --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
flatpak run com.laceediting.TotalMediaDownloader
```

Test that the GUI opens, a download works, and the notification sound plays.

### 7. Export a distributable bundle

```bash
flatpak-builder --repo=repo --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
flatpak build-bundle repo LacesTotalMediaDownloader.flatpak com.laceediting.TotalMediaDownloader
```

This produces `LacesTotalMediaDownloader.flatpak` — a single file anyone can
install without Flathub:

```bash
flatpak install LacesTotalMediaDownloader.flatpak
```

### 8. Uninstall (cleanup)

```bash
flatpak uninstall com.laceediting.TotalMediaDownloader
```

---

## Quick reference — what you're installing on CachyOS

| Package | Command | Why |
|---------|---------|-----|
| `git` | `pacman -S git` | Clone your repo |
| `flatpak` | `pacman -S flatpak` | Flatpak runtime |
| `flatpak-builder` | `pacman -S flatpak-builder` | Builds Flatpaks from manifests |
| Freedesktop SDK 24.08 | `flatpak install` | Sandbox environment for building |

---

## Prerequisites (generic — any distro)

Install Flatpak and flatpak-builder on your Linux system:

```bash
# Arch / CachyOS / Manjaro
sudo pacman -S flatpak flatpak-builder

# Debian / Ubuntu
sudo apt install flatpak flatpak-builder

# Fedora
sudo dnf install flatpak flatpak-builder
```

Add Flathub and install the SDK:

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08
```

## Build

From the repository root:

```bash
flatpak-builder --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
```

## Install locally (for testing)

```bash
flatpak-builder --user --install --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
```

## Run

```bash
flatpak run com.laceediting.TotalMediaDownloader
```

## Uninstall

```bash
flatpak uninstall com.laceediting.TotalMediaDownloader
```

## Export to a .flatpak bundle (for distribution)

```bash
flatpak-builder --repo=repo --force-clean build-dir flatpak/com.laceediting.TotalMediaDownloader.yml
flatpak build-bundle repo LacesTotalMediaDownloader.flatpak com.laceediting.TotalMediaDownloader
```

The resulting `LacesTotalMediaDownloader.flatpak` file can be distributed and installed with:

```bash
flatpak install LacesTotalMediaDownloader.flatpak
```

## Notes

- FFmpeg is included in the `org.freedesktop.Platform` runtime, so it's available automatically.
- yt-dlp auto-updates are disabled inside Flatpak (detected via `/.flatpak-info`). Update the Flatpak package itself to get yt-dlp updates.
- App update checks are also skipped in Flatpak — users should update through their Flatpak manager.
- The app saves its config to `~/.lace_downloader_config.json` (accessible via `--filesystem=home`).
