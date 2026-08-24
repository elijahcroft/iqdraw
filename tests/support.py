"""
Shared test helpers.

Makes this checkout importable as `iqdraw` so the tests run from anywhere
without an install step, and finds the example builds relative to the
checkout rather than by guessing at directory names.  iqdraw has no
dependencies and the tests keep that promise: everything here is standard
library.
"""

import atexit
import importlib.util
import pathlib
import shutil
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _find_import_root():
    """
    A directory that holds this checkout under the name `iqdraw`.

    The package directory *is* the repository root, so importing it by name
    normally requires the checkout itself to be called `iqdraw`.  A clone
    keeps whatever name the remote has, so when it is called something else
    we point at a throwaway directory that spells it correctly.  Both the
    in-process imports below and the CLI subprocesses in `test_cli` need
    this, which is why it is computed once and shared.
    """
    if _ROOT.name == "iqdraw":
        return _ROOT.parent
    shim = pathlib.Path(tempfile.mkdtemp(prefix="iqdraw-import-"))
    atexit.register(shutil.rmtree, shim, True)
    try:
        (shim / "iqdraw").symlink_to(_ROOT, target_is_directory=True)
    except OSError:  # no symlink privilege; fall back to an installed copy
        shutil.rmtree(shim, True)
        return _ROOT.parent
    return shim


#: Also what a subprocess needs on its `PYTHONPATH`; see `test_cli`.
IMPORT_ROOT = str(_find_import_root())
if IMPORT_ROOT not in sys.path:
    sys.path.insert(0, IMPORT_ROOT)

from iqdraw import Build, parts  # noqa: E402


def examples_dir():
    """Where the shipped example specs live."""
    d = _ROOT / "examples"
    if not (d.is_dir() and any(d.glob("*.py"))):
        raise RuntimeError(f"no example builds found in {d}")
    return d


def example_names():
    return sorted(p.stem for p in examples_dir().glob("*.py")
                  if not p.stem.startswith("_"))


def load_example(name):
    path = examples_dir() / f"{name}.py"
    # Builds may import shared modules from beside them, the same way the CLI
    # arranges it in `load_build`.
    here = str(path.parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location(f"_ex_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return next(v for v in vars(module).values() if isinstance(v, Build))
