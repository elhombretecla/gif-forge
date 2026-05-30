# GIF Forge — Development

GIF Forge is a Python 3.10+ / PyGObject / GTK4 + Libadwaita application. It
began as a ground-up rewrite of the deprecated Vala/GTK3 Peek.

## Dependencies

Runtime (system, via PyGObject — not pip-installable):

- Python ≥ 3.10
- GTK 4, Libadwaita 1
- GStreamer with the `pipewiresrc` and `vp9enc` plugins (Wayland capture)
- `ffmpeg` (mandatory: X11 capture, frame decode, all encoding)
- `gifski` (optional: higher-quality GIFs)

On Debian/Ubuntu:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
    gstreamer1.0-pipewire gstreamer1.0-plugins-good ffmpeg
```

## Run from source

```sh
python3 -m gifforge
# or, after `pip install -e .`
gif-forge
```

The GSettings schema is optional in development: if it isn't installed, settings
fall back to a JSON file under `$XDG_CONFIG_HOME`. To use the real GSettings
backend locally:

```sh
mkdir -p /tmp/schemas && cp data/io.github.elhombretecla.GifForge.gschema.xml /tmp/schemas/
glib-compile-schemas /tmp/schemas
GSETTINGS_SCHEMA_DIR=/tmp/schemas python3 -m gifforge
```

## Tests

```sh
python3 -m pytest tests_py -q          # unit tests (some skip without ffmpeg)
# End-to-end UI drivers need a display (use xvfb-run in headless CI):
PYTHONPATH=$PWD python3 tests_py/_e2e_editor.py
```

`tests_py/test_*.py` are unit tests collected by pytest. The `tests_py/_e2e_*.py`
scripts drive the real GTK app end to end and are run manually / in the `e2e`
CI job under Xvfb.

## Build the Flatpak

```sh
flatpak-builder --user --install --force-clean build \
    build-aux/flatpak/io.github.elhombretecla.GifForge.yml
flatpak run io.github.elhombretecla.GifForge
```

The manifest bundles `ffmpeg` (built with the exact codecs/filters GIF Forge
uses — note the `concat` demuxer needed by the exporter) and `gifski`.

## Architecture

Layered, capture-backend-agnostic (see the full plan in
`.claude/plans/`):

```
gifforge/
  capture/    backends: portal+PipeWire (Wayland), x11grab (X11); region math
  encode/     ffmpeg/gifski orchestration; recording + edited-timeline export
  frames/     decode recording -> disk-backed FrameList; per-frame image ops
  editor/     timeline + undoable edit commands (snapshot-based undo/redo)
  project/    session cache, .gifforge container, recents, autosave/recovery
  settings/   GSettings-or-JSON preferences
  ui/         GTK4/Libadwaita windows (recorder, editor, preview, dialogs)
  platform/   X11 geometry and other platform glue
```

The domain layers (`encode`, `frames`, `editor`, `project`, `models`) have no
GTK dependency and are unit tested directly.
