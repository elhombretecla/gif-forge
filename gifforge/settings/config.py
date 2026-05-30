# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Typed settings store with a GSettings or JSON backend.

Backend selection is automatic: if the GSettings schema (``APP_ID``) is
installed it is used (so the app integrates with dconf/Flatpak), otherwise a
JSON file is used. Both expose the same ``get``/``set`` API and key names, so
the rest of the app is backend-agnostic.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from gi.repository import Gio

from .. import APP_ID
from ..models import OutputFormat, RecordingConfig

log = logging.getLogger(__name__)

SCHEMA_ID = APP_ID

# Defaults + implicit types (bool/int/str) — ported from Peek's gschema.
DEFAULTS: Dict[str, Any] = {
    "recording-output-format": "gif",
    "recording-framerate": 10,
    "recording-downsample": 1,
    "recording-capture-mouse": True,
    "recording-capture-sound": False,
    "recording-start-delay": 3,
    "recording-gifski-enabled": False,
    "recording-gifski-quality": 60,
    "interface-show-notification": True,
    "interface-prefer-dark-theme": True,
    "interface-open-editor-after-recording": True,
    "persist-save-folder": "",
}


def _config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path / "settings.json"


class Settings:
    def __init__(self, *, force_json: bool = False) -> None:
        self._gsettings: Optional[Gio.Settings] = (
            None if force_json else self._try_gsettings()
        )
        self._json: Dict[str, Any] = {}
        self._path: Optional[Path] = None
        if self._gsettings is None:
            self._path = _config_path()
            self._json = self._load_json()
        log.info("settings backend: %s", self.backend)

    @staticmethod
    def _try_gsettings() -> Optional[Gio.Settings]:
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None and source.lookup(SCHEMA_ID, True) is not None:
                return Gio.Settings.new(SCHEMA_ID)
        except Exception as exc:  # pragma: no cover - env dependent
            log.debug("GSettings unavailable: %s", exc)
        return None

    @property
    def backend(self) -> str:
        return "gsettings" if self._gsettings is not None else "json"

    # --- raw access ----------------------------------------------------------

    def _load_json(self) -> Dict[str, Any]:
        assert self._path is not None
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}

    def _save_json(self) -> None:
        assert self._path is not None
        self._path.write_text(json.dumps(self._json, indent=2, sort_keys=True))

    def get(self, key: str) -> Any:
        default = DEFAULTS[key]
        if self._gsettings is not None:
            if isinstance(default, bool):
                return self._gsettings.get_boolean(key)
            if isinstance(default, int):
                return self._gsettings.get_int(key)
            return self._gsettings.get_string(key)
        return self._json.get(key, default)

    def set(self, key: str, value: Any) -> None:
        default = DEFAULTS[key]
        if self._gsettings is not None:
            if isinstance(default, bool):
                self._gsettings.set_boolean(key, bool(value))
            elif isinstance(default, int):
                self._gsettings.set_int(key, int(value))
            else:
                self._gsettings.set_string(key, str(value))
        else:
            self._json[key] = value
            self._save_json()

    # --- typed convenience ---------------------------------------------------

    def to_recording_config(self) -> RecordingConfig:
        return RecordingConfig(
            output_format=OutputFormat.from_value(self.get("recording-output-format")),
            framerate=self.get("recording-framerate"),
            downsample=self.get("recording-downsample"),
            capture_mouse=self.get("recording-capture-mouse"),
            capture_sound=self.get("recording-capture-sound"),
            start_delay=self.get("recording-start-delay"),
            gifski_enabled=self.get("recording-gifski-enabled"),
            gifski_quality=self.get("recording-gifski-quality"),
        )


_INSTANCE: Optional[Settings] = None


def get_settings() -> Settings:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Settings()
    return _INSTANCE
