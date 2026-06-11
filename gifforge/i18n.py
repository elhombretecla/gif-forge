# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Internationalisation (gettext) wiring for GIF Forge.

UI modules import ``_`` from here and wrap user-facing strings in ``_( ... )``.
``_`` is :func:`gettext.gettext`, which resolves against the process-global text
domain at *call* time — so it reflects whatever language :func:`init` selected,
regardless of import order. Call :func:`init` once at startup before any window
is built.

English is the source language (the ``msgid`` strings), so an empty/“en”
selection simply uses the untranslated literals. Other languages load a compiled
``gif-forge.mo`` catalogue from the locale directory.
"""

from __future__ import annotations

import gettext as _gettext
import locale
import logging
import os
import sys
from typing import List

log = logging.getLogger(__name__)

DOMAIN = "gif-forge"

# Languages we ship a catalogue for (plus English as the source language).
SUPPORTED_LANGUAGES = ["en", "es", "fr", "de", "pt"]

# Resolves translations against the global text domain at call time. Import this
# as ``from ..i18n import _`` in UI modules.
_ = _gettext.gettext


def _candidate_localedirs() -> List[str]:
    dirs: List[str] = []
    env = os.environ.get("GIFFORGE_LOCALEDIR")
    if env:
        dirs.append(env)
    # Flatpak prefix, then the running interpreter's prefix, then system paths.
    dirs.append("/app/share/locale")
    dirs.append(os.path.join(sys.prefix, "share", "locale"))
    dirs.append("/usr/local/share/locale")
    dirs.append("/usr/share/locale")
    return dirs


def find_localedir() -> str | None:
    """Return the locale dir that actually holds a compiled gif-forge catalogue.

    Returns ``None`` if none is found, letting gettext fall back to the system
    default (and, in turn, to the untranslated English source strings).
    """
    seen = set()
    for d in _candidate_localedirs():
        if not d or d in seen:
            continue
        seen.add(d)
        if not os.path.isdir(d):
            continue
        for lang in SUPPORTED_LANGUAGES:
            mo = os.path.join(d, lang, "LC_MESSAGES", f"{DOMAIN}.mo")
            if os.path.exists(mo):
                return d
    return None


def init(language: str | None = None) -> None:
    """Set up gettext for the whole process.

    *language* is the preferred UI language code ("en", "es", …) or ``None``/
    "system" to follow the environment. English ("en") needs no catalogue.
    Changing the language takes effect on the next launch (this runs once at
    startup, before any string is translated).
    """
    if language and language not in ("system", "en"):
        # Drive language selection deterministically, independent of the host
        # locale. gettext reads LANGUAGE (colon-separated, highest priority).
        os.environ["LANGUAGE"] = language

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        # A misconfigured/missing host locale must never crash the app.
        pass

    localedir = find_localedir()

    # Bind for the C library too (covers GTK's own translated strings and any
    # Gtk.Builder UI that opts into translation); not available on every OS.
    try:
        locale.bindtextdomain(DOMAIN, localedir)
        locale.textdomain(DOMAIN)
    except (AttributeError, locale.Error):
        pass

    _gettext.bindtextdomain(DOMAIN, localedir)
    _gettext.textdomain(DOMAIN)
    log.debug("i18n: language=%s localedir=%s", language, localedir)
