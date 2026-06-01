#!/bin/sh
# Build the GIF Forge .deb (Architecture: all, pure Python).
#
# Version resolution order:
#   1. $1 (explicit argument, e.g. ./build-deb.sh 0.1.0)
#   2. $GITHUB_REF_NAME with a leading "v" stripped (tag-driven CI releases)
#   3. whatever is already in debian/changelog
#
# The resulting gif-forge_<version>_all.deb is written to the parent directory
# (standard dpkg behaviour). Run from anywhere; paths are resolved from $0.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [ -z "$VERSION" ] && [ -n "${GITHUB_REF_NAME:-}" ]; then
  VERSION="${GITHUB_REF_NAME#v}"
fi

if [ -n "$VERSION" ]; then
  echo "Setting package version to $VERSION"
  if command -v dch >/dev/null 2>&1; then
    DEBEMAIL="${DEBEMAIL:-delacruzgarciajuan@gmail.com}" \
    DEBFULLNAME="${DEBFULLNAME:-Juan de la Cruz García}" \
      dch --newversion "$VERSION" --distribution unstable --force-bad-version \
        "Automated release build of $VERSION." \
      || sed -i "1s/^gif-forge ([^)]*)/gif-forge ($VERSION)/" debian/changelog
  else
    sed -i "1s/^gif-forge ([^)]*)/gif-forge ($VERSION)/" debian/changelog
  fi
fi

# Binary-only, unsigned build.
dpkg-buildpackage -us -uc -b

DEB="$(ls "$ROOT"/../gif-forge_*_all.deb 2>/dev/null | tail -n1 || true)"
if [ -n "$DEB" ]; then
  echo "Built: $DEB"
else
  echo "Build finished but no .deb was found in $ROOT/.." >&2
  exit 1
fi
