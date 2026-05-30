#!/bin/sh
# Install GIF Forge's data files (desktop, AppStream, GSettings schema, icons)
# into $1 (the install prefix, e.g. the Flatpak /app). Run from the repo root.
set -eu

PREFIX="${1:-/app}"
APPID=io.github.elhombretecla.GifForge
SHARE="$PREFIX/share"

install -Dm644 "data/$APPID.desktop" "$SHARE/applications/$APPID.desktop"
install -Dm644 "data/$APPID.metainfo.xml" "$SHARE/metainfo/$APPID.metainfo.xml"
install -Dm644 "data/$APPID.gschema.xml" "$SHARE/glib-2.0/schemas/$APPID.gschema.xml"
glib-compile-schemas "$SHARE/glib-2.0/schemas"

# GIF Forge's own application icon, installed at the standard hicolor sizes.
for size in 512x512 256x256 128x128 64x64 48x48; do
  install -Dm644 "data/icons/$size/$APPID.png" \
    "$SHARE/icons/hicolor/$size/apps/$APPID.png"
done

echo "Installed GIF Forge data files into $PREFIX"
