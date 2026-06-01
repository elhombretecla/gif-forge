# GIF Forge — Packaging & Releases

This document is for maintainers. It explains how GIF Forge is packaged for each
channel, how a release is cut, and the manual steps for the channels that can't
be fully automated from this repo.

GIF Forge is a **pure-Python** package (`gifforge`, setuptools, entry point
`gif-forge = gifforge.ui.application:main`) with **system** runtime
dependencies: PyGObject, GTK4, Libadwaita, GStreamer (`pipewiresrc` + `vp9enc`),
`ffmpeg` (mandatory) and `gifski` (optional). The distro packages (.deb, AUR,
Fedora) simply depend on those system packages; Flatpak and AppImage bundle
them.

## Version flow (tag-driven)

`pyproject.toml`/`gifforge/__init__.py` carry a development version. **All
packaging recipes take their version from the git tag.** To cut a release:

1. Bump the version in `pyproject.toml` (`version = "X.Y.Z"`) and
   `gifforge/__init__.py` (`__version__`), commit.
2. Tag `vX.Y.Z` and push the tag.
3. `.github/workflows/release.yml` builds the `.deb`, AppImage and Flatpak
   bundle and attaches them (plus `SHA256SUMS`) to the GitHub Release.
4. Publish the AUR and Fedora packages manually (see below), bumping their
   `pkgver` / `Version` to `X.Y.Z`.

The `.deb` build script (`packaging/deb/build-deb.sh`) reads the version from
its first argument, else `$GITHUB_REF_NAME` (tag with the leading `v` stripped),
else `debian/changelog`.

## Shared data installer

`build-aux/flatpak/install-data.sh PREFIX` is the single source of truth for
installing the desktop entry, AppStream metainfo, GSettings schema and icons
into `PREFIX/share`. It also runs `glib-compile-schemas`. It is reused by AUR,
Fedora and the AppImage build.

**Caveat — the compiled schema cache.** Distros that have a `glib-compile-schemas`
file trigger recompile the schema at install time, so the package must **not**
ship `gschemas.compiled`:

- **.deb** sidesteps the script entirely: `debian/gif-forge.install` copies the
  raw `.gschema.xml` and the dpkg trigger compiles it on the user's machine.
- **Fedora** calls the script, then deletes the cache:
  `rm -f %{buildroot}%{_datadir}/glib-2.0/schemas/gschemas.compiled`.
