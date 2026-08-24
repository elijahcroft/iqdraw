"""
Shared test helpers.

Puts `tools/` on the import path so the tests run from anywhere without an
install step, and finds the example builds regardless of where the checkout
sits.  iqdraw has no dependencies and the tests keep that promise: everything
here is standard library.
"""

import importlib.util
import pathlib
import sys

_TOOLS = pathlib.Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from iqdraw import Build, parts  # noqa: E402


def examples_dir():
    """
    Where the shipped example specs live.

    Standalone IQDraw keeps them in `examples/`. Looking for `builds/` as a
    fallback also lets the suite validate older teaching-repo checkouts.
    """
    for base in (_TOOLS.parent, _TOOLS / "iqdraw"):
        for name in ("builds", "examples"):
            d = base / name
            if d.is_dir() and any(d.glob("*.py")):
                return d
    raise RuntimeError("no example builds found")


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
