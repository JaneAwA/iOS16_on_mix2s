#!/usr/bin/env bash
# Apply every change in this repository onto a checkout of upstream ios-sweet.
#
#   ./apply_to_upstream.sh /path/to/ios-sweet [upstream-ref]
#
# The result builds the same kernel that produced
# kernel.development.polaris in CI run 39470309899.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:?usage: apply_to_upstream.sh <ios-sweet-checkout> [upstream-ref]}"
REF="${2:-main}"

PATCH="$SRC/patches/upstream-polaris.diff"
[[ -f "$PATCH" ]] || { echo "missing $PATCH"; exit 1; }
[[ -d "$DEST/.git" ]] || { echo "$DEST is not a git checkout"; exit 1; }

echo "-> preparing branch polaris-port off $REF in $DEST"
git -C "$DEST" checkout -q -B polaris-port "$REF"

echo "-> dry run (git apply --check)"
git -C "$DEST" apply --check "$PATCH"

echo "-> applying"
git -C "$DEST" apply "$PATCH"

echo
echo "applied cleanly. next step:"
echo "  $SRC/ci/trigger_build.py --config POLARIS"
echo "(or push the branch, then dispatch 'XNU' with machine_config=POLARIS)"
