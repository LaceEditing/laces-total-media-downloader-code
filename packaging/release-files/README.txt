Lace's Total Media Downloader 3.8.0 — Linux (x86-64)
====================================================

Download video and audio from hundreds of sites.

This is a single self-contained program. There is nothing to install first —
no Python, no ffmpeg, no yt-dlp. It is already inside the file.


RUN IT
------

    ./LacesTotalMediaDownloader_v3.8.0_linux

If your file manager or shell says it isn't executable, the download lost the
permission bit. Restore it with:

    chmod +x LacesTotalMediaDownloader_v3.8.0_linux


ADD IT TO YOUR APPLICATIONS MENU (optional)
-------------------------------------------

    ./install-linux.sh

That copies the program to ~/.local/bin, installs the icon, and adds a menu
entry. Everything stays inside your home folder and it never asks for a
password. To undo it:

    ./install-linux.sh --uninstall


REQUIREMENTS
------------

A 64-bit x86 Linux with glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora
36, and anything more recent). X11 or Wayland both work.


WHERE IT PUTS THINGS
--------------------

    ~/Downloads                                     downloaded media (changeable
                                                    in the app)
    ~/.lace_downloader_config.json                  your settings
    ~/.local/share/laces-total-media-downloader/    the download engine
    ~/.fonts/                                       the app's UI fonts

On first launch it downloads two helpers into that engine folder: a current
yt-dlp, and Deno (about 90 MB) which YouTube requires to solve its JavaScript
challenge. Deno is only fetched if you don't already have deno or node
installed. After that, first launch each day refreshes yt-dlp — that is what
keeps downloads working when a site changes something.


SIGNING IN TO YOUTUBE
---------------------

Age-restricted and members-only videos need an account. When one comes up the
app offers to read cookies from a browser you're already signed into. Nothing
is stored or copied — the cookies are read at download time and used only for
YouTube.

On Linux those cookies are encrypted against your desktop keyring, so KWallet
or GNOME Keyring needs to be unlocked. If that doesn't work, the app also
accepts a cookies.txt file exported from any browser extension.


LICENCES
--------

See the LICENSES folder. The bundled ffmpeg is licensed under the GNU General
Public License version 3; its full text and the exact build details are there.
