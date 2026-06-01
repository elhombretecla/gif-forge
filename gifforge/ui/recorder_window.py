# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The recorder: a small capture frame plus a separate floating control bar.

The capture frame is a near-chromeless window whose interior *is* the recorded
region (the desktop shows through on a compositing desktop). All the controls
(format, size, Record, timer, status, menu) live in a **separate** window so
they no longer dictate the frame's minimum width — the frame can be shrunk to
tiny sizes (e.g. 300×200) for small GIFs. Pressing Record runs an optional
countdown, captures the region via the best available backend, encodes off the
main thread, then offers a save dialog and a desktop notification.

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
from ..i18n import _  # noqa: E402
from ..encode.errors import RecordingError  # noqa: E402
from ..models import OutputFormat, RecordingArea, RecordingConfig  # noqa: E402
from ..recorder import RecordingController  # noqa: E402
from ..settings import get_settings  # noqa: E402

log = logging.getLogger(__name__)

# The capture frame can be made this small (logical px). The old single-window
# layout was bounded at ~612px wide by the control widgets; with the controls
# split into their own window the only floor we keep is a sane usable minimum.
_MIN_CAPTURE = 32

_CSS = b"""
.gifforge-recorder.background { background-color: transparent; }
.gifforge-recorder headerbar {
  background-color: @headerbar_bg_color;
  min-height: 0;
  padding: 0 4px;
}
.recorder-control-bar { background-color: @window_bg_color; padding: 8px 12px; }
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
    """The transparent capture frame and the full record→encode→save workflow.

    Owns the capture geometry, X11 click-through/keep-above and the recording
    flow. The user-facing controls live in a sibling :class:`_ControlBar`, which
    this window creates, shows and drives.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(400, 300)
        self.add_css_class("gifforge-recorder")

        self._settings = get_settings()
        self._controller: Optional[RecordingController] = None
        self._countdown_source: int = 0
        self._timer_source: int = 0
        self._elapsed: int = 0
        self._save_dialog: Optional[Gtk.FileChooserNative] = None
        self._syncing_size = False  # guard against control<->capture-area feedback
        self._closing = False

        self._install_css()
        self._build_ui()

        # The control bar holds every recording control, decoupled from the
        # frame's size. Created here, shown when the frame is first mapped.
        self._controls = _ControlBar(self, application=self.get_application())

        self.connect("map", self._on_mapped)
        self.connect("close-request", self._on_close_request)

    # --- construction --------------------------------------------------------

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # A slim header bar gives the frame native move/resize and a close
        # button, but packs no controls of its own so it never widens the frame.
        # An empty title widget keeps the centre clear without relying on the
        # newer Adw.HeaderBar:show-title property.
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label())
        root.append(header)

        # Transparent capture region (a DrawingArea so we get a `resize` signal
        # to keep the size inputs in sync), with hint + countdown overlays.
        overlay = Gtk.Overlay(vexpand=True)
        self._capture_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self._capture_area.set_size_request(_MIN_CAPTURE, _MIN_CAPTURE)
        self._capture_area.add_css_class("capture-area")
        self._capture_area.connect("resize", self._on_capture_resize)
        overlay.set_child(self._capture_area)

        self._hint = Gtk.Label(label=_("Drag over what you want to capture"))
        self._hint.add_css_class("dim-label")
        self._hint.set_halign(Gtk.Align.CENTER)
        self._hint.set_valign(Gtk.Align.CENTER)
        self._hint.set_wrap(True)
        self._hint.set_justify(Gtk.Justification.CENTER)
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

        self.set_content(root)

    # --- public API ----------------------------------------------------------

    @property
    def selected_format(self) -> OutputFormat:
        return self._controls.selected_format

    def toggle_recording(self) -> None:
        if self._controller is not None and self._controller.is_recording:
            self._stop_recording()
        elif self._countdown_source:
            self._cancel_countdown()
        else:
            self._begin_countdown()

    def request_capture_size(self, w_dev: int, h_dev: int) -> None:
        """Resize the frame so the capture area becomes *w_dev*×*h_dev* (device px).

        Driven by the control bar's size inputs. We add the current "chrome"
        (header height; width chrome is ~0) so the *capture area* lands on the
        requested size. The window manager clamps to its minimum; the resulting
        `resize` signal syncs the inputs back to whatever was achieved.
        """
        if self._syncing_size:
            return
        scale = self._scale_factor()
        desired_w = max(1, round(w_dev / scale))
        desired_h = max(1, round(h_dev / scale))
        cap_w = self._capture_area.get_width() or desired_w
        cap_h = self._capture_area.get_height() or desired_h
        chrome_w = max(0, self.get_width() - cap_w)
        chrome_h = max(0, self.get_height() - cap_h)
        self.set_default_size(desired_w + chrome_w, desired_h + chrome_h)
        # Reflect the normalized values now; the resize signal refines them.
        self._controls.set_size_inputs(w_dev, h_dev)

    # --- recording-size sync -------------------------------------------------

    def _scale_factor(self) -> int:
        native = self.get_native()
        surface = native.get_surface() if native else None
        return surface.get_scale_factor() if surface else 1

    def _on_capture_resize(self, _area, width: int, height: int) -> None:
        """Capture area was resized: reflect its pixel size in the inputs."""
        scale = self._scale_factor()
        self._controls.set_size_inputs(width * scale, height * scale)

    # --- window lifecycle ----------------------------------------------------

    def _on_mapped(self, *_args) -> None:
        """Once shown: float the frame and bring up the control bar."""
        self._controls.present()
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

    def _on_close_request(self, *_args) -> bool:
        """Closing the frame tears down the control bar too."""
        if not self._closing:
            self._closing = True
            self._controls.close()
        return False

    def _set_click_through(self, enabled: bool) -> None:
        """Toggle click-through over the capture hole.

        While recording (*enabled*), clicks over the transparent capture area
        pass through to the windows behind; only the header strip stays
        interactive, so the frame can still be dragged. The control bar is a
        separate window and remains fully usable (Stop lives there). When idle
        the whole frame is interactive again.
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

    # --- recording flow ------------------------------------------------------

    def _build_config(self) -> RecordingConfig:
        # All recording settings come from the persisted preferences; the
        # control-bar dropdown only overrides the output format for this run.
        config = self._settings.to_recording_config()
        config.output_format = self.selected_format
        return config

    def _begin_countdown(self) -> None:
        config = self._build_config()
        self._pending_config = config
        delay = config.start_delay
        self._controls.set_record_button(_("Cancel"), "destructive-action")
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
        self._controls.update_timer("00:00", visible=True)
        self._timer_source = GLib.timeout_add_seconds(1, self._on_timer_tick)

    def _on_timer_tick(self) -> bool:
        self._elapsed += 1
        minutes, seconds = divmod(self._elapsed, 60)
        self._controls.update_timer(f"{minutes:02d}:{seconds:02d}", visible=True)
        return True

    def _stop_timer(self) -> None:
        if self._timer_source:
            GLib.source_remove(self._timer_source)
            self._timer_source = 0
        self._controls.update_timer("", visible=False)

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
            self._show_error(_("Could not determine recording area"), str(exc))
            self._reset_idle_ui()
            return

        self._controller = RecordingController(self._pending_config)
        try:
            backend = self._controller.start(area)  # noqa: F841
        except Exception as exc:  # noqa: BLE001
            self._controller = None
            self._show_error(_("Could not start recording"), str(exc))
            self._reset_idle_ui()
            return

        self._hint.set_visible(False)
        self._set_click_through(True)  # let clicks reach the app being recorded
        self._controls.set_record_button(_("Stop"), "destructive-action")
        self._controls.set_status("")
        self._start_timer()

    def _stop_recording(self) -> None:
        self._stop_timer()
        self._set_click_through(False)  # restore full interactivity immediately
        self._controls.set_record_button(None, None, sensitive=False)
        self._controls.start_spinner()
        if self._settings.get("interface-open-editor-after-recording"):
            self._controls.set_status(_("Processing…"))
            thread = threading.Thread(target=self._editor_worker, daemon=True)
        else:
            self._controls.set_status(_("Encoding…"))
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

        self._controls.stop_spinner()
        editor = EditorWindow(application=self.get_application())
        editor.present()
        # The editor adopts the decoded-frame cache and cleans it up on close.
        editor.load(frames, cache=cache)
        # The recorder is no longer needed once the editor is up; close it (and
        # its control bar). The app keeps running because the editor is open.
        app = self.get_application()
        if app is not None and getattr(app, "_window", None) is self:
            app._window = None
        self.close()
        return False

    def _on_encoded(self, output: Path) -> bool:
        self._controls.stop_spinner()
        self._show_save_dialog(output)
        return False

    def _on_encode_failed(self, message: str) -> bool:
        self._controls.stop_spinner()
        self._show_error(_("Encoding failed"), message)
        self._reset_idle_ui()
        return False

    # --- region extraction ---------------------------------------------------

    def _extract_area(self) -> RecordingArea:
        """Compute the capture region in absolute device pixels.

        All maths are kept in device pixels: the X11 window origin is already in
        device pixels, the capture-area offset (logical) is scaled by the HiDPI
        factor, and the *size* comes from the capture area allocation — so it can
        never collapse to zero. Mixing device origin with logical bounds was the
        cause of the "recording area has zero size" error.
        """
        from ..capture import detect_session
        from ..capture.factory import SessionType

        if detect_session() != SessionType.X11:
            raise RuntimeError(
                _(
                    "Region capture on this session needs the Wayland portal "
                    "backend. Run on X11 for now."
                )
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
        width = self._capture_area.get_width() * scale or self._controls.input_width()
        height = self._capture_area.get_height() * scale or self._controls.input_height()

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
            title=_("Save recording"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label=_("_Save"),
            cancel_label=_("_Discard"),
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
                self._controls.set_status(_("Saved to {path}").format(path=dest), sticky=True)
            else:
                Path(output).unlink(missing_ok=True)
                self._controls.set_status(_("Discarded"))
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
        note = Gio.Notification.new(_("Recording saved"))
        note.set_body(str(path))
        app.send_notification("gif-forge-saved", note)

    # --- ui helpers ----------------------------------------------------------

    def _reset_idle_ui(self) -> None:
        self._stop_timer()
        self._set_click_through(False)
        self._hint.set_visible(True)
        self._controls.set_record_button(_("Record"), "suggested-action", sensitive=True)
        self._controls.reset_status_if_idle()

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


class _ControlBar(Adw.ApplicationWindow):
    """Floating toolbar holding every recording control.

    Kept as a window of its own so the recording controls no longer constrain
    the capture frame's width — the frame can be made arbitrarily small while
    these controls float beside it.
    """

    def __init__(self, recorder: "RecorderWindow", **kwargs) -> None:
        super().__init__(**kwargs)
        self._recorder = recorder
        self._settings = recorder._settings
        self._syncing_size = False
        self._closing = False
        self._status_sticky = False

        self.set_title(f"{APP_NAME} — " + _("Controls"))
        self.set_resizable(False)
        self.set_default_size(420, -1)

        self._build_ui()
        self._init_format_from_settings()
        self.connect("map", self._on_mapped)
        self.connect("close-request", self._on_close_request)

    # --- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        self._format_dropdown = Gtk.DropDown.new_from_strings(
            [fmt.value.upper() for fmt in OutputFormat]
        )
        self._format_dropdown.set_tooltip_text(_("Output format"))
        header.pack_start(self._format_dropdown)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("About GIF Forge"), "app.about")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        root.append(header)

        root.append(self._build_control_row())
        self.set_content(root)

    def _build_control_row(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("recorder-control-bar")

        # Left: editable recording-size inputs (in output pixels). Plain entries
        # (no spin steppers) — applied on Enter or focus-out, clamped on apply.
        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        size_box.set_valign(Gtk.Align.CENTER)
        self._width_entry = self._make_size_entry(_("Recording width in pixels"))
        self._height_entry = self._make_size_entry(_("Recording height in pixels"))
        times = Gtk.Label(label="×")
        times.add_css_class("dim-label")
        unit = Gtk.Label(label="px")
        unit.add_css_class("dim-label")
        size_box.append(self._width_entry)
        size_box.append(times)
        size_box.append(self._height_entry)
        size_box.append(unit)
        bar.append(size_box)

        bar.append(Gtk.Box(hexpand=True))

        # Right: status + spinner + the Record button.
        self._status_label = Gtk.Label(label="", xalign=1)
        self._status_label.add_css_class("dim-label")
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_label.set_max_width_chars(16)
        bar.append(self._status_label)

        self._spinner = Gtk.Spinner()
        bar.append(self._spinner)

        # Timer + Record button live in a tight box so the elapsed-time counter
        # sits flush against the button while recording.
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_valign(Gtk.Align.CENTER)

        self._timer_label = Gtk.Label(label="00:00")
        self._timer_label.add_css_class("recording-timer")
        self._timer_label.set_visible(False)
        self._timer_label.set_can_target(False)
        controls.append(self._timer_label)

        self._record_button = Gtk.Button(label=_("Record"))
        self._record_button.add_css_class("suggested-action")
        self._record_button.connect("clicked", lambda *_: self._recorder.toggle_recording())
        controls.append(self._record_button)

        bar.append(controls)
        return bar

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

    # --- size inputs ---------------------------------------------------------

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
            return max(_MIN_CAPTURE, min(16384, int(entry.get_text().strip())))
        except (ValueError, TypeError):
            return int(fallback)

    def input_width(self) -> int:
        return self._entry_int(self._width_entry, _MIN_CAPTURE)

    def input_height(self) -> int:
        return self._entry_int(self._height_entry, _MIN_CAPTURE)

    def set_size_inputs(self, width: int, height: int) -> None:
        self._syncing_size = True
        self._width_entry.set_text(str(int(width)))
        self._height_entry.set_text(str(int(height)))
        self._syncing_size = False

    def _on_size_entered(self) -> None:
        if self._syncing_size:
            return
        self._recorder.request_capture_size(self.input_width(), self.input_height())

    # --- control state (driven by the recorder) ------------------------------

    @property
    def selected_format(self) -> OutputFormat:
        return list(OutputFormat)[self._format_dropdown.get_selected()]

    def set_record_button(
        self, label: Optional[str], css: Optional[str], *, sensitive: bool = True
    ) -> None:
        for klass in ("suggested-action", "destructive-action"):
            self._record_button.remove_css_class(klass)
        if label is not None:
            self._record_button.set_label(label)
        if css is not None:
            self._record_button.add_css_class(css)
        self._record_button.set_sensitive(sensitive)

    def set_status(self, text: str, *, sticky: bool = False) -> None:
        # `sticky` marks a message (e.g. "Saved to …") that should survive the
        # idle reset, instead of fragile prefix-matching on a translated string.
        self._status_sticky = sticky
        self._status_label.set_label(text)

    def reset_status_if_idle(self) -> None:
        if not self._status_sticky:
            self._status_label.set_label("")

    def update_timer(self, text: str, *, visible: bool) -> None:
        self._timer_label.set_label(text)
        self._timer_label.set_visible(visible)

    def start_spinner(self) -> None:
        self._spinner.start()

    def stop_spinner(self) -> None:
        self._spinner.stop()

    # --- window lifecycle ----------------------------------------------------

    def _on_mapped(self, *_args) -> None:
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
            log.debug("control-bar keep-above failed: %s", exc)

    def _on_close_request(self, *_args) -> bool:
        """Closing the control bar closes the whole recorder."""
        if not self._closing:
            self._closing = True
            self._recorder.close()
        return False
