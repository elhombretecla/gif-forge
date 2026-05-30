# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry point: ``python -m gifforge``."""

import sys

from .ui.application import main

if __name__ == "__main__":
    sys.exit(main())
