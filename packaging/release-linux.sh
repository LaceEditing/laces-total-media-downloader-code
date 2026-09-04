#!/usr/bin/env bash
#
# Build the distributable Linux release: a portable binary plus the tarball to
# upload. Run from anywhere; it works on the repo it lives in.
#
#   packaging/release-linux.sh
#
# The build happens inside an Ubuntu 22.04 container ON PURPOSE. glibc is
# forward-compatible only, so a binary built against a current Arch/Fedora glibc
# refuses to start on anything older -- which is nearly every machine you'd be
# shipping to. 22.04 gives glibc 2.35 and covers everything from 2022 onward.
#
# Requires docker (rootless or with your user in the docker group) and the
# static ffmpeg/ffprobe next to the spec (see BUILD_LINUX.md section 3).
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

IMAGE="ltmd-linux-build"
VERSION="$(grep -oP 'CURRENT_VERSION\s*=\s*"\K[^"]+' main.py)"
NAME="LacesTotalMediaDownloader-${VERSION}-linux-x86_64"
BINARY="LacesTotalMediaDownloader_v${VERSION}_linux"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Building $NAME"

if [[ ! -f ffmpeg || ! -f ffprobe ]]; then
    echo "WARNING: ffmpeg/ffprobe are not next to the spec, so the release will" >&2
    echo "         depend on the user having ffmpeg installed. See BUILD_LINUX.md." >&2
fi

echo "==> Preparing build image ($IMAGE)"
docker build -q -t "$IMAGE" -f packaging/Dockerfile.linux "$REPO" >/dev/null

echo "==> Compiling (Ubuntu 22.04 / glibc 2.35)"
# Source mounted read-only so a build can never dirty the working tree; output
# goes to a scratch dir, owned by the invoking user rather than root.
docker run --rm \
    -v "$REPO":/src:ro \
    -v "$WORK":/out \
    -w /src \
    -u "$(id -u):$(id -g)" \
    -e HOME=/out \
    "$IMAGE" \
    pyinstaller --noconfirm --clean \
        --distpath /out/dist --workpath /out/build \
        LacesTotalMediaDownloader.spec

[[ -f "$WORK/dist/$BINARY" ]] || { echo "build produced no $BINARY" >&2; exit 1; }

echo "==> Checking the glibc floor"
# Guard against a future change quietly reintroducing a too-new dependency.
MAX_GLIBC="$(cd "$WORK" && objdump -T "dist/$BINARY" 2>/dev/null \
    | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1 || true)"
echo "    bootloader needs at most ${MAX_GLIBC:-none}"

echo "==> Assembling the tarball"
STAGE="$WORK/stage/$NAME"
install -Dm755 "$WORK/dist/$BINARY"       "$STAGE/$BINARY"
install -Dm755 "$REPO/install-linux.sh"   "$STAGE/install-linux.sh"
install -Dm644 "$REPO/assets/icons/icon.png" "$STAGE/icon.png"
cp -r "$REPO/packaging/release-files/." "$STAGE/"

mkdir -p "$REPO/dist"
install -Dm755 "$WORK/dist/$BINARY" "$REPO/dist/$BINARY"
tar --numeric-owner --owner=0 --group=0 --sort=name \
    -czf "$REPO/dist/$NAME.tar.gz" -C "$WORK/stage" "$NAME"

echo
echo "Done:"
echo "  dist/$NAME.tar.gz   ($(du -h "$REPO/dist/$NAME.tar.gz" | cut -f1))  <- upload this"
echo "  dist/$BINARY   ($(du -h "$REPO/dist/$BINARY" | cut -f1))  <- bare binary"
