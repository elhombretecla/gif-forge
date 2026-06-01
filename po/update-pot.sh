#!/bin/sh
# Regenerate po/gif-forge.pot from the source strings and merge it into every
# translation, for maintainers. Needs gettext (xgettext, msgmerge).
#
#   sh po/update-pot.sh
#
# After this, edit the per-language po/<lang>.po files to fill in new msgstr.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

xgettext \
  --from-code=UTF-8 \
  --keyword=_ \
  --language=Python \
  --package-name="gif-forge" \
  --package-version="0.1.0" \
  --msgid-bugs-address="https://github.com/elhombretecla/gif-forge/issues" \
  --files-from=po/POTFILES.in \
  --output=po/gif-forge.pot

while read -r lang; do
  case "$lang" in ""|\#*) continue ;; esac
  echo "Merging $lang…"
  msgmerge --update --backup=none "po/$lang.po" po/gif-forge.pot
done < po/LINGUAS

echo "Updated po/gif-forge.pot and merged all languages."
