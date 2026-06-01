# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manual end-to-end editor driver (run under an X11 display).

Decodes a short clip, loads the editor window, then exercises selection,
navigation and playback, asserting the current frame tracks correctly.
"""
import subprocess
import tempfile
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from gifforge.project.cache import SessionCache
from gifforge.frames.decode import decode_to_frames
from gifforge.ui.editor_window import EditorWindow

state = {"steps": [], "ok": False, "error": None}


def main():
    Adw.init()
    app = Adw.Application(application_id="io.github.elhombretecla.GifForge.EditorTest")

    sample = Path(tempfile.mktemp(suffix=".webm"))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=2:size=200x150:rate=10",
         "-codec:v", "libvpx-vp9", "-lossless", "1", str(sample)],
        check=True, capture_output=True,
    )
    cache = SessionCache()
    frames = decode_to_frames(sample, 10, cache)
    print("decoded frames:", len(frames))

    def on_activate(_a):
        win = EditorWindow(application=app)
        win.present()
        win.load(frames)

        def step1():
            print("after load, current:", win.current_index)
            state["steps"].append(("load", win.current_index == 0))
            win._strip.select(10)
            return False

        def step2():
            print("after select(10), current:", win.current_index)
            state["steps"].append(("select", win.current_index == 10))
            win.go_first()
            win.toggle_play()  # start playback from 0
            # Poll for advancement instead of asserting at a fixed instant: under
            # CI load the per-frame play timer can tick late, which made a
            # fixed-time check flaky. Pass as soon as the frame advances; only
            # fail if it never advances within a generous window.
            poll = {"ticks": 0}

            def poll_playback():
                poll["ticks"] += 1
                advanced = win.current_index > 0
                if advanced or poll["ticks"] >= 60:  # ~3s at 50ms intervals
                    print("during playback, current:", win.current_index)
                    state["steps"].append(("playback-advanced", advanced))
                    win.toggle_play()  # pause
                    step4()
                    return False
                return True

            GLib.timeout_add(50, poll_playback)
            return False

        def step4():
            # Exercise edit ops + undo/redo through the real window methods.
            n0 = len(win._frames)
            win._strip.select(5)
            win.delete_selected()
            state["steps"].append(("delete", len(win._frames) == n0 - 1))
            win.undo()
            state["steps"].append(("undo-delete", len(win._frames) == n0))
            win.redo()
            state["steps"].append(("redo-delete", len(win._frames) == n0 - 1))
            win.duplicate_selected()
            state["steps"].append(("duplicate", len(win._frames) == n0))
            d0 = win._frames.total_duration_ms
            win.change_speed(2.0)  # half speed -> longer total
            state["steps"].append(("speed", win._frames.total_duration_ms > d0))
            finish()
            return False

        def finish():
            cache.cleanup()
            sample.unlink(missing_ok=True)
            state["ok"] = all(ok for _, ok in state["steps"])
            app.quit()

        GLib.timeout_add(700, step1)
        GLib.timeout_add(1100, step2)

    app.connect_after("activate", on_activate)
    GLib.timeout_add_seconds(20, app.quit)
    app.run([])

    for name, ok in state["steps"]:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print("error:", state["error"])
    raise SystemExit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