- **AUR** keeps the cache (harmless — Arch's `glib2` hook recompiles system-wide).

## Channels

### Flatpak (recommended)

Manifest: `build-aux/flatpak/io.github.elhombretecla.GifForge.yml` (GNOME
Platform 48; bundles `ffmpeg` built with the exact codecs/filters the exporter
needs — including the `concat` demuxer — and `gifski`).

```sh
flatpak-builder --user --install --force-clean build \
    build-aux/flatpak/io.github.elhombretecla.GifForge.yml
```

CI builds the bundle in both `flatpak.yml` (branch/PR) and `release.yml` (tag).
Flathub submission is out of scope for now.

### .deb (Debian/Ubuntu)

Native `debian/` packaging via `debhelper` + `dh-python`/`pybuild`. Targets
Ubuntu 22.04+/Debian 12+ (GTK4/Libadwaita availability). Single binary package
`gif-forge`, `Architecture: all` (no compiled code → one build serves all
arches). `pybuild` installs `gifforge` into `dist-packages` and generates
`/usr/bin/gif-forge` from `[project.scripts]`.

```sh
sudo apt install devscripts debhelper dh-python pybuild-plugin-pyproject \
    python3-all python3-setuptools libglib2.0-bin
sh packaging/deb/build-deb.sh 0.1.0   # writes ../gif-forge_0.1.0_all.deb
```

`gifski` is `Recommends` (optional, not in every repo). The GSettings schema is
compiled by the dpkg trigger.

> **setuptools floor.** `pyproject.toml` declares `license = "GPL-3.0-or-later"`
> (PEP 639), which needs `setuptools>=77` + `packaging>=24.2`. `pybuild` uses the
> system setuptools, which on Ubuntu 22.04/24.04 is too old. The `deb` CI job
> upgrades it (`pip install -U 'setuptools>=77' 'packaging>=24.2'`); do the same
> when building the `.deb` locally. Arch/Fedora ship a recent enough setuptools,
> and Flatpak builds inside the GNOME SDK (also recent), so only the `.deb` path
> needs this.

### Arch (AUR)

`packaging/aur/PKGBUILD` (+ `.SRCINFO`). `arch=('any')`. `package()` installs the
wheel with `python -m installer` and reuses `install-data.sh`.

**AUR cannot be a subdirectory of this repo** — it has its own git repo. To
publish:

```sh
git clone ssh://aur@aur.archlinux.org/gif-forge.git aur-gif-forge
cp packaging/aur/PKGBUILD aur-gif-forge/
cd aur-gif-forge
# bump pkgver, refresh the source checksum:
updpkgsums
makepkg --printsrcinfo > .SRCINFO
git commit -am "gif-forge X.Y.Z" && git push
```

Locally test with `makepkg -si` and lint with `namcap PKGBUILD *.pkg.tar.zst`.

### Fedora (COPR)

`packaging/rpm/gif-forge.spec`, `BuildArch: noarch`, using `pyproject-rpm-macros`.
`%install` reuses `install-data.sh` and deletes `gschemas.compiled`.

**`ffmpeg` is in RPM Fusion, not Fedora proper.** Users enable RPM Fusion before
installing; a COPR project cannot depend on RPM Fusion packages at build time
(runtime `Requires: ffmpeg` is still declared).

Publish via COPR:

```sh
# Local build first:
rpmbuild -ba packaging/rpm/gif-forge.spec     # needs Source0 tarball in ~/rpmbuild/SOURCES
# COPR: create a project, then build from the spec + an uploaded SRPM,
# or point COPR at this repo's spec for SCM builds.
```

Lint with `rpmlint`.

### AppImage (portable, best-effort)

`packaging/appimage/build-appimage.sh` assembles an `AppDir` with a relocatable
Python, the GTK4/Libadwaita/GStreamer stack (via `linuxdeploy-plugin-gtk`),
bundled `ffmpeg` + `gifski`, our data files, and a custom `AppRun`, then packs it
with `linuxdeploy`. Built on **Ubuntu 22.04** so the glibc is old enough to run
on most still-supported distros (AppImages are not forward-compatible on glibc).

**This is the highest-maintenance, most fragile channel. Treat it as a portable
fallback, not the primary recommendation** (its CI job is `continue-on-error`):

- **Size:** expect 150–300 MB uncompressed.
- **Wayland/PipeWire capture is best-effort.** The bundled `libpipewire-0.3`
  must be ABI-compatible with the host's PipeWire daemon; if it isn't, Wayland
  capture fails. **X11 capture (bundled ffmpeg `xcbgrab`) is the reliable path.**
  Wayland users should prefer Flatpak.
- Every GTK/GStreamer/glibc shift on the build base can silently break loaders,
  typelibs or the Pango/HarfBuzz combo. Pin the base image.

Things `AppRun` must wire up (see the script and `AppRun`):

- `PATH` — prepend `$APPDIR/usr/bin` so the bare `ffmpeg`/`gifski` names resolve
  to the bundled binaries.
- `GI_TYPELIB_PATH` — bundle the typelibs for `Gtk-4.0, Gdk-4.0, Gsk-4.0, Adw-1,
  Gst-1.0` (+ GstBase/App/Video), `GdkPixbuf-2.0`, **`GdkX11-4.0`**, `Gio`,
  `GLib`, `GObject`, `Graphene`, Pango/PangoCairo, HarfBuzz, cairo. GdkX11 and
  Gst are easy to miss but are required by `capture/portal.py` and the recorder.
- `GST_PLUGIN_SYSTEM_PATH_1_0` / `GST_PLUGIN_PATH` + a writable `GST_REGISTRY`
  in `$HOME` — bundle `pipewiresrc` (libgstpipewire), `vp9enc` (libgstvpx),
  core/coreelements/app/videoconvert/matroska/webm, plus `libpipewire-0.3`.
- `GDK_PIXBUF_MODULE_FILE` (loaders.cache regenerated by the gtk plugin).
- `GSETTINGS_SCHEMA_DIR` (our compiled schema; falls back to JSON if absent).
- `PYTHONPATH`/`PYTHONHOME` for the bundled interpreter + `gifforge`.

Alternative tooling documented but not used: `appimage-builder` (knows about
GI/loaders/schemas via an `AppImageBuilder.yml`) and `python-appimage` (ships an
interpreter only — does not bring the GTK/GStreamer C stack).

## Release CI overview

`.github/workflows/release.yml` (on `push: tags: v*`, also `workflow_dispatch`):

| Job        | Runner        | Output                         | Notes                     |
|------------|---------------|--------------------------------|---------------------------|
| `deb`      | ubuntu-22.04  | `gif-forge_<v>_all.deb`        |                           |
| `appimage` | ubuntu-22.04  | `GIF_Forge-<v>-x86_64.AppImage`| `continue-on-error: true` |
| `flatpak`  | gnome-48 img  | `gif-forge.flatpak`            | same step as `flatpak.yml`|
| `publish`  | ubuntu-latest | attaches all + `SHA256SUMS`    | `if: always()` on tags    |

AUR and Fedora are **not** built here — publish them manually as above.
`ci.yml` and `flatpak.yml` (branch/PR CI) are unchanged.
