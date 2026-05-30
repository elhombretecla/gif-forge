# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wayland screen capture via xdg-desktop-portal ScreenCast + PipeWire.

This is GIF Forge's *primary* capture backend and the modern replacement for
Peek's X11-only approach. The flow follows the documented portal protocol:

    CreateSession -> SelectSources -> Start -> OpenPipeWireRemote

The portal/compositor shows its own picker during ``SelectSources``/``Start``,
so on Wayland the *compositor* decides what is shared — the ``area`` argument
is only a hint (unlike X11 where we pass explicit coordinates). The returned
PipeWire node is fed through a GStreamer pipeline that writes a WebM
intermediate, which the existing encode pipeline then turns into GIF/APNG/WebM.

Each portal method is request/response based; we drive them with a private,
nested ``GLib.MainLoop`` so the :class:`CaptureBackend` contract stays
synchronous and the existing recorder UI works unchanged.

NOTE: verified structurally on X11 (imports, availability gating, D-Bus
signatures); end-to-end behaviour must be confirmed on a real Wayland session
(GNOME/KDE/wlroots).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import gi

from gi.repository import Gio, GLib

from ..models import RecordingArea, RecordingConfig
from ..utils import create_temp_file
from ..encode.errors import CancelledError, RecordingError
from .backend import CaptureBackend, CaptureState

log = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

# SelectSources "types" bitmask.
SOURCE_MONITOR = 1
SOURCE_WINDOW = 2
# cursor_mode values.
CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2

_token_counter = 0


def _next_token(prefix: str) -> str:
    global _token_counter
    _token_counter += 1
    return f"gifforge_{prefix}_{os.getpid()}_{_token_counter}"


def request_object_path(sender: str, handle_token: str) -> str:
    """Derive the portal Request object path the portal will emit Response on.

    The *handle_token* placed in a method's options MUST match the token here,
    or the Response signal is missed and the call hangs. Kept pure for testing.
    """
    return f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"


def _gst():
    """Import and initialise GStreamer lazily (heavy, env-dependent)."""
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    if not Gst.is_initialized():
        Gst.init(None)
    return Gst


