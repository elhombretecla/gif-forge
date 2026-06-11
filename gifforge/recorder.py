# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recording orchestration: capture backend + encode pipeline.

UI-agnostic and synchronous. The UI runs :meth:`stop_and_encode` on a worker
thread and marshals the result back to the GTK main loop. Keeping this free of
GTK makes the record→encode sequence unit-testable.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .capture import CaptureBackend, create_backend
from .encode import encode_recording
from .models import RecordingArea, RecordingConfig

log = logging.getLogger(__name__)


class RecordingController:
    def __init__(self, config: RecordingConfig, *, prefer: str | None = None) -> None:
        self.config = config
        self._prefer = prefer
        self._backend: CaptureBackend | None = None
        self._cancel = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._backend is not None

    def start(self, area: RecordingArea) -> str:
        """Create a backend and begin recording. Returns the backend name."""
        if self._backend is not None:
            raise RuntimeError("already recording")
        self._cancel.clear()
        self._backend = create_backend(self.config, prefer=self._prefer)
        self._backend.start(area)
        log.info("recording started via %s", self._backend.name)
        return self._backend.name

    def stop_capture(self) -> Path:
        """Stop capture and return the raw intermediate (no encoding).

        Used by the editor flow, which decodes the intermediate into frames.
        Blocking — call from a worker thread.
        """
        if self._backend is None:
            raise RuntimeError("not recording")
        backend = self._backend
        try:
            return backend.stop()
        finally:
            self._backend = None

    def stop_and_encode(self) -> Path:
        """Stop capture and run the encode pipeline. Returns the output path.

        Blocking — call from a worker thread.
        """
        if self._backend is None:
            raise RuntimeError("not recording")
        backend = self._backend
        try:
            intermediate = backend.stop()
            log.debug("intermediate recording: %s", intermediate)
            if backend.intermediate_is_final:
                # Already captured in the output format at final quality;
                # re-encoding would only add a lossy generation.
                log.debug("intermediate is final; passing through")
                return intermediate
            output = encode_recording(intermediate, self.config, cancel_event=self._cancel)
            # The lossless intermediate is no longer needed.
            try:
                intermediate.unlink(missing_ok=True)
            except OSError:
                pass
            return output
        finally:
            self._backend = None

    def cancel(self) -> None:
        """Abort an in-progress recording or encode."""
        self._cancel.set()
        if self._backend is not None:
            self._backend.cancel()
            self._backend = None
