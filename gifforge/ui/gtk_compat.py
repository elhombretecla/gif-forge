# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small GTK4 version-compatibility shims.

Local dev runs GTK 4.6; the target runtime is newer. A few APIs we want
(``Gtk.Picture.set_content_fit``, ``Gtk.ListView.scroll_to``) only exist in
4.8+/4.12+, so we feature-detect and degrade gracefully.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


def configure_picture_fit(picture: Gtk.Picture) -> None:
    """Make a Gtk.Picture scale-to-fit while keeping aspect ratio."""
    if hasattr(picture, "set_content_fit") and hasattr(Gtk, "ContentFit"):
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)  # GTK 4.8+
    else:  # GTK 4.6
        picture.set_can_shrink(True)
        picture.set_keep_aspect_ratio(True)


def scroll_list_to(list_view: Gtk.ListView, index: int) -> None:
    """Scroll a ListView so *index* is visible, where supported (GTK 4.12+)."""
    if hasattr(list_view, "scroll_to") and hasattr(Gtk, "ListScrollFlags"):
        try:
            list_view.scroll_to(index, Gtk.ListScrollFlags.NONE, None)
        except Exception:  # pragma: no cover - best effort
            pass
