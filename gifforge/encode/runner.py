# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Subprocess runner for CLI tools (ffmpeg, gifski).

Replaces Peek's ``CliPostProcessor.spawn_command_async``. Synchronous by
design; callers run it off the GTK main thread (see ui layer) and pass a
``threading.Event`` to support cancellation.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Sequence

from .errors import CancelledError, EncodeError

log = logging.getLogger(__name__)


def run_command(
    argv: Sequence[str],
    *,
    cancel_event: threading.Event | None = None,
    poll_interval: float = 0.1,
) -> str:
    """Run *argv* to completion, returning combined stdout+stderr.

    Raises :class:`EncodeError` on non-zero exit and :class:`CancelledError`
    if *cancel_event* is set while the process is running.
    """
    log.debug("running: %s", " ".join(argv))
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise EncodeError(f"failed to launch {argv[0]!r}: {exc}") from exc

    try:
        while True:
            try:
                out, _ = proc.communicate(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    proc.kill()
                    proc.wait()
                    raise CancelledError("encoding cancelled") from None
                continue
    finally:
        if proc.poll() is None:
            proc.kill()

    if proc.returncode != 0:
        raise EncodeError(
            f"{argv[0]} exited with {proc.returncode}:\n{(out or '').strip()}"
        )
    return out or ""
