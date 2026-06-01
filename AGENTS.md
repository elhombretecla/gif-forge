# AGENTS.md

Guidance for AI coding agents (and new contributors) working on GIF Forge.
Human-oriented docs live in [`docs/`](docs/); this file is the quick, rules-first
context. Nested `AGENTS.md` files (e.g. [`po/AGENTS.md`](po/AGENTS.md)) override
this one for their subtree.

## Project overview

GIF Forge is a modern Linux **screen recorder + GIF/video timeline editor**,
built in **Python 3.10+ with GTK4 / Libadwaita (PyGObject)**. It records a
region, window or screen on **Wayland** (ScreenCast portal + PipeWire) or **X11**
(ffmpeg `x11grab`), edits the result on a timeline, and exports an optimized
**GIF, WebM or APNG** via `ffmpeg` (and optionally `gifski`). It is a ground-up
rewrite of the deprecated Peek; released under **GPL-3.0-or-later**.

### Repository layout

```
gifforge/            main package (importable, no pip runtime deps)
  capture/           capture backends: portal (Wayland), x11; region math; factory/detect
  encode/            ffmpeg/gifski orchestration, presets, pipeline, errors
  frames/            decode → disk-backed FrameList, per-frame ops, overlay_render (pycairo)
  editor/            timeline + undoable edit commands
  project/           session cache, .gifforge container, recents, autosave/recovery
  settings/          GSettings-or-JSON Settings store
  ui/                GTK4/Libadwaita windows (recorder, editor, preview, export, preferences, frame_strip)
  platform/          X11 geometry / window glue
  i18n.py            gettext setup (`_`, `init`)
  models.py recorder.py utils.py __init__.py (APP_ID/APP_NAME/__version__) __main__.py
data/                .desktop, .metainfo.xml (AppStream), .gschema.xml, icons/
po/                  translations — see po/AGENTS.md
build-aux/flatpak/   Flatpak manifest + install-data.sh (shared data installer)
debian/  packaging/{appimage,aur,rpm,deb}/   distro packaging — see docs/PACKAGING.md
docs/                USER_GUIDE.md, DEVELOPMENT.md, PACKAGING.md
tests_py/            unit tests (test_*.py) + e2e drivers (_e2e_*.py)
.github/workflows/   ci.yml (tests+validation), flatpak.yml, release.yml (tag-driven)
```

## Setup

Runtime dependencies are **system packages, not pip** (`pyproject.toml` has
`dependencies = []` on purpose — PyGObject/GTK come from the OS).

On Debian/Ubuntu (22.04+):

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    gstreamer1.0-pipewire gstreamer1.0-plugins-good ffmpeg
# optional, higher-quality GIFs: gifski
```

For tests: `pip install -e .[dev]` (or just `pip install pytest`).

## Common commands

- **Run from source:** `./run.sh` (checks deps, compiles the GSettings schema and
  translations into a cache dir) — or `python3 -m gifforge`.
- **Unit tests:** `python3 -m pytest tests_py -q`
- **End-to-end UI drivers** (need a display; use Xvfb headless):
  `xvfb-run -a python3 tests_py/_e2e_editor.py` (also `_e2e_export.py`,
  `_e2e_project.py`, `_e2e_ui.py`).
- **Validate data files:** `desktop-file-validate data/io.github.elhombretecla.GifForge.desktop`,
  `appstreamcli validate --no-net data/io.github.elhombretecla.GifForge.metainfo.xml`,
  `glib-compile-schemas` on a copy of the schema.
- **Build Flatpak:** `flatpak-builder --user --install --force-clean build build-aux/flatpak/io.github.elhombretecla.GifForge.yml`
- **Build .deb:** `sh packaging/deb/build-deb.sh`
- **Refresh translations:** `sh po/update-pot.sh`

## Code style

- Python with `from __future__ import annotations` and type hints; `snake_case`
  functions, `PascalCase` classes. 4-space indentation.
- Every source file starts with the two SPDX header lines
  (`# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <…>` /
  `# SPDX-License-Identifier: GPL-3.0-or-later`). Keep them on new files.
