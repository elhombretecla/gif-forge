# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Horizontal frame-strip (timeline) widget.

Backed by a ``Gtk.ListView`` so only visible thumbnails are realized — this is
what keeps a several-hundred-frame strip responsive. Thumbnail textures are
cached by (path, height); duplicated frames share a path and therefore reuse
the same texture for free.

Emits ``current-changed(index)`` when the selected frame changes.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk  # noqa: E402

from ..frames.model import FrameList  # noqa: E402
from .gtk_compat import configure_picture_fit, scroll_list_to  # noqa: E402

log = logging.getLogger(__name__)

_STRIP_CSS = b"""
.frame-strip { padding: 6px; }
.frame-strip > row, .frame-strip child { padding: 3px; border-radius: 6px; }
.frame-thumb { border-radius: 4px; border: 1px solid alpha(currentColor, 0.15); }
.frame-cell-info { padding: 0 2px; font-size: 0.8em; }
.frame-index { font-weight: bold; }
.frame-delay { font-style: italic; }
"""

THUMB_HEIGHT = 72


class FrameObject(GObject.Object):
    __gtype_name__ = "GifForgeFrameObject"

    def __init__(self, index: int, path: str, delay_ms: int) -> None:
        super().__init__()
        self.index = index
        self.path = path
        self.delay_ms = delay_ms


class FrameStrip(Gtk.ScrolledWindow):
    __gtype_name__ = "GifForgeFrameStrip"
    __gsignals__ = {
        "current-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.set_min_content_height(THUMB_HEIGHT + 44)
        self._texture_cache: dict[tuple[str, int], Gdk.Texture] = {}

        self._store = Gio.ListStore(item_type=FrameObject)
        self._selection = Gtk.MultiSelection(model=self._store)
        self._selection.connect("selection-changed", self._on_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)

        self._list = Gtk.ListView(model=self._selection, factory=factory)
        self._list.set_orientation(Gtk.Orientation.HORIZONTAL)
        self._list.add_css_class("frame-strip")
        self.set_child(self._list)

        provider = Gtk.CssProvider()
        provider.load_from_data(_STRIP_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # --- public API ----------------------------------------------------------

    def set_frames(self, frames: FrameList) -> None:
        self._store.remove_all()
        for i, frame in enumerate(frames):
            self._store.append(FrameObject(i, str(frame.path), frame.delay_ms))
        if len(frames):
            self.select(0)

    def get_current_index(self) -> int:
        """The frame shown in the preview — the lowest selected index."""
        indices = self.get_selected_indices()
        return indices[0] if indices else -1

    def get_selected_indices(self) -> list[int]:
        bitset = self._selection.get_selection()
        return [bitset.get_nth(i) for i in range(bitset.get_size())]

    def select(self, index: int) -> None:
        """Select a single frame (used by navigation/playback)."""
        if 0 <= index < self._store.get_n_items():
            self._selection.select_item(index, True)  # unselect the rest
            scroll_list_to(self._list, index)

    def select_all(self) -> None:
        if self._store.get_n_items():
            self._selection.select_all()

    def select_none(self) -> None:
        self._selection.unselect_all()

    def invert_selection(self) -> None:
        n = self._store.get_n_items()
        if not n:
            return
        everything = Gtk.Bitset.new_range(0, n)
        inverted = everything.copy()
        inverted.subtract(self._selection.get_selection())
        self._selection.set_selection(inverted, everything)

    # --- factory callbacks ---------------------------------------------------

    def _on_setup(self, _factory, item: Gtk.ListItem) -> None:
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        picture = Gtk.Picture()
        picture.add_css_class("frame-thumb")
        picture.set_size_request(-1, THUMB_HEIGHT)
        configure_picture_fit(picture)
        cell.append(picture)

        info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        info.add_css_class("frame-cell-info")
        index_label = Gtk.Label(xalign=0, hexpand=True)
        index_label.add_css_class("frame-index")
        delay_label = Gtk.Label(xalign=1)
        delay_label.add_css_class("frame-delay")
        delay_label.add_css_class("dim-label")
        info.append(index_label)
        info.append(delay_label)
        cell.append(info)

        # Stash references for fast binding.
        cell._picture = picture
        cell._index_label = index_label
        cell._delay_label = delay_label
        item.set_child(cell)

    def _on_bind(self, _factory, item: Gtk.ListItem) -> None:
        obj: FrameObject = item.get_item()
        cell = item.get_child()
        cell._picture.set_paintable(self._texture_for(obj.path, THUMB_HEIGHT))
        cell._index_label.set_label(str(obj.index))
        cell._delay_label.set_label(f"{obj.delay_ms} ms")

    def _texture_for(self, path: str, height: int) -> Gdk.Texture:
        key = (path, height)
        texture = self._texture_cache.get(key)
        if texture is None:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, -1, height, True)
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._texture_cache[key] = texture
        return texture

    def _on_selection_changed(self, _selection, _position, _n_items) -> None:
        index = self.get_current_index()
        if index >= 0:
            self.emit("current-changed", index)
