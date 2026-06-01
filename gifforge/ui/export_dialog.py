# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export dialog: choose a preset, pick a path, encode off the main thread.

Kept deliberately small for T10 (preset + loop + destination + progress).
Phase 4 adds advanced optimization controls. The actual export runs on a worker
thread; ``export_to_path`` is exposed so it can be driven in tests without the
file chooser.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..i18n import _  # noqa: E402
from ..encode import DEFAULT_PRESETS, export_frames  # noqa: E402
from ..encode.presets import ExportPreset  # noqa: E402
from ..frames.model import FrameList  # noqa: E402

log = logging.getLogger(__name__)


class ExportDialog(Adw.Window):
    __gtype_name__ = "GifForgeExportDialog"

    def __init__(self, parent: Gtk.Window, frames: FrameList, overlays=None) -> None:
        super().__init__(transient_for=parent, modal=True)
        self.set_title(_("Export"))
        self.set_default_size(380, 220)
        self._frames = frames
        self._overlays = overlays or []
        self._busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(Adw.HeaderBar())

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title=_("Export settings"))

        self._preset_row = Adw.ComboRow(title=_("Preset"))
        self._preset_row.set_model(
            Gtk.StringList.new([p.name for p in DEFAULT_PRESETS])
        )
        group.add(self._preset_row)
        page.add(group)
        root.append(page)

        actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
            margin_top=8, margin_bottom=12, margin_start=12, margin_end=12,
            halign=Gtk.Align.END,
        )
        self._progress = Gtk.Label(label="")
        self._progress.add_css_class("dim-label")
        self._progress.set_hexpand(True)
        self._progress.set_xalign(0)
        actions.append(self._progress)

        self._spinner = Gtk.Spinner()
        actions.append(self._spinner)

        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: self.close())
        actions.append(cancel)

        self._export_button = Gtk.Button(label=_("Export…"))
        self._export_button.add_css_class("suggested-action")
        self._export_button.connect("clicked", lambda *_: self._choose_and_export())
        actions.append(self._export_button)

        root.append(actions)
        self.set_content(root)

    # --- public API ----------------------------------------------------------

    @property
    def selected_preset(self) -> ExportPreset:
        return DEFAULT_PRESETS[self._preset_row.get_selected()]

    def export_to_path(self, dest: Path) -> None:
        """Encode to *dest* on a worker thread (also used by tests)."""
        if self._busy:
            return
        self._busy = True
        preset = self.selected_preset
        self._export_button.set_sensitive(False)
        self._progress.set_label(_("Encoding…"))
        self._spinner.start()
        thread = threading.Thread(
            target=self._worker, args=(preset, Path(dest)), daemon=True
        )
        thread.start()

    # --- internals -----------------------------------------------------------

    def _choose_and_export(self) -> None:
        preset = self.selected_preset
        ext = preset.output_format.file_extension
        default_name = time.strftime(f"{APP_NAME} %Y-%m-%d %H-%M") + f".{ext}"
        chooser = Gtk.FileChooserNative(
            title=_("Export recording"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label=_("_Export"),
            cancel_label=_("_Cancel"),
        )
        chooser.set_current_name(default_name)
        chooser.connect("response", self._on_chooser_response)
        self._chooser = chooser
        chooser.show()

    def _on_chooser_response(self, chooser, response: int) -> None:
        path = chooser.get_file().get_path() if response == Gtk.ResponseType.ACCEPT else None
        chooser.destroy()
        self._chooser = None
        if path:
            self.export_to_path(Path(path))

    def _worker(self, preset: ExportPreset, dest: Path) -> None:
        render_cache = None
        try:
            frames = self._frames
            if self._overlays:
                from ..frames.overlay_render import render_overlays
                from ..project.cache import SessionCache

                render_cache = SessionCache()
                frames = render_overlays(self._frames, self._overlays, render_cache)
            export_frames(frames, preset.output_format, dest, loop=preset.loop)
            GLib.idle_add(self._on_done, dest)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self._on_error, str(exc))
        finally:
            if render_cache is not None:
                render_cache.cleanup()

    def _on_done(self, dest: Path) -> bool:
        self._spinner.stop()
        self._notify(dest)
        self.close()
        return False

    def _on_error(self, message: str) -> bool:
        self._busy = False
        self._spinner.stop()
        self._export_button.set_sensitive(True)
        self._progress.set_label(_("Failed: {error}").format(error=message))
        log.error("export failed: %s", message)
        return False

    def _notify(self, dest: Path) -> None:
        app = self.get_transient_for().get_application() if self.get_transient_for() else None
        if app is None:
            return
        note = Gio.Notification.new(_("Export complete"))
        note.set_body(str(dest))
        app.send_notification("gif-forge-exported", note)
