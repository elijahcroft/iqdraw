#!/usr/bin/env bash
# Assemble the GitHub Pages site into _site/.
#
# Generated booklets are never committed - they are rendered here, from the
# examples in the repository, every time the site is deployed. That keeps the
# published output honest: it is whatever the current code actually draws.
#
#   ./docs/build.sh          write _site/ using the `iqdraw` on PATH
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$here/_site"

rm -rf "$out"
mkdir -p "$out/examples" "$out/steps"
cp "$here/docs/index.html" "$out/index.html"

# The hero steps through this build, showing each spec fragment beside the
# drawing it produced, so the SVGs have to be the real rendered steps.
iqdraw "$here/examples/pinned-frame.py" \
    -o "$out/examples/pinned-frame.html" --svg-dir "$out/steps" --strict

for name in gear-train drive-base grabber-arm; do
    iqdraw "$here/examples/$name.py" -o "$out/examples/$name.html" --strict
done

echo "built $out"
du -sh "$out"
