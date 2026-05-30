# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The main recorder window and full record→encode→save workflow (T5).

The window frames a transparent capture region (the desktop shows through on a
compositing desktop). Pressing Record runs an optional countdown, captures the
region via the best available backend, encodes off the main thread, then offers
a save dialog and a desktop notification.

Region extraction uses X11 absolute geometry today; on Wayland the ScreenCast
portal supplies the region (T4), so :meth:`_extract_area` raises a clear error
there until that backend lands.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..encode.errors import RecordingError  # noqa: E402
from ..models import OutputFormat, RecordingArea, RecordingConfig  # noqa: E402
from ..recorder import RecordingController  # noqa: E402
from ..settings import get_settings  # noqa: E402

log = logging.getLogger(__name__)

_CSS = b"""
.gifforge-recorder.background { background-color: transparent; }
.gifforge-recorder headerbar { background-color: @headerbar_bg_color; }
.recorder-bottom-bar { background-color: @window_bg_color; padding: 8px 12px; }
.capture-area {
  background-color: transparent;
  box-shadow: inset 0 0 0 2px alpha(@accent_color, 0.8);
}
.countdown-label { font-size: 64px; font-weight: bold; }
.recording-timer {
  font-size: 20px;
  font-weight: bold;
  font-feature-settings: "tnum";
  color: @error_color;
  margin-right: 2px;
}
"""


class RecorderWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(520, 360)
        self.add_css_class("gifforge-recorder")

        self._settings = get_settings()
        self._controller: Optional[RecordingController] = None
        self._countdown_source: int = 0
        self._timer_source: int = 0
        self._elapsed: int = 0
        self._save_dialog: Optional[Gtk.FileChooserNative] = None
        self._syncing_size = False  # guard against spin<->capture-area feedback

        self._install_css()
        self._build_ui()
        self._init_format_from_settings()
        # Float above other windows and let clicks pass through the capture hole.
        self.connect("map", self._on_mapped)

    # --- construction --------------------------------------------------------

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        self._format_dropdown = Gtk.DropDown.new_from_strings(
            [fmt.value.upper() for fmt in OutputFormat]
        )
        self._format_dropdown.set_tooltip_text("Output format")
        header.pack_start(self._format_dropdown)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gtk.Builder.new_from_string(_MENU_XML, -1).get_object("primary-menu")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        root.append(header)

        # Transparent capture region (a DrawingArea so we get a `resize` signal
        # to keep the size inputs in sync), with hint + countdown overlays.
        overlay = Gtk.Overlay(vexpand=True)
        self._capture_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self._capture_area.add_css_class("capture-area")
        self._capture_area.connect("resize", self._on_capture_resize)
        overlay.set_child(self._capture_area)

        self._hint = Gtk.Label(label="Position this window over what you want to capture")
        self._hint.add_css_class("dim-label")
        self._hint.set_halign(Gtk.Align.CENTER)
        self._hint.set_valign(Gtk.Align.CENTER)
        self._hint.set_can_target(False)
        overlay.add_overlay(self._hint)

        self._countdown_label = Gtk.Label(label="")
        self._countdown_label.add_css_class("countdown-label")
        self._countdown_label.set_halign(Gtk.Align.CENTER)
        self._countdown_label.set_valign(Gtk.Align.CENTER)
        self._countdown_label.set_visible(False)
        self._countdown_label.set_can_target(False)
        overlay.add_overlay(self._countdown_label)
        root.append(overlay)

        root.append(self._build_bottom_bar())
        self.set_content(root)

    def _build_bottom_bar(self) -> Gtk.Box:
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.add_css_class("recorder-bottom-bar")

        # Left: editable recording-size inputs (in output pixels). Plain entries
        # (no spin steppers) — applied on Enter or focus-out, clamped on apply.
        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        size_box.set_valign(Gtk.Align.CENTER)
        self._width_entry = self._make_size_entry("Recording width in pixels")
        self._height_entry = self._make_size_entry("Recording height in pixels")
        times = Gtk.Label(label="×")
        times.add_css_class("dim-label")
        unit = Gtk.Label(label="px")
        unit.add_css_class("dim-label")
        size_box.append(self._width_entry)
        size_box.append(times)
        size_box.append(self._height_entry)
        size_box.append(unit)
        bottom.append(size_box)

        bottom.append(Gtk.Box(hexpand=True))

        # Right: status + spinner + the Record button.
        self._status_label = Gtk.Label(label="", xalign=1)
        self._status_label.add_css_class("dim-label")
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_label.set_max_width_chars(16)
        bottom.append(self._status_label)

        self._spinner = Gtk.Spinner()
        bottom.append(self._spinner)

        # Timer + Record button live in a tight box so the elapsed-time counter
        # sits flush against the button while recording.
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_valign(Gtk.Align.CENTER)

        self._timer_label = Gtk.Label(label="00:00")
        self._timer_label.add_css_class("recording-timer")
        self._timer_label.set_visible(False)
        self._timer_label.set_can_target(False)
        controls.append(self._timer_label)

        self._record_button = Gtk.Button(label="Record")
        self._record_button.add_css_class("suggested-action")
        self._record_button.connect("clicked", lambda *_: self.toggle_recording())
        controls.append(self._record_button)

        bottom.append(controls)
        return bottom

    # --- public API ----------------------------------------------------------

    def _init_format_from_settings(self) -> None:
        formats = list(OutputFormat)
        current = self._settings.get("recording-output-format")
        index = next((i for i, f in enumerate(formats) if f.value == current), 0)
        self._format_dropdown.set_selected(index)
        self._format_dropdown.connect(
            "notify::selected",
            lambda d, _p: self._settings.set(
                "recording-output-format", self.selected_format.value
            ),
        )

    @property
    def selected_format(self) -> OutputFormat:
        return list(OutputFormat)[self._format_dropdown.get_selected()]

    # --- recording-size inputs ----------------------------------------------

    def _scale_factor(self) -> int:
        native = self.get_native()
        surface = native.get_surface() if native else None
        return surface.get_scale_factor() if surface else 1

    def _make_size_entry(self, tooltip: str) -> Gtk.Entry:
        entry = Gtk.Entry(width_chars=5, max_width_chars=6, xalign=0.5)
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        entry.set_tooltip_text(tooltip)
        entry.connect("activate", lambda _e: self._on_size_entered())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: self._on_size_entered())
        entry.add_controller(focus)
        return entry

    def _entry_int(self, entry: Gtk.Entry, fallback: int) -> int:
        try:
            return max(16, min(16384, int(entry.get_text().strip())))
        except (ValueError, TypeError):
            return int(fallback)

    def _on_capture_resize(self, _area, width: int, height: int) -> None:
        """Capture area was resized: reflect its pixel size in the inputs."""
        scale = self._scale_factor()
        self._set_size_inputs(width * scale, height * scale)

    def _on_mapped(self, *_args) -> None:
        """Once shown: keep the recorder above the rest of the desktop."""
        from ..capture import detect_session
        from ..capture.factory import SessionType

        if detect_session() != SessionType.X11:
            return
        native = self.get_native()
        surface = native.get_surface() if native else None
        if surface is None:
            return
        try:
            from ..platform.x11_window import set_keep_above

            set_keep_above(surface.get_xid())
        except Exception as exc:  # noqa: BLE001
            log.debug("keep-above failed: %s", exc)

    def _set_click_through(self, enabled: bool) -> None:
        """Toggle click-through over the capture hole.

        While recording (*enabled*), clicks over the transparent capture area
        pass through to the windows behind; only the chrome (header, controls,
        border) stays interactive — so you can still drag the window or press
        Stop. When idle the whole window is interactive again, so it can be
        moved and resized normally.
        """
        from ..capture import detect_session
        from ..capture.factory import SessionType

        if detect_session() != SessionType.X11:
            return
        native = self.get_native()
        surface = native.get_surface() if native else None
        if native is None or surface is None:
            return
        try:
            from ..platform.x11_window import (
                clear_input_passthrough,
                set_input_passthrough,
            )

            xid = surface.get_xid()
            if not enabled:
                clear_input_passthrough(xid)
                return
            ok, rect = self._capture_area.compute_bounds(self)
            if not ok:
                return
            # Widget coords (logical) -> surface coords (add the CSD-shadow
            # transform) -> device pixels (×scale), which is what X expects.
            tx, ty = native.get_surface_transform()
            scale = surface.get_scale_factor()
            hole = (
                int(round((rect.get_x() + tx) * scale)),
                int(round((rect.get_y() + ty) * scale)),
                int(round(rect.get_width() * scale)),
                int(round(rect.get_height() * scale)),
            )
            set_input_passthrough(xid, hole)
        except Exception as exc:  # noqa: BLE001 - never block recording on this
            log.debug("click-through toggle failed: %s", exc)

    def _set_size_inputs(self, width: int, height: int) -> None:
        self._syncing_size = True
        self._width_entry.set_text(str(int(width)))
        self._height_entry.set_text(str(int(height)))
        self._syncing_size = False

    def _on_size_entered(self) -> None:
        """User typed a size: resize the window so the capture area matches.

        We resize the whole window by the requested capture size plus the
        current "chrome" (header + bottom bar). The window manager clamps to the
        minimum usable size; the resulting `resize` signal syncs the inputs back
        to whatever size was actually achieved.
        """
        if self._syncing_size:
            return
        scale = self._scale_factor()
        w_dev = self._entry_int(self._width_entry, (self._capture_area.get_width() or 1) * scale)
        h_dev = self._entry_int(self._height_entry, (self._capture_area.get_height() or 1) * scale)
        desired_w = max(1, round(w_dev / scale))
        desired_h = max(1, round(h_dev / scale))
        cap_w = self._capture_area.get_width() or desired_w
        cap_h = self._capture_area.get_height() or desired_h
        chrome_w = max(0, self.get_width() - cap_w)
        chrome_h = max(0, self.get_height() - cap_h)
        self.set_default_size(desired_w + chrome_w, desired_h + chrome_h)
        # Reflect the normalized values now; the resize signal refines them.
        self._set_size_inputs(w_dev, h_dev)

    def toggle_recording(self) -> None:
        if self._controller is not None and self._controller.is_recording:
            self._stop_recording()
        elif self._countdown_source:
            self._cancel_countdown()
        else:
            self._begin_countdown()

    # --- recording flow ------------------------------------------------------

    def _build_config(self) -> RecordingConfig:
        # All recording settings come from the persisted preferences; the
        # header-bar dropdown only overrides the output format for this run.
        config = self._settings.to_recording_config()
        config.output_format = self.selected_format
        return config

    def _begin_countdown(self) -> None:
        config = self._build_config()
        self._pending_config = config
        delay = config.start_delay
        self._set_button("Cancel", "destructive-action")
        if delay <= 0:
            self._start_recording()
            return
        self._remaining = delay
        self._countdown_label.set_visible(True)
        self._countdown_label.set_label(str(self._remaining))
        self._countdown_source = GLib.timeout_add_seconds(1, self._on_countdown_tick)

    def _on_countdown_tick(self) -> bool:
        self._remaining -= 1
        if self._remaining <= 0:
            self._countdown_source = 0
            self._countdown_label.set_visible(False)
            self._start_recording()
            return False
        self._countdown_label.set_label(str(self._remaining))
        return True

    # --- elapsed-time counter ------------------------------------------------

    def _start_timer(self) -> None:
        self._elapsed = 0
        self._timer_label.set_label("00:00")
        self._timer_label.set_visible(True)
        self._timer_source = GLib.timeout_add_seconds(1, self._on_timer_tick)

    def _on_timer_tick(self) -> bool:
        self._elapsed += 1
        minutes, seconds = divmod(self._elapsed, 60)
        self._timer_label.set_label(f"{minutes:02d}:{seconds:02d}")
        return True

    def _stop_timer(self) -> None:
        if self._timer_source:
            GLib.source_remove(self._timer_source)
            self._timer_source = 0
        self._timer_label.set_visible(False)

    def _cancel_countdown(self) -> None:
        if self._countdown_source:
            GLib.source_remove(self._countdown_source)
            self._countdown_source = 0
        self._countdown_label.set_visible(False)
        self._reset_idle_ui()

    def _start_recording(self) -> None:
        try:
            area = self._extract_area()
        except Exception as exc:  # noqa: BLE001 - surface any setup error
            self._show_error("Could not determine recording area", str(exc))
            self._reset_idle_ui()
            return

        self._controller = RecordingController(self._pending_config)
        try:
            backend = self._controller.start(area)
        except Exception as exc:  # noqa: BLE001
            self._controller = None
            self._show_error("Could not start recording", str(exc))
            self._reset_idle_ui()
            return

        self._hint.set_visible(False)
        self._set_click_through(True)  # let clicks reach the app being recorded
        self._set_button("Stop", "destructive-action")
        self._status_label.set_label("")
        self._start_timer()

    def _stop_recording(self) -> None:
        self._stop_timer()
        self._set_click_through(False)  # restore full interactivity immediately
        self._set_button(None, None, sensitive=False)
        self._spinner.start()
        if self._settings.get("interface-open-editor-after-recording"):
            self._status_label.set_label("Processing…")
            thread = threading.Thread(target=self._editor_worker, daemon=True)
        else:
            self._status_label.set_label("Encoding…")
            thread = threading.Thread(target=self._encode_worker, daemon=True)
        thread.start()

    def _encode_worker(self) -> None:
        try:
            output = self._controller.stop_and_encode()
            GLib.idle_add(self._on_encoded, output)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self._on_encode_failed, str(exc))
        finally:
            self._controller = None

    def _editor_worker(self) -> None:
        """Stop capture, decode to frames, and hand off to the editor."""
        from ..frames.decode import decode_to_frames
        from ..project.cache import SessionCache

        try:
            intermediate = self._controller.stop_capture()
            cache = SessionCache()
            frames = decode_to_frames(intermediate, self._pending_config.framerate, cache)
            intermediate.unlink(missing_ok=True)
            GLib.idle_add(self._open_editor, frames, cache)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self._on_encode_failed, str(exc))
        finally:
            self._controller = None

    def _open_editor(self, frames, cache) -> bool:
        from .editor_window import EditorWindow

        self._spinner.stop()
        editor = EditorWindow(application=self.get_application())
        editor.present()
        # The editor adopts the decoded-frame cache and cleans it up on close.
        editor.load(frames, cache=cache)
        # The recorder window is no longer needed once the editor is up; close
        # it. The app keeps running because the editor window is still open.
        app = self.get_application()
        if app is not None and getattr(app, "_window", None) is self:
            app._window = None
        self.close()
        return False

    def _on_encoded(self, output: Path) -> bool:
        self._spinner.stop()
        self._show_save_dialog(output)
        return False

    def _on_encode_failed(self, message: str) -> bool:
        self._spinner.stop()
        self._show_error("Encoding failed", message)
        self._reset_idle_ui()
        return False

    # --- region extraction ---------------------------------------------------

    def _extract_area(self) -> RecordingArea:
        """Compute the capture region in absolute device pixels.

        All maths are kept in device pixels: the X11 window origin is already in
        device pixels, the capture-area offset (logical) is scaled by the HiDPI
        factor, and the *size* comes from the editable inputs — so it can never
        collapse to zero. Mixing device origin with logical bounds was the cause
        of the "recording area has zero size" error.
        """
        from ..capture import detect_session
        from ..capture.factory import SessionType

        if detect_session() != SessionType.X11:
            raise RuntimeError(
                "Region capture on this session needs the Wayland portal backend. "
                "Run on X11 for now."
            )

        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11  # noqa: F401 (registers the type)

        native = self.get_native()
        surface = native.get_surface() if native else None
        if surface is None:
            raise RuntimeError("window has no surface yet")

        scale = surface.get_scale_factor()
        from ..platform.x11_geometry import absolute_origin
        from ..platform.x11_window import get_frame_extents

        xid = surface.get_xid()
        origin_x, origin_y = absolute_origin(xid)  # outer (shadow) corner, device px
        # GTK draws CSD shadows inside the surface; the X origin is the shadow
        # corner, but widget offsets are measured from the visible content.
        # Add the frame extents to get the true content origin.
        frame_left, _fr, frame_top, _fb = get_frame_extents(xid)

        # Capture-area offset within the window (logical px -> device px).
        ok, rect = self._capture_area.compute_bounds(self)
        off_x = int(round(rect.get_x() * scale)) if ok else 0
        off_y = int(round(rect.get_y() * scale)) if ok else 0
        left = origin_x + frame_left + off_x
        top = origin_y + frame_top + off_y

        # Size tracks the actual capture area (WYSIWYG); the inputs stay in sync
        # with it. Falls back to the input values if not yet allocated.
        width = self._capture_area.get_width() * scale or self._entry_int(self._width_entry, 16)
        height = self._capture_area.get_height() * scale or self._entry_int(self._height_entry, 16)

        # Clip to the visible screen, all in device pixels.
        screen_w, screen_h = self._virtual_screen_size()
        screen_w *= scale
        screen_h *= scale
        left = min(max(0, left), max(0, screen_w - 1))
        top = min(max(0, top), max(0, screen_h - 1))
        width = max(0, min(width, screen_w - left))
        height = max(0, min(height, screen_h - top))

        area = RecordingArea(left, top, width, height)
        log.debug("recording area: %s (scale=%d)", area, scale)
        if not area.is_valid():
            raise RecordingError("recording area has zero size")
        return area

    def _virtual_screen_size(self) -> tuple[int, int]:
        display = self.get_display()
        monitors = display.get_monitors()
        width = height = 0
        for i in range(monitors.get_n_items()):
            geo = monitors.get_item(i).get_geometry()
            width = max(width, geo.x + geo.width)
            height = max(height, geo.y + geo.height)
        return (width or 1920, height or 1080)

    # --- saving --------------------------------------------------------------

    def _show_save_dialog(self, output: Path) -> None:
        ext = self.selected_format.file_extension
        default_name = time.strftime(f"{APP_NAME} %Y-%m-%d %H-%M") + f".{ext}"
        dialog = Gtk.FileChooserNative(
            title="Save recording",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label="_Save",
            cancel_label="_Discard",
        )
        dialog.set_current_name(default_name)
        dialog.connect("response", self._on_save_response, output)
        self._save_dialog = dialog
        dialog.show()

    def _on_save_response(
        self, dialog: Gtk.FileChooserNative, response: int, output: Path
    ) -> None:
        try:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dialog.get_file()
                dest = gfile.get_path()
                shutil.move(str(output), dest)
                self._notify_saved(Path(dest))
                self._status_label.set_label(f"Saved to {dest}")
            else:
                Path(output).unlink(missing_ok=True)
                self._status_label.set_label("Discarded")
        finally:
            dialog.destroy()
            self._save_dialog = None
            self._reset_idle_ui()

    def _notify_saved(self, path: Path) -> None:
        if not self._settings.get("interface-show-notification"):
            return
        app = self.get_application()
        if app is None:
            return
        note = Gio.Notification.new("Recording saved")
        note.set_body(str(path))
        app.send_notification("gif-forge-saved", note)

    # --- ui helpers ----------------------------------------------------------

    def _set_button(
        self, label: Optional[str], css: Optional[str], *, sensitive: bool = True
    ) -> None:
        for klass in ("suggested-action", "destructive-action"):
            self._record_button.remove_css_class(klass)
        if label is not None:
            self._record_button.set_label(label)
        if css is not None:
            self._record_button.add_css_class(css)
        self._record_button.set_sensitive(sensitive)

    def _reset_idle_ui(self) -> None:
        self._stop_timer()
        self._set_click_through(False)
        self._hint.set_visible(True)
        self._set_button("Record", "suggested-action", sensitive=True)
        if not self._status_label.get_label().startswith("Saved"):
            self._status_label.set_label("")

    def _show_error(self, title: str, detail: str) -> None:
        log.error("%s: %s", title, detail)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
            secondary_text=detail,
        )
        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.show()


_MENU_XML = """
<interface>
  <menu id="primary-menu">
    <section>
      <item>
        <attribute name="label">Preferences</attribute>
        <attribute name="action">app.preferences</attribute>
      </item>
      <item>
        <attribute name="label">About GIF Forge</attribute>
        <attribute name="action">app.about</attribute>
      </item>
    </section>
  </menu>
</interface>
"""
