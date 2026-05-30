# GIF Forge

**GIF Forge is a modern Linux screen-capture *studio*.** Record a region,
window or screen on **Wayland or X11**, then refine the result on a
**timeline** (trim, cut, reorder, retime, crop, undo/redo) before exporting an
optimized **GIF, WebM or APNG**. Projects are saveable and survive crashes.

It is built in **Python + GTK4 / Libadwaita**.

- **User guide:** [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
- **Development & build:** [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)

```sh
# Run from source
python3 -m gifforge
# Build the Flatpak
flatpak-builder --user --install --force-clean build \
    build-aux/flatpak/io.github.elhombretecla.GifForge.yml
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
