# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""X11 window helpers: CSD frame extents and always-on-top.

GTK4 draws client-side decoration shadows *inside* the X surface, so the X
window's origin (what ``XTranslateCoordinates`` reports) is the outer shadow
corner, not the visible content. GTK publishes the shadow margins in the
``_GTK_FRAME_EXTENTS`` property; adding them back gives the true on-screen
position of the content (and of widgets within it).

Also provides keep-above via ``_NET_WM_STATE_ABOVE`` so the recorder floats over
other windows.

All functions degrade to no-ops/zeros if X11 or the properties are unavailable.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from typing import Tuple

log = logging.getLogger(__name__)

_XA_CARDINAL = 6
_XA_ATOM = 4
_PROP_MODE_REPLACE = 0
_SUBSTRUCTURE_NOTIFY = 1 << 19
_SUBSTRUCTURE_REDIRECT = 1 << 20
_NET_WM_STATE_ADD = 1


def _x11():
    name = ctypes.util.find_library("X11")
    if not name:
        raise RuntimeError("libX11 not found")
    x = ctypes.CDLL(name)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x


def _open():
    x = _x11()
    dpy = x.XOpenDisplay((os.environ.get("DISPLAY", "").encode() or None))
    if not dpy:
        raise RuntimeError("cannot open X display")
    return x, dpy


# --- XShape input passthrough -------------------------------------------------

_SHAPE_BOUNDING = 0
_SHAPE_INPUT = 2
_SHAPE_SET = 0
_SHAPE_SUBTRACT = 3
_SHAPE_UNSORTED = 0


class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short), ("y", ctypes.c_short),
        ("width", ctypes.c_ushort), ("height", ctypes.c_ushort),
    ]


def _xshape():
    name = ctypes.util.find_library("Xext")
    if not name:
        raise RuntimeError("libXext (XShape) not found")
    return ctypes.CDLL(name)


def _window_size(x, dpy, xid: int) -> Tuple[int, int]:
    root = ctypes.c_ulong(); gx = ctypes.c_int(); gy = ctypes.c_int()
    w = ctypes.c_uint(); h = ctypes.c_uint(); bw = ctypes.c_uint(); depth = ctypes.c_uint()
    x.XGetGeometry.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x.XGetGeometry(dpy, ctypes.c_ulong(xid), ctypes.byref(root), ctypes.byref(gx),
                   ctypes.byref(gy), ctypes.byref(w), ctypes.byref(h),
                   ctypes.byref(bw), ctypes.byref(depth))
    return int(w.value), int(h.value)


def set_input_passthrough(xid: int, hole: Tuple[int, int, int, int]) -> None:
    """Make the rectangle *hole* (device px, window-relative) pass clicks through.

    The window's X input shape is set to the whole window minus *hole*, so the
    chrome stays interactive while the capture area is transparent to input.
    """
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("input passthrough: %s", exc)
        return
    try:
        ext = _xshape()
        ext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        gw, gh = _window_size(x, dpy, xid)
        full = (_XRectangle * 1)(_XRectangle(0, 0, gw, gh))
        ext.XShapeCombineRectangles(dpy, ctypes.c_ulong(xid), _SHAPE_INPUT, 0, 0,
                                    full, 1, _SHAPE_SET, _SHAPE_UNSORTED)
        hx, hy, hw, hh = hole
        rect = (_XRectangle * 1)(_XRectangle(hx, hy, hw, hh))
        ext.XShapeCombineRectangles(dpy, ctypes.c_ulong(xid), _SHAPE_INPUT, 0, 0,
                                    rect, 1, _SHAPE_SUBTRACT, _SHAPE_UNSORTED)
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XFlush(dpy)
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("set_input_passthrough failed: %s", exc)
    finally:
        x.XCloseDisplay(dpy)


def clear_input_passthrough(xid: int) -> None:
    """Restore the whole window as input-reactive (undo passthrough)."""
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("clear passthrough: %s", exc)
        return
    try:
        ext = _xshape()
        ext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int,
        ]
        # A None (0) mask means "no input shape" -> the whole window is reactive.
        ext.XShapeCombineMask(dpy, ctypes.c_ulong(xid), _SHAPE_INPUT, 0, 0, 0, _SHAPE_SET)
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XFlush(dpy)
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("clear_input_passthrough failed: %s", exc)
    finally:
        x.XCloseDisplay(dpy)


# --- XShape bounding hole (compositor-free transparency) ----------------------


