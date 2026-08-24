#!/usr/bin/env bash
# Run the iqdraw test suite. No install and no dependencies - the tests use
# unittest for the same reason the library uses no third-party packages.
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