- GTK widgets are built **in code**, not in `.ui` templates. Menus use
  `Gio.Menu` (not GtkBuilder XML).
- Match the surrounding file's comment density and idiom.

## Architecture rules

- **Domain layers stay toolkit-agnostic.** `capture/`, `encode/`, `frames/`,
  `editor/`, `project/`, `models.py` must **not** import `gi`/GTK — they are unit
  tested without a display. Only `gifforge/ui/` (and `platform/`) touch GTK.
- **Capture backends** go behind `capture/factory.py` + the `capture/backend.py`
  interface; detect the session with `capture.detect_session()`.
- **Settings**: to add a preference, add the key to `DEFAULTS` in
  `settings/config.py` **and** to `data/…gschema.xml` (with the same name/type),
  then read/write via `get_settings().get(key)` / `.set(key, value)`.
- Reuse existing utilities before adding abstractions (e.g.
  `build-aux/flatpak/install-data.sh` is the one shared data installer for every
  packaging channel).

## Internationalisation (i18n)

- Every **user-facing string must be wrapped in `_()`** (`from ..i18n import _`).
  English is the source language; the gettext domain is `gif-forge`.
- Do **not** call `_()` at module top level — `i18n.init()` runs in `main()`
  before windows are built, so translate at call time inside functions/methods.
- Keep `{named}` placeholders identical between the English string and its
  translations. After adding strings, run `sh po/update-pot.sh`. See
  [`po/AGENTS.md`](po/AGENTS.md).

## Testing expectations

- Add or update tests for behavioral changes, especially in the GTK-free domain
  layers (they're straightforward to unit test).
- Run `python3 -m pytest tests_py -q` before finishing.
- The e2e `playback-advanced` check is timing-based and **occasionally flaky** in
  CI — a single re-run is the expected remedy, not a code change.

## Packaging & releases

- Releases are **driven by a git tag** `vX.Y.Z`: bump the version in
  `pyproject.toml` and `gifforge/__init__.py`, then push the tag — `release.yml`
  builds the `.deb`, AppImage and Flatpak bundle and attaches them to the GitHub
  Release. AUR/Fedora are published manually.
- `install-data.sh` is reused by AUR/Fedora/AppImage/Flatpak; the `.deb` diverges
  on purpose (uses `debian/*.install` + the dpkg `glib-compile-schemas` trigger).
- Full maintainer guide and caveats (PEP 639 `setuptools>=77`, AppImage
  fragility, RPM Fusion ffmpeg) are in [`docs/PACKAGING.md`](docs/PACKAGING.md).

## Generated / do-not-edit files

- Never commit compiled artifacts: `gschemas.compiled`, `po/*.mo` (compiled at
  install time), `AppDir/`, `build/`, `dist/`, `.appimage-tools/`, `__pycache__/`.
- Do **not** hand-edit `.mo`; edit `po/<lang>.po` and recompile via the
  packaging scripts / `po/update-pot.sh`.

## Git / PR conventions

- **Don't commit directly to `main`** — branch, then open a PR.
- Small, focused commits/PRs; don't mix a large refactor with a fix.
- **CI must be green before merging** (`ci.yml`: unit + e2e + data validation,
  `flatpak.yml`: bundle build). `release.yml` only runs on tags / manual dispatch.
- Note risks, migrations, or version-sensitive changes in the PR summary.

## Safety / boundaries

- **Do not remove Peek attribution.** Parts of the encode/capture logic are
  genuinely derived from Peek (GPL-3) — `AUTHORS` and the "ported from `*.vala`"
  provenance comments are a licence obligation, not cosmetic cruft.
- **Do not add pip runtime dependencies.** GTK/GStreamer come from the system;
  `dependencies = []` is intentional. New deps need a clear, discussed reason.
- **Do not bump bundled `ffmpeg`/`gifski` versions** (Flatpak manifest) without
  updating the `sha256` and verifying the codec/demuxer/filter flags the exporter
  relies on (notably the `concat` demuxer and `palettegen`/`paletteuse`).
- Don't change the app ID, GSettings schema id, or public command names without
  updating the data files and docs together.
