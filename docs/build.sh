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
mkdir -p "$out/examples" "$out/steps" "$out/previews"
cp "$here/docs/index.html" "$out/index.html"

# Small raster previews keep the landing page fast while still showing the
# real renderer. They use the included procedural geometry so the public site
# is reproducible without the optional, non-redistributable CAD provider.
python3 "$here/docs/render-previews.py" "$out/previews"

# The hero steps through this build, showing each spec fragment beside the
# drawing it produced, so the SVGs have to be the real rendered steps.
iqdraw "$here/examples/pinned-frame.py" \
    -o "$out/examples/pinned-frame.html" --svg-dir "$out/steps" \
    --detail simple --strict

for name in gear-train drive-base grabber-arm survey-rover; do
    iqdraw "$here/examples/$name.py" -o "$out/examples/$name.html" \
        --detail simple --strict
done

echo "built $out"
du -sh "$out"
