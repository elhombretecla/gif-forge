#!/usr/bin/env bash
# Dev launcher for GIF Forge.
#
# Runs the app straight from this source checkout — no install needed. It
# compiles the GSettings schema into a cache dir (so the real GSettings backend
# is used; otherwise the app falls back to a JSON config file, which also works)
# and sets PYTHONPATH to this checkout.
#
# Usage:  ./run.sh [extra args passed to gifforge]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- compile the GSettings schema into a cache dir ---------------------------
SCHEMA_SRC="data/io.github.elhombretecla.GifForge.gschema.xml"
SCHEMA_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/gif-forge-dev/schemas"
mkdir -p "$SCHEMA_DIR"
if [ -f "$SCHEMA_SRC" ] && command -v glib-compile-schemas >/dev/null 2>&1; then
  cp "$SCHEMA_SRC" "$SCHEMA_DIR/"
  glib-compile-schemas "$SCHEMA_DIR"
  export GSETTINGS_SCHEMA_DIR="$SCHEMA_DIR${GSETTINGS_SCHEMA_DIR:+:$GSETTINGS_SCHEMA_DIR}"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# --- check runtime dependencies (warn, don't fail) ---------------------------
python3 - <<'PY' || true
import shutil, sys
missing = []
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw  # noqa: F401
except Exception as exc:  # pragma: no cover
    missing.append(f"PyGObject with GTK 4 + Libadwaita ({exc})")
if shutil.which("ffmpeg") is None:
    missing.append("ffmpeg (required for capture and encoding)")
if shutil.which("gifski") is None:
    sys.stderr.write("ℹ gifski not found — high-quality GIF option will be unavailable.\n")
if missing:
    sys.stderr.write(
        "\n⚠ Missing required dependencies:\n  - " + "\n  - ".join(missing) +
        "\n\nOn Debian/Ubuntu:\n"
        "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \\\n"
        "      gstreamer1.0-pipewire gstreamer1.0-plugins-good ffmpeg\n\n"
    )
    sys.exit(1)
PY

# --- launch ------------------------------------------------------------------
echo "Launching GIF Forge (session: ${XDG_SESSION_TYPE:-unknown})…"
exec python3 -m gifforge "$@"
