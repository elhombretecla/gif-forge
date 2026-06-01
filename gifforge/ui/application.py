# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adw.Application lifecycle, actions and shortcuts.

Replaces Peek's ``application.vala`` / ``main.vala``. Notably it does NOT force
``GDK_BACKEND=x11`` — native Wayland is a first-class target.
"""

from __future__ import annotations

import logging
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, APP_NAME, __version__  # noqa: E402
from ..i18n import _  # noqa: E402
from ..project import SessionCache, list_recoverable, load_project  # noqa: E402
from ..settings import get_settings  # noqa: E402
from .preferences_window import PreferencesWindow  # noqa: E402
from .recorder_window import RecorderWindow  # noqa: E402

log = logging.getLogger(__name__)


def apply_color_scheme(prefer_dark: bool) -> None:
    """Apply the preferred light/dark color scheme via libadwaita."""
    manager = Adw.StyleManager.get_default()
    manager.set_color_scheme(
        Adw.ColorScheme.PREFER_DARK if prefer_dark else Adw.ColorScheme.DEFAULT
    )


class GifForgeApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self._window: RecorderWindow | None = None
        self._recovery_checked = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._setup_actions()
        settings = get_settings()
        apply_color_scheme(settings.get("interface-prefer-dark-theme"))

    def do_activate(self) -> None:
        if self._window is None:
            self._window = RecorderWindow(application=self)
        self._window.present()
        if not self._recovery_checked:
            self._recovery_checked = True
            from gi.repository import GLib

            GLib.idle_add(self._check_recovery)

    # --- editor / recovery ---------------------------------------------------

    def open_editor_with_project(self, path) -> None:
        from pathlib import Path

        from .editor_window import EditorWindow

        cache = SessionCache()
        try:
            document = load_project(Path(path), cache)
        except Exception as exc:  # noqa: BLE001
            cache.cleanup()
            log.error("could not open project %s: %s", path, exc)
            return
        editor = EditorWindow(application=self)
        editor.present()
        editor.load_document(document, cache)

    def _check_recovery(self) -> bool:
        recoverable = list_recoverable()
        if not recoverable:
            return False
        dialog = Gtk.MessageDialog(
            transient_for=self.props.active_window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text=_("Recover unsaved recording?"),
            secondary_text=_(
                "{count} recording(s) from a previous session were not saved. "
                "Recover them in the editor?"
            ).format(count=len(recoverable)),
        )
        dialog.add_button(_("_Discard"), Gtk.ResponseType.REJECT)
        dialog.add_button(_("_Recover"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.connect("response", self._on_recovery_response, recoverable)
        dialog.show()
        return False

    def _on_recovery_response(self, dialog, response, recoverable) -> None:
        dialog.destroy()
        for path in recoverable:
            if response == Gtk.ResponseType.ACCEPT:
                self.open_editor_with_project(path)
            # Either way, drop the stale autosave (recovered copies re-autosave
            # under a fresh session id; discarded ones are removed).
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _setup_actions(self) -> None:
        for name, callback, accels in (
            ("about", self._on_about, None),
            ("preferences", self._on_preferences, ["<Primary>comma"]),
            ("quit", self._on_quit, ["<Primary>q"]),
            ("toggle-recording", self._on_toggle_recording, ["<Primary><Alt>r"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    # --- action handlers ----------------------------------------------------

    def _on_quit(self, *_args) -> None:
        self.quit()

    def _on_about(self, *_args) -> None:
        # Adw.AboutWindow needs libadwaita 1.2; Gtk.AboutDialog works everywhere.
        about = Gtk.AboutDialog(
            transient_for=self.props.active_window,
            modal=True,
            program_name=APP_NAME,
            logo_icon_name=APP_ID,
            version=__version__,
            license_type=Gtk.License.GPL_3_0,
            comments=_("Record and edit screen captures as GIF, video or APNG."),
        )

        # Load the app logo PNG directly so it shows even when running from
        # source, where the icon isn't installed in the system icon theme and
        # `logo_icon_name` would otherwise fall back to a generic placeholder.
        logo = self._load_logo_texture()
        if logo is not None:
            about.set_logo(logo)

        about.present()

    @staticmethod
    def _load_logo_texture():
        """Return a GdkTexture of the app logo, or None if it can't be found."""
        # Repo root relative to this module: gifforge/ui/application.py -> ../../
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        candidates = []
        for size in ("512x512", "256x256", "128x128", "64x64", "48x48"):
            candidates.append(
                os.path.join(repo_root, "data", "icons", size, f"{APP_ID}.png")
            )
            # Installed / Flatpak hicolor location.
            candidates.append(f"/app/share/icons/hicolor/{size}/apps/{APP_ID}.png")
        for path in candidates:
            if os.path.exists(path):
                try:
                    return Gdk.Texture.new_from_filename(path)
                except GLib.Error:
                    log.warning("Failed to load logo from %s", path)
        return None

    def _on_preferences(self, *_args) -> None:
        settings = get_settings()
        window = PreferencesWindow(settings, transient_for=self.props.active_window)

        # Re-apply the color scheme live when the preference changes.
        def on_close(*_a):
            apply_color_scheme(settings.get("interface-prefer-dark-theme"))
            return False

        window.connect("close-request", on_close)
        window.present()

    def _on_toggle_recording(self, *_args) -> None:
        if self._window is not None:
            self._window.toggle_recording()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    # Set up translations before any window (and thus any string) is built.
    from .. import i18n

    i18n.init(get_settings().get("interface-language"))
    Adw.init()
    app = GifForgeApplication()
    return app.run(None)