def set_bounding_hole(xid: int, hole: Tuple[int, int, int, int]) -> None:
    """Cut a real hole in the window's *bounding* shape over *hole*.

    Unlike ARGB transparency, the bounding shape is honoured by the X server
    itself, so the desktop shows through the rectangle *without* a compositing
    manager. The chrome around the hole keeps its pixels (and its input), while
    the hole region renders — and clicks — straight through to whatever is
    behind. *hole* is (x, y, w, h) in device px, relative to the window origin.
    """
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("bounding hole: %s", exc)
        return
    try:
        ext = _xshape()
        ext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        gw, gh = _window_size(x, dpy, xid)
        full = (_XRectangle * 1)(_XRectangle(0, 0, gw, gh))
        ext.XShapeCombineRectangles(dpy, ctypes.c_ulong(xid), _SHAPE_BOUNDING, 0, 0,
                                    full, 1, _SHAPE_SET, _SHAPE_UNSORTED)
        hx, hy, hw, hh = hole
        rect = (_XRectangle * 1)(_XRectangle(hx, hy, hw, hh))
        ext.XShapeCombineRectangles(dpy, ctypes.c_ulong(xid), _SHAPE_BOUNDING, 0, 0,
                                    rect, 1, _SHAPE_SUBTRACT, _SHAPE_UNSORTED)
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XFlush(dpy)
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("set_bounding_hole failed: %s", exc)
    finally:
        x.XCloseDisplay(dpy)


def clear_bounding_hole(xid: int) -> None:
    """Restore the whole window as drawn (undo :func:`set_bounding_hole`)."""
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("clear bounding hole: %s", exc)
        return
    try:
        ext = _xshape()
        ext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int,
        ]
        # A None (0) mask means "no bounding shape" -> the whole window is drawn.
        ext.XShapeCombineMask(dpy, ctypes.c_ulong(xid), _SHAPE_BOUNDING, 0, 0, 0, _SHAPE_SET)
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XFlush(dpy)
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("clear_bounding_hole failed: %s", exc)
    finally:
        x.XCloseDisplay(dpy)


def get_frame_extents(xid: int) -> Tuple[int, int, int, int]:
    """Return (left, right, top, bottom) CSD shadow margins in device px."""
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("frame extents: %s", exc)
        return (0, 0, 0, 0)
    try:
        for name in (b"_GTK_FRAME_EXTENTS", b"_NET_FRAME_EXTENTS"):
            atom = x.XInternAtom(dpy, name, True)
            if not atom:
                continue
            actual_type = ctypes.c_ulong()
            actual_format = ctypes.c_int()
            nitems = ctypes.c_ulong()
            bytes_after = ctypes.c_ulong()
            prop = ctypes.POINTER(ctypes.c_ulong)()
            x.XGetWindowProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ]
            status = x.XGetWindowProperty(
                dpy, ctypes.c_ulong(xid), ctypes.c_ulong(atom), 0, 4, False,
                _XA_CARDINAL, ctypes.byref(actual_type), ctypes.byref(actual_format),
                ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(prop),
            )
            if status == 0 and prop and nitems.value >= 4:
                vals = [int(prop[i]) for i in range(4)]
                x.XFree(prop)
                return (vals[0], vals[1], vals[2], vals[3])
            if prop:
                x.XFree(prop)
        return (0, 0, 0, 0)
    finally:
        x.XCloseDisplay(dpy)


def set_keep_above(xid: int) -> None:
    """Ask the window manager to keep *xid* above other windows."""
    try:
        x, dpy = _open()
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("keep-above: %s", exc)
        return
    try:
        wm_state = x.XInternAtom(dpy, b"_NET_WM_STATE", False)
        above = x.XInternAtom(dpy, b"_NET_WM_STATE_ABOVE", False)

        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        root = x.XDefaultRootWindow(dpy)

        # XClientMessageEvent laid out for XSendEvent.
        class _Data(ctypes.Union):
            _fields_ = [("l", ctypes.c_long * 5), ("s", ctypes.c_short * 10),
                        ("b", ctypes.c_char * 20)]

        class _ClientMessage(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_int),
                ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong),
                ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int),
                ("data", _Data),
            ]

        class _XEvent(ctypes.Union):
            _fields_ = [("type", ctypes.c_int), ("xclient", _ClientMessage),
                        ("pad", ctypes.c_long * 24)]

        ev = _XEvent()
        ev.xclient.type = 33  # ClientMessage
        ev.xclient.send_event = True
        ev.xclient.window = ctypes.c_ulong(xid).value
        ev.xclient.message_type = wm_state
        ev.xclient.format = 32
        ev.xclient.data.l[0] = _NET_WM_STATE_ADD
        ev.xclient.data.l[1] = above
        ev.xclient.data.l[2] = 0
        ev.xclient.data.l[3] = 1  # source: application

        x.XSendEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
            ctypes.POINTER(_XEvent),
        ]
        x.XSendEvent(dpy, ctypes.c_ulong(root), False,
                     _SUBSTRUCTURE_NOTIFY | _SUBSTRUCTURE_REDIRECT, ctypes.byref(ev))
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XFlush(dpy)
    except Exception as exc:  # pragma: no cover - env dependent
        log.debug("keep-above send failed: %s", exc)
    finally:
        x.XCloseDisplay(dpy)
