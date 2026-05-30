# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings / preferences layer.

Wraps GSettings when the compiled schema is available (production / Flatpak)
and transparently falls back to a JSON file under XDG_CONFIG_HOME for plain
development checkouts. The key names mirror Peek's original gschema so dconf
data and translations carry over.
"""

from .config import DEFAULTS, Settings, get_settings

__all__ = ["DEFAULTS", "Settings", "get_settings"]
