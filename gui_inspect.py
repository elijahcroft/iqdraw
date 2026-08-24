"""Isolated build inspection used by IQDraw Studio.

A build spec is a Python program. Loading it in this short-lived process keeps
its imports and global state out of the desktop application's own process.
It is isolation for reliability, not a security sandbox; the GUI says so
before it opens a user's first build.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

from .gui import inspect_build


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: python -m iqdraw.gui_inspect BUILD.py")
    # Specs occasionally print progress while defining a build. Keep that
    # output from corrupting the JSON protocol on stdout.
    with contextlib.redirect_stdout(io.StringIO()):
        summary = inspect_build(pathlib.Path(args[0]))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