class PortalRecorder(CaptureBackend):
    def __init__(self, config: RecordingConfig) -> None:
        super().__init__(config)
        self._conn: Optional[Gio.DBusConnection] = None
        self._sender: str = ""
        self._session_handle: Optional[str] = None
        self._pipeline = None
        self._fd: int = -1

    # --- availability --------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        # Must be a Wayland session.
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        if session != "wayland" and not os.environ.get("WAYLAND_DISPLAY"):
            return False
        # GStreamer + pipewiresrc must exist.
        try:
            Gst = _gst()
            if Gst.ElementFactory.find("pipewiresrc") is None:
                log.debug("pipewiresrc element missing")
                return False
            if Gst.ElementFactory.find("vp9enc") is None:
                log.debug("vp9enc element missing")
                return False
        except Exception as exc:  # pragma: no cover - env dependent
            log.debug("GStreamer unavailable: %s", exc)
            return False
        # The ScreenCast portal must be reachable on the session bus.
        try:
            conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            conn.call_sync(
                PORTAL_BUS, PORTAL_PATH, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (SCREENCAST_IFACE, "version")),
                GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 2000, None,
            )
        except Exception as exc:  # pragma: no cover - env dependent
            log.debug("ScreenCast portal unreachable: %s", exc)
            return False
        return True

    # --- lifecycle -----------------------------------------------------------

    def start(self, area: RecordingArea) -> None:
        """Negotiate the portal session and start the GStreamer pipeline.

        Blocks (via a nested main loop) while the portal picker is shown and
        until the pipeline reaches PLAYING. ``area`` is advisory on Wayland.
        """
        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._sender = self._conn.get_unique_name()[1:].replace(".", "_")

        self._session_handle = self._create_session()
        self._select_sources()
        streams = self._start_cast()
        if not streams:
            raise RecordingError("portal returned no streams")
        node_id = streams[0][0]
        self._fd = self._open_pipewire_remote()

        self.temp_file = create_temp_file("webm")
        self._build_pipeline(self._fd, node_id, self.temp_file)
        self.state = CaptureState.RECORDING
        log.info("portal recording started (node=%s -> %s)", node_id, self.temp_file)

    def stop(self) -> Path:
        if self._pipeline is None or self.temp_file is None:
            raise RecordingError("not recording")
        Gst = _gst()
        self.state = CaptureState.STOPPING

        # Flush the muxer so the WebM is finalised.
        self._pipeline.send_event(Gst.Event.new_eos())
        bus = self._pipeline.get_bus()
        bus.timed_pop_filtered(
            10 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR
        )
        self._teardown_pipeline()
        self._close_session()
        self.state = CaptureState.DONE
        return self.temp_file

    def cancel(self) -> None:
        self._teardown_pipeline()
        self._close_session()
        if self.temp_file is not None:
            self.temp_file.unlink(missing_ok=True)
            self.temp_file = None
        self.state = CaptureState.IDLE

    # --- portal calls --------------------------------------------------------

    def _portal_request(
        self, method: str, params: GLib.Variant, handle_token: str,
        *, timeout_seconds: int = 300,
    ) -> dict:
        """Call a ScreenCast method and wait for its Request.Response signal.

        *handle_token* MUST equal the ``handle_token`` placed in *params*'
        options dict: the portal derives the Request object path from it, so the
        path we subscribe to has to match exactly or the Response is missed.
        """
        request_path = request_object_path(self._sender, handle_token)
        loop = GLib.MainLoop()
        out: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, parameters):
            response, results = parameters.unpack()
            out["response"] = response
            out["results"] = results
            loop.quit()

        def on_timeout():
            out["timeout"] = True
            loop.quit()
            return False

        sub_id = self._conn.signal_subscribe(
            PORTAL_BUS, REQUEST_IFACE, "Response", request_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )
        timeout_id = GLib.timeout_add_seconds(timeout_seconds, on_timeout)
        try:
            self._conn.call_sync(
                PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE, method, params,
                GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None,
            )
            loop.run()
        finally:
            self._conn.signal_unsubscribe(sub_id)
            GLib.source_remove(timeout_id)

        if out.get("timeout"):
            raise RecordingError(f"portal {method} timed out")
        response = out.get("response", 2)
        if response == 1:
            raise CancelledError(f"{method} cancelled by user")
        if response != 0:
            raise RecordingError(f"portal {method} failed (response={response})")
        return out.get("results", {})

    def _create_session(self) -> str:
        handle_token = _next_token("createsession")
        options = {
            "handle_token": GLib.Variant("s", handle_token),
            "session_handle_token": GLib.Variant("s", _next_token("session")),
        }
        params = GLib.Variant("(a{sv})", (options,))
        results = self._portal_request("CreateSession", params, handle_token)
        handle = results.get("session_handle")
        if not handle:
            raise RecordingError("portal did not return a session handle")
        return handle

    def _select_sources(self) -> None:
        cursor = CURSOR_EMBEDDED if self.config.capture_mouse else CURSOR_HIDDEN
        handle_token = _next_token("selectsources")
        options = {
            "handle_token": GLib.Variant("s", handle_token),
            "types": GLib.Variant("u", SOURCE_MONITOR | SOURCE_WINDOW),
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", cursor),
        }
        params = GLib.Variant("(oa{sv})", (self._session_handle, options))
        self._portal_request("SelectSources", params, handle_token)

    def _start_cast(self):
        handle_token = _next_token("start")
        options = {"handle_token": GLib.Variant("s", handle_token)}
        params = GLib.Variant("(osa{sv})", (self._session_handle, "", options))
        results = self._portal_request("Start", params, handle_token)
        return results.get("streams", [])

    def _open_pipewire_remote(self) -> int:
        params = GLib.Variant("(oa{sv})", (self._session_handle, {}))
        reply, fd_list = self._conn.call_with_unix_fd_list_sync(
            PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE, "OpenPipeWireRemote",
            params, GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None,
        )
        (handle_index,) = reply.unpack()
        return fd_list.get(handle_index)

    def _close_session(self) -> None:
        if self._conn is None or self._session_handle is None:
            return
        try:
            self._conn.call_sync(
                PORTAL_BUS, self._session_handle, SESSION_IFACE, "Close",
                None, None, Gio.DBusCallFlags.NONE, 2000, None,
            )
        except Exception as exc:  # pragma: no cover - env dependent
            log.debug("error closing portal session: %s", exc)
        self._session_handle = None

    # --- gstreamer pipeline --------------------------------------------------

    def _build_pipeline(self, fd: int, node_id: int, output: Path) -> None:
        Gst = _gst()
        fps = self.config.framerate
        # Lossless VP9 intermediate (matches the X11 backend's GIF path); the
        # encode pipeline re-encodes from here to the requested output format.
        desc = (
            f"pipewiresrc fd={fd} path={node_id} do-timestamp=true "
            f"keepalive-time=1000 ! videorate ! "
            f"video/x-raw,framerate={fps}/1 ! videoconvert ! "
            f"vp9enc lossless=1 ! webmmux ! filesink location={output}"
        )
        log.debug("gst pipeline: %s", desc)
        self._pipeline = Gst.parse_launch(desc)
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._teardown_pipeline()
            raise RecordingError("failed to start GStreamer capture pipeline")

    def _teardown_pipeline(self) -> None:
        if self._pipeline is not None:
            Gst = _gst()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
