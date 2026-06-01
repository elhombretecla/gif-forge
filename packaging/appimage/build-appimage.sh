#!/bin/bash
# Build the GIF Forge AppImage.
#
# This is the most fragile packaging channel (see docs/PACKAGING.md). It bundles
# a relocatable Python, the GTK4/Libadwaita/GStreamer stack via
# linuxdeploy-plugin-gtk, the GObject-introspection typelibs, gdk-pixbuf loaders,
# our data files, and static ffmpeg/gifski binaries, then packs it all with
# linuxdeploy. Intended to run on Ubuntu 22.04 (old glibc -> broad portability).
#
# Output: dist/GIF_Forge-<version>-x86_64.AppImage
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PKGDIR="packaging/appimage"

VERSION="${1:-${GITHUB_REF_NAME:-}}"
VERSION="${VERSION#v}"
[ -n "$VERSION" ] || VERSION="0.0.0-dev"

ARCH="$(uname -m)"
APPDIR="$ROOT/AppDir"
USR="$APPDIR/usr"
APPID="io.github.elhombretecla.GifForge"

rm -rf "$APPDIR" dist
mkdir -p "$USR/bin" "$USR/lib" dist

# --- 1. system build dependencies (the AppImage bundles copies of these) -----
# On CI these are installed by the workflow; listed here for local runs.
#   sudo apt-get install -y python3 python3-pip python3-gi python3-gi-cairo \
#     gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 \
#     gstreamer1.0-pipewire gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
#     libgirepository-1.0-1 wget file desktop-file-utils

PYVER="$(python3 -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"
PYLIB="/usr/lib/$PYVER"

# --- 2. bundle a relocatable Python interpreter ------------------------------
cp "$(command -v "$PYVER" || command -v python3)" "$USR/bin/$PYVER"
mkdir -p "$USR/lib/$PYVER"
# Standard library (skip the heavy/unneeded test trees).
cp -a "$PYLIB/." "$USR/lib/$PYVER/" 2>/dev/null || true
rm -rf "$USR/lib/$PYVER/test" "$USR/lib/$PYVER/"*/test 2>/dev/null || true
mkdir -p "$USR/lib/$PYVER/site-packages"

# --- 3. install gifforge into the bundled site-packages ----------------------
python3 -m pip install --no-deps --no-compile \
  --target "$USR/lib/$PYVER/site-packages" "$ROOT"
# The entry-point script is irrelevant inside the AppImage; AppRun runs
# `python -m gifforge` directly.

# --- 4. bundle the system `gi` (C extension) + typelibs ----------------------
# `import gi` must match the bundled interpreter's ABI.
GI_SRC="$(python3 -c 'import gi, os; print(os.path.dirname(gi.__file__))')"
cp -a "$GI_SRC" "$USR/lib/$PYVER/site-packages/"

# pycairo (`import cairo`) — overlay rendering at export time needs it, and the
# gi cairo foreign-struct converter (_gi_cairo) ships inside the gi package above.
CAIRO_SRC="$(python3 -c 'import cairo, os; print(os.path.dirname(cairo.__file__))' 2>/dev/null || true)"
[ -n "$CAIRO_SRC" ] && cp -a "$CAIRO_SRC" "$USR/lib/$PYVER/site-packages/" \
  || echo "WARN: pycairo not found; overlay export will fail" >&2

TYPELIB_DIR="/usr/lib/$ARCH-linux-gnu/girepository-1.0"
mkdir -p "$USR/lib/$ARCH-linux-gnu/girepository-1.0"
for t in Gtk-4.0 Gdk-4.0 Gsk-4.0 Adw-1 \
         Gst-1.0 GstBase-1.0 GstApp-1.0 GstVideo-1.0 \
         GdkPixbuf-2.0 GdkX11-4.0 Gio-2.0 GLib-2.0 GObject-2.0 \
         GModule-2.0 Graphene-1.0 HarfBuzz-0.0 Pango-1.0 PangoCairo-1.0 \
         cairo-1.0 freetype2-2.0 ; do
  [ -f "$TYPELIB_DIR/$t.typelib" ] && \
    cp "$TYPELIB_DIR/$t.typelib" "$USR/lib/$ARCH-linux-gnu/girepository-1.0/" || \
    echo "WARN: typelib $t not found" >&2
