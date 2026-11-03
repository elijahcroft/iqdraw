#!/usr/bin/env bash
# Run the iqdraw test suite. The tests use unittest, so they need nothing
# beyond what the library itself needs (numpy).
#
#   ./run-tests.sh            all of it
#   ./run-tests.sh test_check just one module
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# No PYTHONPATH needed: tests/support.py makes the checkout importable as
# `iqdraw` whatever the clone is called.
cd "$here/tests"
if [ $# -eq 0 ]; then
    exec python3 -m unittest discover -t . "$@"
fi
exec python3 -m unittest "$@"
