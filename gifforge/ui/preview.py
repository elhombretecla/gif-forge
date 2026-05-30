# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview panel: shows the current frame over a transparency checker.

A cairo-drawn checkerboard sits behind a ``Gtk.Picture``; PNG alpha composites
over it so transparent regions read correctly. Supports fit-to-window (default)
and 100% zoom (scrolls when larger than the viewport).
"""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .gtk_compat import configure_picture_fit  # noqa: E402

log = logging.getLogger(__name__)

_CHECK = 12  # checker square size in px
_LIGHT = (0.55, 0.55, 0.55)
_DARK = (0.40, 0.40, 0.40)


class Preview(Gtk.ScrolledWindow):
    __gtype_name__ = "PeekPreview"

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._texture_cache: dict[str, Gdk.Texture] = {}
        self._texture: Gdk.Texture | None = None
        self._zoom_fit = True

        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        self._checker = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self._checker.set_draw_func(self._draw_checker)
        overlay.set_child(self._checker)

        self._picture = Gtk.Picture(hexpand=True, vexpand=True)
        configure_picture_fit(self._picture)
        overlay.add_overlay(self._picture)

        self.set_child(overlay)

    # --- public API ----------------------------------------------------------

    def show_path(self, path: Path | str) -> None:
        self._texture = self._texture_for(str(path))
        self._picture.set_paintable(self._texture)
        self._apply_zoom()

    def clear(self) -> None:
        self._texture = None
        self._picture.set_paintable(None)

    def set_zoom_fit(self, fit: bool) -> None:
        self._zoom_fit = fit
        self._apply_zoom()

    @property
    def zoom_fit(self) -> bool:
        return self._zoom_fit

    # --- internals -----------------------------------------------------------

    def _apply_zoom(self) -> None:
        if self._zoom_fit or self._texture is None:
            self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
            self._picture.set_size_request(-1, -1)
            if hasattr(self._picture, "set_can_shrink"):
                self._picture.set_can_shrink(True)
        else:
            self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self._picture.set_size_request(
                self._texture.get_width(), self._texture.get_height()
            )
            if hasattr(self._picture, "set_can_shrink"):
                self._picture.set_can_shrink(False)

    def _texture_for(self, path: str) -> Gdk.Texture:
        texture = self._texture_cache.get(path)
        if texture is None:
            texture = Gdk.Texture.new_from_filename(path)
            self._texture_cache[path] = texture
        return texture

    def _draw_checker(self, _area, cr, width, height) -> None:
        rows = height // _CHECK + 1
        cols = width // _CHECK + 1
        for row in range(rows):
            for col in range(cols):
                r, g, b = _LIGHT if (row + col) % 2 == 0 else _DARK
                cr.set_source_rgb(r, g, b)
                cr.rectangle(col * _CHECK, row * _CHECK, _CHECK, _CHECK)
                cr.fill()