done

# --- 5. bundle GStreamer plugins (capture + encode) --------------------------
GST_SRC="/usr/lib/$ARCH-linux-gnu/gstreamer-1.0"
GST_DST="$USR/lib/$ARCH-linux-gnu/gstreamer-1.0"
mkdir -p "$GST_DST"
for p in libgstcoreelements libgstpipewire libgstvpx libgstapp \
         libgstvideoconvertscale libgstvideoconvert libgstvideoscale \
         libgstmatroska libgstisomp4 \
         libgstpng libgstplayback libgsttypefindfunctions ; do
  [ -f "$GST_SRC/$p.so" ] && cp "$GST_SRC/$p.so" "$GST_DST/" || \
    echo "WARN: gst plugin $p not found" >&2
done
# PipeWire client lib (ABI must match the host daemon; best-effort).
for lib in /usr/lib/$ARCH-linux-gnu/libpipewire-0.3.so*; do
  [ -e "$lib" ] && cp -a "$lib" "$USR/lib/$ARCH-linux-gnu/" || true
done

# --- 6. data files (desktop, metainfo, gschema, icons) -----------------------
sh build-aux/flatpak/install-data.sh "$USR"

# --- 7. static ffmpeg + gifski ----------------------------------------------
# ffmpeg: GitHub-hosted static build from BtbN (reliable from CI; GPL build has
# the concat demuxer + palettegen/paletteuse filters the exporter needs).
if [ ! -x "$USR/bin/ffmpeg" ]; then
  FF_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-linux64-gpl-7.1.tar.xz"
  wget -qO /tmp/ffmpeg.tar.xz "$FF_URL"
  mkdir -p /tmp/ffmpeg-extract
  tar -xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-extract
  FF_BIN="$(find /tmp/ffmpeg-extract -type f -name ffmpeg | head -n1)"
  install -Dm755 "$FF_BIN" "$USR/bin/ffmpeg"
fi
# gifski: prebuilt binary from the release page (optional; app degrades without).
if [ ! -x "$USR/bin/gifski" ]; then
  if command -v cargo >/dev/null 2>&1; then
    cargo install gifski --root "$USR" --features openmp || \
      echo "WARN: gifski build failed; high-quality GIF export unavailable" >&2
  else
    echo "WARN: cargo not available; skipping gifski (optional)" >&2
  fi
fi

# --- 8. AppRun, top-level desktop + icon -------------------------------------
cp "$PKGDIR/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp "data/$APPID.desktop" "$APPDIR/$APPID.desktop"
cp "data/icons/256x256/$APPID.png" "$APPDIR/$APPID.png"

# --- 9. linuxdeploy + gtk plugin --------------------------------------------
TOOLDIR="$ROOT/.appimage-tools"
mkdir -p "$TOOLDIR"
fetch() { # fetch <url> <dest>
  [ -x "$2" ] || { wget -qO "$2" "$1"; chmod +x "$2"; }
}
fetch "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-${ARCH}.AppImage" \
  "$TOOLDIR/linuxdeploy"
fetch "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh" \
  "$TOOLDIR/linuxdeploy-plugin-gtk.sh"

export OUTPUT="dist/GIF_Forge-${VERSION}-${ARCH}.AppImage"
export DEPLOY_GTK_VERSION=4

"$TOOLDIR/linuxdeploy" \
  --appdir "$APPDIR" \
  --plugin gtk \
  --custom-apprun "$APPDIR/AppRun" \
  --desktop-file "$APPDIR/$APPID.desktop" \
  --icon-file "$APPDIR/$APPID.png" \
  --output appimage

echo "Built: $OUTPUT"
