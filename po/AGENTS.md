# AGENTS.md — translations

Scope: the `po/` directory. Extends the root [`AGENTS.md`](../AGENTS.md).

GIF Forge uses gettext. The text domain is **`gif-forge`** and **English is the
source language** (the `msgid` strings), so there is no `en.po` — English is just
the untranslated literals.

## Files

- `gif-forge.pot` — template (all source `msgid`s, no translations).
- `<lang>.po` — one catalogue per language listed in `LINGUAS` (`es`, `fr`,
  `de`, `pt`).
- `LINGUAS` — the set of shipped languages.
- `POTFILES.in` — the source files scanned for translatable strings.
- `update-pot.sh` — regenerates the `.pot` and merges it into every `.po`.

## Rules

- **Never edit or commit `.mo` files.** They are compiled from `.po` at install
  time (by `build-aux/flatpak/install-data.sh`, `debian/rules`, and `run.sh` for
  dev). Edit the `.po` source only.
- After adding/changing `_()` strings in the code, run `sh po/update-pot.sh`
  (needs `gettext`), then fill in the new `msgstr` in each `po/<lang>.po`.
- **Keep `{named}` placeholders byte-for-byte identical** to the English `msgid`
  (e.g. `{count}`, `{path}`, `{seconds:.1f}`). A mismatch crashes `str.format`.
- Preserve **mnemonic underscores** (`_Save`, `_Cancel`) — the `_` marks the
  keyboard accelerator; place it before a suitable letter in the translation.
- Don't translate the brand name **“GIF Forge”** or tool names (`gifski`,
  `ffmpeg`, `WebM`, `APNG`).

## Translation quality status

- **`es`** (Spanish) is human-quality and reviewed.
- **`fr`, `de`, `pt`** are **best-effort and not yet reviewed by a native
  speaker** — improve them freely; treat existing strings as drafts.

## Adding a new language

1. Add its code to `LINGUAS`.
2. Add it to `SUPPORTED_LANGUAGES` in `gifforge/i18n.py`, `_LANGUAGE_NAMES` in
   `gifforge/ui/preferences_window.py`, and the `<choices>` in
   `data/io.github.elhombretecla.GifForge.gschema.xml`.
3. Create `po/<lang>.po` (copy `gif-forge.pot` and translate, or
   `msginit --locale=<lang> --input=gif-forge.pot`).
