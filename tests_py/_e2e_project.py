# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""E2E: edit -> save project -> reopen restores edits; autosave -> recover."""
import subprocess
import tempfile
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib

from gifforge.project import SessionCache, list_recoverable
from gifforge.frames.decode import decode_to_frames
from gifforge.ui.application import GifForgeApplication
from gifforge.ui.editor_window import EditorWindow

DEST = Path(tempfile.mktemp(suffix=".gifforge"))
state = {}


def editors(app):
    return [w for w in app.get_windows() if isinstance(w, EditorWindow)]


def main():
    app = GifForgeApplication()

    sample = Path(tempfile.mktemp(suffix=".webm"))
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=2:size=120x90:rate=10",
                    "-codec:v", "libvpx-vp9", "-lossless", "1", str(sample)],
                   check=True, capture_output=True)

    def after(_a):
        cache = SessionCache()
        frames = decode_to_frames(sample, 10, cache)
        ed1 = EditorWindow(application=app)
        ed1.present()
        ed1.load(frames, cache=cache)

        def edit_and_save():
            ed1.reduce_frames(2)  # 20 -> 10 frames, delays fold to 200ms
            state["edited_frames"] = len(ed1._frames)
            state["edited_delays"] = [f.delay_ms for f in ed1._frames]
            ed1._write_project(DEST)
            state["saved"] = DEST.exists()
            # Simulate a crash autosave that was never cleared.
            ed1._do_autosave()
            state["recoverable"] = len(list_recoverable())
            # Reopen the saved project in a new editor.
            app.open_editor_with_project(DEST)
            GLib.timeout_add(700, check_reopen)
            return False

        def check_reopen():
            reopened = [e for e in editors(app) if e is not ed1]
            ed2 = reopened[-1] if reopened else None
            state["reopened_frames"] = len(ed2._frames) if ed2 else None
            state["reopened_delays"] = [f.delay_ms for f in ed2._frames] if ed2 else None
            sample.unlink(missing_ok=True)
            DEST.unlink(missing_ok=True)
            app.quit()
            return False

        GLib.timeout_add(600, edit_and_save)

    app.connect_after("activate", after)
    GLib.timeout_add_seconds(20, app.quit)
    app.run([])

    ok = (
        state.get("edited_frames") == 10
        and state.get("saved") is True
        and state.get("recoverable", 0) >= 1
        and state.get("reopened_frames") == 10
        and state.get("reopened_delays") == state.get("edited_delays")
    )
    for k, v in state.items():
        print(f"  {k}: {v}")
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
