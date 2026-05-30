# GIF Forge — User Guide

GIF Forge records a region, window or screen and lets you refine the result on
a timeline before exporting an optimized GIF, video or APNG.

## Recording

1. Launch GIF Forge. The recorder window frames a transparent capture area —
   position it over what you want to record (on X11) or pick a source in the
   system dialog (on Wayland).
2. Choose the output format (GIF / APNG / WebM) from the header bar.
3. Press **Record**. After the optional countdown, capture begins.
4. Press **Stop**.

By default the recording opens in the **editor** (see below). To save
immediately without editing, turn off *Open editor after recording* in
Preferences.

### Capture backends

- **Wayland (preferred):** uses the desktop's screen-cast portal + PipeWire, so
  it works on GNOME, KDE and wlroots compositors. The compositor shows its own
  source picker.
- **X11:** captures the region under the window directly.

## Editing

The editor shows a **preview** above a **frame strip** (timeline).

- **Play / pause** and step through frames; toggle **loop** and **fit/100%**.
- Select frames in the strip (click, Ctrl-click, Shift-click for ranges).

Operations (Edit menu, toolbar, or shortcuts):

| Action | Shortcut |
|---|---|
| Delete selected frames | `Delete` |
| Duplicate selected frames | `Ctrl+D` |
| Trim to selection | Edit menu |
| Reverse | Edit menu |
| Remove duplicate frames | Edit menu |
| Reduce frames (keep every 2nd) | Edit menu |
| Double / half speed | Edit menu |
| Increase / decrease delay | Edit menu |
| Undo / redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Play / pause | `Space` |

Every edit is undoable.

## Exporting

Press **Export…**, choose a preset (looping GIF, GIF once, APNG, WebM), pick a
destination, and GIF Forge re-encodes the edited timeline — honoring each
frame's delay. A notification confirms when it's done.

## Projects, autosave and recovery

- **Save project** (`Ctrl+S`) writes a `.gifforge` file containing the frames
  and your edits, so you can reopen and continue later (`Ctrl+O`).
- The editor **autosaves** in the background. If the app closes unexpectedly,
  the next launch offers to **recover** the unsaved recording.

## Preferences

Frame rate, downsample factor, mouse-cursor capture, sound capture (WebM),
start delay, gifski quality, notifications, dark theme, and whether to open the
editor after recording.
