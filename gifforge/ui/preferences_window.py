# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preferences window (T6).

Built with libadwaita 1.1-compatible widgets (ActionRow + Switch/SpinButton
suffixes, ComboRow) so it runs on older runtimes too. Every control writes
straight back to :class:`~gifforge.settings.Settings`, which persists via
GSettings or JSON.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..models import OutputFormat  # noqa: E402
from ..settings import Settings  # noqa: E402


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, settings: Settings, **kwargs) -> None:
        super().__init__(**kwargs)
        self._settings = settings
        self.set_title("Preferences")
        self.set_search_enabled(False)
        self._build()

    def _build(self) -> None:
        page = Adw.PreferencesPage(title="Recording", icon_name="camera-video-symbolic")

        recording = Adw.PreferencesGroup(title="Recording")
        recording.add(self._format_row())
        recording.add(
            self._spin_row("Frame rate", "recording-framerate", 1, 60, 1, "fps")
        )
        recording.add(
            self._spin_row("Downsample", "recording-downsample", 1, 4, 1, "×")
        )
        recording.add(self._switch_row("Capture mouse cursor", "recording-capture-mouse"))
        recording.add(self._switch_row("Capture sound (WebM only)", "recording-capture-sound"))
        recording.add(
            self._spin_row("Start delay", "recording-start-delay", 0, 60, 1, "s")
        )
        page.add(recording)

        quality = Adw.PreferencesGroup(
            title="GIF quality",
            description="gifski produces higher-quality GIFs when installed.",
        )
        quality.add(self._switch_row("Use gifski encoder", "recording-gifski-enabled"))
        quality.add(
            self._spin_row("gifski quality", "recording-gifski-quality", 20, 100, 5, "")
        )
        page.add(quality)

        interface = Adw.PreferencesGroup(title="Interface")
        interface.add(
            self._switch_row("Open editor after recording", "interface-open-editor-after-recording")
        )
        interface.add(
            self._switch_row("Show notification after saving", "interface-show-notification")
        )
        interface.add(self._switch_row("Prefer dark theme", "interface-prefer-dark-theme"))
        page.add(interface)

        self.add(page)

    # --- row builders --------------------------------------------------------

    def _format_row(self) -> Adw.ComboRow:
        formats = list(OutputFormat)
        model = Gtk.StringList.new([f.value.upper() for f in formats])
        row = Adw.ComboRow(title="Output format", model=model)
        current = self._settings.get("recording-output-format")
        row.set_selected(
            next((i for i, f in enumerate(formats) if f.value == current), 0)
        )

        def on_selected(combo, _param):
            self._settings.set(
                "recording-output-format", formats[combo.get_selected()].value
            )

        row.connect("notify::selected", on_selected)
        return row

    def _switch_row(self, title: str, key: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=self._settings.get(key))
        switch.connect("notify::active", lambda s, _p: self._settings.set(key, s.get_active()))
        row.add_suffix(switch)
        row.set_activatable_widget(switch)
        return row

    def _spin_row(
        self, title: str, key: str, lo: int, hi: int, step: int, unit: str
    ) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        spin = Gtk.SpinButton.new_with_range(lo, hi, step)
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_value(self._settings.get(key))
        spin.connect(
            "value-changed", lambda s: self._settings.set(key, int(s.get_value()))
        )
        if unit:
            label = Gtk.Label(label=unit)
            label.add_css_class("dim-label")
            row.add_suffix(label)
        row.add_suffix(spin)
        row.set_activatable_widget(spin)
        return row
