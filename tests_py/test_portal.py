# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Wayland portal backend's pure/gating logic.

The full ScreenCast flow needs a live portal + Wayland session and a user to
pick a source, so it is exercised manually. These tests lock in the parts that
can break silently: availability gating, token uniqueness, and the Request
object-path derivation (whose mismatch caused a hang during development).
"""

import gi  # noqa: F401  (ensures gi is importable before portal import)

from gifforge.capture import portal
from gifforge.capture.portal import PortalRecorder, request_object_path


def test_not_available_on_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert PortalRecorder.is_available() is False


def test_tokens_are_unique():
    tokens = {portal._next_token("start") for _ in range(100)}
    assert len(tokens) == 100


def test_request_path_matches_handle_token():
    sender = "1.240"  # already stripped/escaped form
    token = "gifforge_createsession_123_4"
    path = request_object_path(sender, token)
    assert path.endswith(f"/request/{sender}/{token}")
    # The token in the path is exactly the handle_token we send in options.
    assert path.rsplit("/", 1)[1] == token
