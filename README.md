# GIF Forge

**GIF Forge is a modern Linux screen-capture *studio*.** Record a region,
window or screen on **Wayland or X11**, then refine the result on a
**timeline** (trim, cut, reorder, retime, crop, undo/redo) before exporting an
optimized **GIF, WebM or APNG**. Projects are saveable and survive crashes.

It is built in **Python + GTK4 / Libadwaita**.

- **User guide:** [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
- **Development & build:** [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- **Packaging & releases:** [`docs/PACKAGING.md`](docs/PACKAGING.md)

## Installation

| Method | Audience | How | Notes |
|---|---|---|---|
| **Flatpak** *(recommended)* | Any distro, best Wayland support | Download `gif-forge.flatpak` from [Releases](https://github.com/elhombretecla/gif-forge/releases), then `flatpak install --user gif-forge.flatpak` | Sandboxed; bundles ffmpeg + gifski |
| **AppImage** | Portable, no install | Download the `.AppImage` from Releases, `chmod +x`, run it | X11 capture reliable; Wayland best-effort; ~150–300 MB |
| **`.deb`** | Ubuntu 22.04+ / Debian 12+ | Download from Releases, then `sudo apt install ./gif-forge_*.deb` | Uses system GTK4 / ffmpeg |
| **Arch (AUR)** | Arch / Manjaro | `yay -S gif-forge` | From the AUR |
| **Fedora (COPR)** | Fedora | `sudo dnf copr enable <owner>/gif-forge && sudo dnf install gif-forge` | Needs [RPM Fusion](https://rpmfusion.org/) for `ffmpeg` |
| **From source** | Developers | `python3 -m gifforge` or `./run.sh` | See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) |

### From source

```sh
# Run straight from a checkout (./run.sh checks dependencies first):
./run.sh
# or:
python3 -m gifforge

# Build the Flatpak:
flatpak-builder --user --install --force-clean build \
    build-aux/flatpak/io.github.elhombretecla.GifForge.yml
```

On Debian/Ubuntu the runtime dependencies are:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
    gstreamer1.0-pipewire gstreamer1.0-plugins-good ffmpeg
```

## License

GIF Forge is free software, released under the
[GNU General Public License v3.0 or later](LICENSE).

## Credits

GIF Forge began as a ground-up rewrite of
[**Peek**](https://github.com/phw/peek), the screen recorder by Philipp Wolfer,
which was [deprecated in 2024](https://github.com/phw/peek/issues/1191). GIF
Forge is an independent project — built from scratch in Python/GTK4 rather than
Peek's original Vala/GTK3 — but it builds on Peek's packaging and ffmpeg/gifski
encoding knowledge under the same GPL-3.0-or-later license.

Heartfelt thanks to Philipp Wolfer and all of Peek's contributors. See
[`AUTHORS`](AUTHORS) for full attribution.
