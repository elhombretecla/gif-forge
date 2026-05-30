# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Absolute on-screen position of an X11 window via libX11 (ctypes).

GTK4 deliberately removed the window-position APIs that Peek's GTK3 code used
(``Gdk.Window.get_origin``). For the X11 capture backend we still need absolute
coordinates, so we ask the X server directly with ``XTranslateCoordinates`` —
no extra Python dependency, just libX11 which is present on every X11 system.

On Wayland this is unused; the ScreenCast portal supplies the region (T4).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from typing import Tuple


def _load_x11() -> ctypes.CDLL:
    name = ctypes.util.find_library("X11")
    if not name:
        raise RuntimeError("libX11 not found")
    return ctypes.CDLL(name)


def absolute_origin(xid: int) -> Tuple[int, int]:
    """Return the absolute (root-relative) coordinates of *xid*'s origin."""
    x11 = _load_x11()
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XTranslateCoordinates.restype = ctypes.c_int
    x11.XTranslateCoordinates.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display_name = os.environ.get("DISPLAY", "").encode() or None
    dpy = x11.XOpenDisplay(display_name)
    if not dpy:
        raise RuntimeError("cannot open X display")
    try:
        root = x11.XDefaultRootWindow(dpy)
        dest_x = ctypes.c_int()
        dest_y = ctypes.c_int()
        child = ctypes.c_ulong()
        ok = x11.XTranslateCoordinates(
            dpy, ctypes.c_ulong(xid), root, 0, 0,
            ctypes.byref(dest_x), ctypes.byref(dest_y), ctypes.byref(child),
        )
        if not ok:
            raise RuntimeError("XTranslateCoordinates failed")
        return int(dest_x.value), int(dest_y.value)
    finally:
        x11.XCloseDisplay(dpy)
