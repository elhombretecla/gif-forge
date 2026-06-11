# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the JSON-backed settings store and config mapping."""

import importlib

import pytest

from gifforge.models import OutputFormat


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Reload module so _config_path() picks up the patched env.
    from gifforge.settings import config as config_mod

    importlib.reload(config_mod)
    return config_mod.Settings(force_json=True)


def test_defaults(settings):
    assert settings.backend == "json"
    assert settings.get("recording-framerate") == 10
    assert settings.get("recording-output-format") == "gif"
    assert settings.get("recording-capture-mouse") is True


def test_set_and_persist(settings, tmp_path, monkeypatch):
    settings.set("recording-framerate", 24)
    settings.set("recording-output-format", "webm")
    settings.set("recording-capture-mouse", False)

    # A fresh instance reading the same file should see the saved values.
    from gifforge.settings.config import Settings

    reloaded = Settings(force_json=True)
    assert reloaded.get("recording-framerate") == 24
    assert reloaded.get("recording-output-format") == "webm"
    assert reloaded.get("recording-capture-mouse") is False


def test_to_recording_config(settings):
    settings.set("recording-framerate", 30)
    settings.set("recording-output-format", "apng")
    settings.set("recording-gifski-quality", 80)

    config = settings.to_recording_config()
    assert config.framerate == 30
    assert config.output_format is OutputFormat.APNG
    assert config.gifski_quality == 80
    config.validate()  # should not raise


def test_to_recording_config_clamps_hand_edited_values(settings):
    # The JSON file can be edited by hand: bad values must degrade, not raise.
    settings.set("recording-framerate", 999)
    settings.set("recording-downsample", 0)
    settings.set("recording-output-format", "bogus")

    config = settings.to_recording_config()
    assert config.framerate == 60
    assert config.downsample == 1
    assert config.output_format is OutputFormat.GIF
    config.validate()  # should not raise
