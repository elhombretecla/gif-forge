# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture engine: a backend-agnostic recording abstraction.

The UI talks only to :class:`CaptureBackend` and never knows whether the
underlying implementation is X11 (ffmpeg x11grab) or Wayland (xdg-desktop-portal
ScreenCast + PipeWire). Backends are chosen by :func:`factory.create_backend`.
"""

from .backend import CaptureBackend, CaptureState
from .factory import create_backend, detect_session

__all__ = ["CaptureBackend", "CaptureState", "create_backend", "detect_session"]
