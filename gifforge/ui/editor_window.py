# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Editor window: preview + frame-strip timeline + playback (T8).

Selection is the single source of truth: the frame strip's ``current-changed``
drives the preview and the status line, and playback simply advances the
selection on a per-frame timer. Frame operations (T9) and export (T10) build on
this window.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..editor import (  # noqa: E402
    AdjustDelay,
    DeleteFrames,
    DuplicateFrames,
    InsertFrames,
    ReduceFrames,
    RemoveDuplicates,
    ReverseFrames,
    ScaleDelay,
    SetDelay,
    TextOverlay,
    Timeline,
    TrimFrames,
)
from ..frames.model import FrameList  # noqa: E402
from ..i18n import _  # noqa: E402
from ..models import OutputFormat  # noqa: E402
from ..project import (  # noqa: E402
    PROJECT_SUFFIX,
    ProjectDocument,
    RecentProjects,
    SessionCache,
    autosave,
    clear_autosave,
    load_project,
    save_project,
)
from .frame_strip import FrameStrip  # noqa: E402
from .preview import Preview  # noqa: E402

_DELAY_STEP_MS = 20
_AUTOSAVE_DEBOUNCE_MS = 1500

log = logging.getLogger(__name__)


class EditorWindow(Adw.ApplicationWindow):
    __gtype_name__ = "PeekEditorWindow"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title(_("Editor") + " — GIF Forge")
        self.set_default_size(720, 560)

        self._frames: FrameList = FrameList()
        self._timeline: Timeline | None = None
        self._current = -1
        self._playing = False
        self._loop = True
        self._play_source = 0

        # Project/session state.
        self._session_id = f"editor-{os.getpid()}-{int(time.time())}-{id(self) & 0xffff}"
        self._session_cache: SessionCache | None = None
        self._project_path = None
        self._output_format = OutputFormat.GIF
        self._overlays: list = []
        self._clipboard: list = []  # copied/cut frames
        self._autosave_source = 0
        self._recents = RecentProjects()

        self._build_ui()
        self._setup_actions()
        self._setup_shortcuts()
        self.connect("close-request", self._on_close_request)

    # --- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self._install_css()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        self._export_button = Gtk.Button(label=_("Export…"))
        self._export_button.add_css_class("suggested-action")
        self._export_button.set_sensitive(False)
        self._export_button.set_tooltip_text(_("Export the edited timeline"))
        self._export_button.connect("clicked", lambda *_: self.open_export_dialog())
        header.pack_end(self._export_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_menu_model(self._build_menu())
        header.pack_end(menu_button)
        root.append(header)

        root.append(self._build_toolbar())

        self._preview = Preview()
        root.append(self._preview)

        self._strip = FrameStrip()
        self._strip.connect("current-changed", self._on_strip_current)
        root.append(self._strip)

        root.append(self._build_bottom_bar())
        self.set_content(root)

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()

        projects = Gio.Menu()
        projects.append(_("Open project…"), "win.open-project")
        projects.append(_("Save project…"), "win.save-project")
        menu.append_section(None, projects)

        frames = Gio.Menu()
        frames.append(_("Delete selected"), "win.delete")
        frames.append(_("Duplicate selected"), "win.duplicate")
        frames.append(_("Trim to selection"), "win.trim")
        menu.append_section(None, frames)

        captions = Gio.Menu()
        captions.append(_("Add caption…"), "win.add-caption")
        menu.append_section(None, captions)

        timing = Gio.Menu()
        timing.append(_("Reverse"), "win.reverse")
        timing.append(_("Remove duplicate frames"), "win.dedup")
        timing.append(_("Reduce frames (keep every 2nd)"), "win.reduce")
        menu.append_section(None, timing)

        speed = Gio.Menu()
        speed.append(_("Double speed"), "win.speed-up")
        speed.append(_("Half speed"), "win.speed-down")
        speed.append(_("Increase delay"), "win.delay-up")
        speed.append(_("Decrease delay"), "win.delay-down")
        menu.append_section(None, speed)

        return menu

    def _install_css(self) -> None:
        css = b"""
        .editor-toolbar { padding: 6px 10px; }
        .toolbar-group-label { font-size: 0.78em; }
        .tool-button { padding: 4px 8px; }
        .tool-button label { font-size: 0.82em; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # --- ribbon-style toolbar ------------------------------------------------

    def _tool_button(self, icon: str, label: str, callback, *, toggle=False):
        btn = Gtk.ToggleButton() if toggle else Gtk.Button()
        btn.add_css_class("flat")
        btn.add_css_class("tool-button")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.set_halign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(20)
        content.append(image)
        content.append(Gtk.Label(label=label))
        btn.set_child(content)
        btn.set_tooltip_text(label)
        if not toggle:
            btn.connect("clicked", lambda *_: callback())
        return btn

    def _group(self, title: str, buttons) -> Gtk.Box:
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for b in buttons:
            row.append(b)
        group.append(row)
        label = Gtk.Label(label=title)
        label.add_css_class("toolbar-group-label")
        label.add_css_class("dim-label")
        group.append(label)
        return group

    def _build_toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("editor-toolbar")

        def sep():
            bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Action stack.
        self._undo_button = self._tool_button("edit-undo-symbolic", _("Undo"), self.undo)
        self._redo_button = self._tool_button("edit-redo-symbolic", _("Redo"), self.redo)
        reset_btn = self._tool_button("edit-clear-all-symbolic", _("Reset"), self.reset)
        bar.append(self._group(_("Action"), [self._undo_button, self._redo_button, reset_btn]))
        sep()

        # Clipboard.
        bar.append(self._group(_("Clipboard"), [
            self._tool_button("edit-copy-symbolic", _("Copy"), self.copy_frames),
            self._tool_button("edit-cut-symbolic", _("Cut"), self.cut_frames),
            self._tool_button("edit-paste-symbolic", _("Paste"), self.paste_frames),
        ]))
        sep()

        # Frame operations.
        bar.append(self._group(_("Frames"), [
            self._tool_button("edit-delete-symbolic", _("Delete"), self.delete_selected),
            self._tool_button("list-add-symbolic", _("Duplicate"), self.duplicate_selected),
            self._tool_button("document-edit-symbolic", _("Delay…"), self.set_delay_dialog),
        ]))
        sep()

        # Selection.
        bar.append(self._group(_("Select"), [
            self._tool_button("edit-select-all-symbolic", _("All"), self.select_all),
            self._tool_button("object-flip-horizontal-symbolic", _("Inverse"), self.invert_selection),
            self._tool_button("edit-clear-symbolic", _("None"), self.deselect),
            self._tool_button("go-jump-symbolic", _("Go to…"), self.go_to_dialog),
        ]))
        sep()

        # Zoom.
        self._zoom_fit_button = self._tool_button("zoom-fit-best-symbolic", _("Fit"), None, toggle=True)
        self._zoom_fit_button.set_active(True)
        self._zoom_fit_button.connect("toggled", self._on_zoom_fit_toggled)
        zoom_100 = self._tool_button("zoom-original-symbolic", "100%", self._zoom_100)
        bar.append(self._group(_("Zoom"), [self._zoom_fit_button, zoom_100]))

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_child(bar)
        return scroller

    def _build_bottom_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("toolbar")
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        bar.set_margin_start(8)
        bar.set_margin_end(8)

        def nav(icon, tip, cb):
            b = Gtk.Button(icon_name=icon)
            b.add_css_class("flat")
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            bar.append(b)
            return b

        nav("go-first-symbolic", _("First frame"), self.go_first)
        nav("go-previous-symbolic", _("Previous frame"), self.go_previous)
        self._play_button = nav("media-playback-start-symbolic", _("Play / Pause"), self.toggle_play)
        nav("go-next-symbolic", _("Next frame"), self.go_next)
        nav("go-last-symbolic", _("Last frame"), self.go_last)

        self._loop_button = Gtk.ToggleButton(icon_name="media-playlist-repeat-symbolic")
        self._loop_button.add_css_class("flat")
        self._loop_button.set_tooltip_text(_("Loop playback"))
        self._loop_button.set_active(self._loop)
        self._loop_button.connect("toggled", lambda b: setattr(self, "_loop", b.get_active()))
        bar.append(self._loop_button)

        bar.append(Gtk.Box(hexpand=True))
        self._status = Gtk.Label(label=_("No frames"))
        self._status.add_css_class("dim-label")
        bar.append(self._status)
        return bar

    def _on_zoom_fit_toggled(self, button: Gtk.ToggleButton) -> None:
        self._preview.set_zoom_fit(button.get_active())

    def _zoom_100(self) -> None:
        self._zoom_fit_button.set_active(False)  # triggers set_zoom_fit(False)

    # --- public API ----------------------------------------------------------

    def load(self, frames: FrameList, *, cache: SessionCache | None = None) -> None:
        self._pause()
        if cache is not None:
            self._session_cache = cache
        self._frames = frames
        self._timeline = Timeline(frames)
        self._refresh(select_index=0)

    def load_document(self, document: ProjectDocument, cache: SessionCache) -> None:
        """Load a saved/recovered project into the editor."""
        self._project_path = document.path
        self._output_format = document.output_format
        self._overlays = list(document.overlays)
        if document.path:
            self.set_title(f"{document.title} — GIF Forge")
            self._recents.add(document.path)
        self.load(document.frames, cache=cache)

    @property
    def current_index(self) -> int:
        return self._current

    @property
    def timeline(self) -> Timeline | None:
        return self._timeline

    def _refresh(self, select_index: int | None = None) -> None:
        """Rebuild the strip after a structural edit and resync preview/state."""
        n = len(self._frames)
        self._strip.set_frames(self._frames)
        if n == 0:
            self._current = -1
            self._preview.clear()
        else:
            if select_index is None:
                select_index = self._current
            select_index = max(0, min(n - 1, select_index))
            self._strip.select(select_index)
            self._current = select_index
            self._preview.show_path(self._frames[select_index].path)
        self._update_history_buttons()
        self._update_status()
        self._schedule_autosave()

    def _update_history_buttons(self) -> None:
        tl = self._timeline
        self._undo_button.set_sensitive(bool(tl and tl.can_undo))
        self._redo_button.set_sensitive(bool(tl and tl.can_redo))
        self._export_button.set_sensitive(len(self._frames) > 0)

    # --- navigation ----------------------------------------------------------

    def go_first(self) -> None:
        self._strip.select(0)

    def go_last(self) -> None:
        self._strip.select(len(self._frames) - 1)

    def go_previous(self) -> None:
        self._strip.select(max(0, self._current - 1))

    def go_next(self) -> None:
        self._strip.select(min(len(self._frames) - 1, self._current + 1))

    # --- playback ------------------------------------------------------------

    def toggle_play(self) -> None:
        self._pause() if self._playing else self._play()

    def _play(self) -> None:
        if len(self._frames) < 2:
            return
        if self._current >= len(self._frames) - 1 and not self._loop:
            self._strip.select(0)
        self._playing = True
        self._play_button.set_icon_name("media-playback-pause-symbolic")
        self._schedule_advance()

    def _pause(self) -> None:
        self._playing = False
        if self._play_source:
            GLib.source_remove(self._play_source)
            self._play_source = 0
        self._play_button.set_icon_name("media-playback-start-symbolic")

    def _schedule_advance(self) -> None:
        delay = max(10, self._frames[self._current].delay_ms)
        self._play_source = GLib.timeout_add(delay, self._advance)

    def _advance(self) -> bool:
        self._play_source = 0
        nxt = self._current + 1
        if nxt >= len(self._frames):
            if not self._loop:
                self._pause()
                return False
            nxt = 0
        self._strip.select(nxt)
        if self._playing:
            self._schedule_advance()
        return False

    # --- actions & shortcuts -------------------------------------------------

    def _setup_actions(self) -> None:
        actions = {
            "delete": self.delete_selected,
            "duplicate": self.duplicate_selected,
            "reverse": self.reverse_all,
            "dedup": self.remove_duplicates,
            "reduce": lambda: self.reduce_frames(2),
            "speed-up": lambda: self.change_speed(0.5),
            "speed-down": lambda: self.change_speed(2.0),
            "delay-up": lambda: self.adjust_delay(_DELAY_STEP_MS),
            "delay-down": lambda: self.adjust_delay(-_DELAY_STEP_MS),
            "trim": self.trim_to_selection,
            "undo": self.undo,
            "redo": self.redo,
            "reset": self.reset,
            "copy": self.copy_frames,
            "cut": self.cut_frames,
            "paste": self.paste_frames,
            "select-all": self.select_all,
            "deselect": self.deselect,
            "invert": self.invert_selection,
            "go-to": self.go_to_dialog,
            "set-delay": self.set_delay_dialog,
            "save-project": self.save_project,
            "open-project": self.open_project,
            "add-caption": self.add_caption_dialog,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)

    def _setup_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.MANAGED)
        for accel, callback in (
            ("Delete", self.delete_selected),
            ("<Primary>d", self.duplicate_selected),
            ("<Primary>c", self.copy_frames),
            ("<Primary>x", self.cut_frames),
            ("<Primary>v", self.paste_frames),
            ("<Primary>a", self.select_all),
            ("<Primary>z", self.undo),
            ("<Primary><Shift>z", self.redo),
            ("<Primary>y", self.redo),
            ("<Primary>s", self.save_project),
            ("<Primary>o", self.open_project),
            ("space", self.toggle_play),
        ):
            shortcut = Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(accel),
                action=Gtk.CallbackAction.new(
                    lambda _w, _a, cb=callback: (cb(), True)[1]
                ),
            )
            controller.add_shortcut(shortcut)
        self.add_controller(controller)

    # --- edit operations -----------------------------------------------------

    def _selected_indices(self) -> list[int]:
        indices = self._strip.get_selected_indices()
        if not indices and self._current >= 0:
            indices = [self._current]
        return indices

    def _execute(self, command, *, select_index: int | None = None) -> None:
        if self._timeline is None:
            return
        self._pause()
        self._timeline.execute(command)
        self._refresh(select_index=select_index)

    def delete_selected(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        if len(indices) >= len(self._frames):
            self._status.set_label(_("Can't delete every frame"))
            return
        self._execute(DeleteFrames(indices), select_index=min(indices))

    def duplicate_selected(self) -> None:
        indices = self._selected_indices()
        if indices:
            self._execute(DuplicateFrames(indices), select_index=min(indices))

    def reverse_all(self) -> None:
        self._execute(ReverseFrames(), select_index=self._current)

    def remove_duplicates(self) -> None:
        self._execute(RemoveDuplicates(), select_index=0)

    def reduce_frames(self, keep_every: int) -> None:
        self._execute(ReduceFrames(keep_every), select_index=0)

    def change_speed(self, factor: float) -> None:
        indices = self._selected_indices() or list(range(len(self._frames)))
        self._execute(ScaleDelay(indices, factor), select_index=self._current)

    def adjust_delay(self, delta_ms: int) -> None:
        indices = self._selected_indices() or list(range(len(self._frames)))
        self._execute(AdjustDelay(indices, delta_ms), select_index=self._current)

    def trim_to_selection(self) -> None:
        indices = self._selected_indices()
        if len(indices) < 1:
            return
        self._execute(TrimFrames(min(indices), max(indices)), select_index=0)

    def reset(self) -> None:
        if self._timeline is None:
            return
        self._pause()
        self._timeline.reset()
        self._refresh(select_index=0)

    # --- clipboard -----------------------------------------------------------

    def copy_frames(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        self._clipboard = [self._frames[i].clone() for i in indices]
        self._status.set_label(
            _("Copied {count} frame(s)").format(count=len(self._clipboard))
        )

    def cut_frames(self) -> None:
        indices = self._selected_indices()
        if not indices or len(indices) >= len(self._frames):
            self._status.set_label(_("Can't cut every frame"))
            return
        self._clipboard = [self._frames[i].clone() for i in indices]
        self._execute(DeleteFrames(indices), select_index=min(indices))

    def paste_frames(self) -> None:
        if not self._clipboard:
            return
        at = self._current + 1 if self._current >= 0 else len(self._frames)
        self._execute(InsertFrames(at, self._clipboard), select_index=at)

    # --- selection -----------------------------------------------------------

    def select_all(self) -> None:
        self._strip.select_all()

    def deselect(self) -> None:
        self._strip.select_none()

    def invert_selection(self) -> None:
        self._strip.invert_selection()

    def go_to_dialog(self) -> None:
        n = len(self._frames)
        if n == 0:
            return
        dialog = Gtk.Window(transient_for=self, modal=True, title=_("Go to frame"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        spin = Gtk.SpinButton.new_with_range(0, n - 1, 1)
        spin.set_value(max(0, self._current))
        box.append(Gtk.Label(label=_("Frame number (0–{max}):").format(max=n - 1), xalign=0))
        box.append(spin)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: dialog.close())
        go = Gtk.Button(label=_("Go"))
        go.add_css_class("suggested-action")

        def commit(*_a):
            self._strip.select(int(spin.get_value()))
            dialog.close()

        go.connect("clicked", commit)
        spin.connect("activate", commit)
        buttons.append(cancel)
        buttons.append(go)
        box.append(buttons)
        dialog.set_child(box)
        dialog.present()

    # --- timing --------------------------------------------------------------

    def set_delay_dialog(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        current_delay = self._frames[indices[0]].delay_ms
        dialog = Gtk.Window(transient_for=self, modal=True, title=_("Frame delay"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        spin = Gtk.SpinButton.new_with_range(1, 60000, 1)
        spin.set_value(current_delay)
        box.append(Gtk.Label(
            label=_("Delay for {count} frame(s), in ms:").format(count=len(indices)),
            xalign=0,
        ))
        box.append(spin)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: dialog.close())
        apply_btn = Gtk.Button(label=_("Apply"))
        apply_btn.add_css_class("suggested-action")

        def commit(*_a):
            self._execute(SetDelay(indices, int(spin.get_value())), select_index=self._current)
            dialog.close()

        apply_btn.connect("clicked", commit)
        spin.connect("activate", commit)
        buttons.append(cancel)
        buttons.append(apply_btn)
        box.append(buttons)
        dialog.set_child(box)
        dialog.present()

    # --- annotations ---------------------------------------------------------

    def add_caption_dialog(self) -> None:
        if not len(self._frames):
            return
        dialog = Gtk.Window(transient_for=self, modal=True, title=_("Add caption"))
        dialog.set_default_size(320, -1)
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=16, margin_bottom=16, margin_start=16, margin_end=16,
        )
        entry = Gtk.Entry(placeholder_text=_("Caption text"))
        entry.set_hexpand(True)
        box.append(entry)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: dialog.close())
        add = Gtk.Button(label=_("Add"))
        add.add_css_class("suggested-action")

        def commit(*_a):
            text = entry.get_text().strip()
            if text:
                self.add_caption(text)
            dialog.close()

        add.connect("clicked", commit)
        entry.connect("activate", commit)
        buttons.append(cancel)
        buttons.append(add)
        box.append(buttons)
        dialog.set_child(box)
        dialog.present()

    def add_caption(self, text: str) -> None:
        """Add a text caption over the current selection (or whole timeline)."""
        indices = self._strip.get_selected_indices()
        if indices:
            start, end = min(indices), max(indices)
        else:
            start, end = 0, -1
        self._overlays.append(TextOverlay(start=start, end=end, text=text))
        self._status.set_label(_("Caption added: “{text}”").format(text=text))
        self._schedule_autosave()

    # --- projects & autosave -------------------------------------------------

    def _document(self) -> ProjectDocument:
        return ProjectDocument(
            frames=self._frames,
            output_format=self._output_format,
            path=self._project_path,
            overlays=list(self._overlays),
        )

    def save_project(self) -> None:
        if not len(self._frames):
            return
        if self._project_path is not None:
            self._write_project(self._project_path)
            return
        chooser = Gtk.FileChooserNative(
            title=_("Save project"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label=_("_Save"),
        )
        chooser.set_current_name(f"Untitled{PROJECT_SUFFIX}")
        chooser.connect("response", self._on_save_project_response)
        self._save_chooser = chooser
        chooser.show()

    def _on_save_project_response(self, chooser, response: int) -> None:
        path = chooser.get_file().get_path() if response == Gtk.ResponseType.ACCEPT else None
        chooser.destroy()
        self._save_chooser = None
        if path:
            if not path.endswith(PROJECT_SUFFIX):
                path += PROJECT_SUFFIX
            self._write_project(Path(path))

    def _write_project(self, path) -> None:
        from pathlib import Path as _Path

        doc = self._document()
        save_project(doc, _Path(path))
        self._project_path = doc.path
        self._recents.add(doc.path)
        self.set_title(f"{doc.title} — GIF Forge")
        self._status.set_label(_("Saved project to {path}").format(path=doc.path))

    def open_project(self) -> None:
        chooser = Gtk.FileChooserNative(
            title=_("Open project"),
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=_("_Open"),
        )
        chooser.connect("response", self._on_open_project_response)
        self._open_chooser = chooser
        chooser.show()

    def _on_open_project_response(self, chooser, response: int) -> None:
        path = chooser.get_file().get_path() if response == Gtk.ResponseType.ACCEPT else None
        chooser.destroy()
        self._open_chooser = None
        if path:
            self.open_project_path(Path(path))

    def open_project_path(self, path) -> None:
        from pathlib import Path as _Path

        cache = SessionCache()
        try:
            document = load_project(_Path(path), cache)
        except Exception as exc:  # noqa: BLE001
            cache.cleanup()
            self._show_error(_("Could not open project"), str(exc))
            return
        self._adopt_cache(cache)
        self.load_document(document, cache)

    def _adopt_cache(self, cache: SessionCache) -> None:
        # Replace any previous session cache (clean up the old one).
        if self._session_cache is not None and self._session_cache is not cache:
            self._session_cache.cleanup()
        self._session_cache = cache

    def _schedule_autosave(self) -> None:
        if not len(self._frames):
            return
        if self._autosave_source:
            GLib.source_remove(self._autosave_source)
        self._autosave_source = GLib.timeout_add(
            _AUTOSAVE_DEBOUNCE_MS, self._do_autosave
        )

    def _do_autosave(self) -> bool:
        self._autosave_source = 0
        try:
            autosave(self._document(), self._session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("autosave failed: %s", exc)
        return False

    def _on_close_request(self, *_args) -> bool:
        if self._autosave_source:
            GLib.source_remove(self._autosave_source)
            self._autosave_source = 0
        # Clean close: drop the recovery snapshot and session cache.
        clear_autosave(self._session_id)
        if self._session_cache is not None:
            self._session_cache.cleanup()
            self._session_cache = None
        return False  # allow close

    def _show_error(self, title: str, detail: str) -> None:
        log.error("%s: %s", title, detail)
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE, text=title, secondary_text=detail,
        )
        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.show()

    def open_export_dialog(self) -> None:
        if not len(self._frames):
            return
        self._pause()
        from .export_dialog import ExportDialog

        dialog = ExportDialog(self, self._frames, self._overlays)
        dialog.present()

    def undo(self) -> None:
        if self._timeline and self._timeline.can_undo:
            self._pause()
            self._timeline.undo()
            self._refresh(select_index=self._current)

    def redo(self) -> None:
        if self._timeline and self._timeline.can_redo:
            self._pause()
            self._timeline.redo()
            self._refresh(select_index=self._current)

    # --- callbacks -----------------------------------------------------------

    def _on_strip_current(self, _strip, index: int) -> None:
        self._current = index
        if 0 <= index < len(self._frames):
            self._preview.show_path(self._frames[index].path)
        self._update_status()

    def _update_status(self) -> None:
        n = len(self._frames)
        if n == 0:
            self._status.set_label(_("No frames"))
            return
        selected = len(self._strip.get_selected_indices())
        total_s = self._frames.total_duration_ms / 1000
        self._status.set_label(
            _("{count} frames · {selected} selected · #{current} · {seconds:.1f}s").format(
                count=n, selected=selected, current=self._current, seconds=total_s
            )
        )
