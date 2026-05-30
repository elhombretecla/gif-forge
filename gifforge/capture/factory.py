# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend selection.

Wayland-first: prefer the portal/PipeWire backend when on a Wayland session and
it is available, falling back to X11. This is the modern replacement for Peek's
``ScreenRecorderFactory`` (which preferred the GNOME-Shell D-Bus recorder).
"""

from __future__ import annotations

import enum
import logging
import os
from typing import Optional

from ..models import RecordingConfig
from .backend import CaptureBackend
from .x11 import X11Recorder

log = logging.getLogger(__name__)


class SessionType(enum.Enum):
    X11 = "x11"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"


def detect_session() -> SessionType:
    stype = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if stype == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return SessionType.WAYLAND
    if stype == "x11" or os.environ.get("DISPLAY"):
        return SessionType.X11
    return SessionType.UNKNOWN


def create_backend(
    config: RecordingConfig, *, prefer: Optional[str] = None
) -> CaptureBackend:
    """Create the best available capture backend.

    *prefer* may be ``"x11"`` or ``"portal"`` to force a backend (CLI override,
    mirroring Peek's ``--backend``). Raises RuntimeError if none is available.
    """
    session = detect_session()
    log.debug("session=%s prefer=%s", session, prefer)

    # The Wayland portal backend is implemented in capture.portal (T4). Import
    # lazily so the app runs even where its GStreamer deps are missing.
    portal_cls = _try_import_portal()

    candidates = []
    if prefer == "x11":
        candidates = [X11Recorder]
    elif prefer == "portal":
        candidates = [portal_cls] if portal_cls else []
    elif session == SessionType.WAYLAND:
        candidates = [portal_cls, X11Recorder]
    else:
        candidates = [X11Recorder, portal_cls]

    for cls in candidates:
        if cls is not None and cls.is_available():
            log.info("using capture backend: %s", cls.__name__)
            return cls(config)

    raise RuntimeError(
        "No screen-capture backend available. On Wayland install "
        "xdg-desktop-portal + PipeWire; on X11 install ffmpeg."
    )


def _try_import_portal():
    try:
        from .portal import PortalRecorder  # noqa: WPS433 (lazy by design)

        return PortalRecorder
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("portal backend unavailable: %s", exc)
        return None
