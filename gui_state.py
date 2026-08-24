"""Small, dependency-free persistence helpers for IQDraw Studio."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import asdict, dataclass, field
from typing import Mapping, Optional


MAX_RECENT = 8


@dataclass
class StudioState:
    """Preferences worth carrying between GUI sessions."""

    recent_files: list[str] = field(default_factory=list)
    detail: str = "simple"
    context_detail: str = "same"
    hero: bool = True
    checks: bool = True
    strict: bool = False
    export_svg: bool = False
    export_png: bool = False
    trust_notice_seen: bool = False

    def remember(self, path: pathlib.Path) -> None:
        resolved = str(path.resolve())
        self.recent_files = [
            resolved,
            *(item for item in self.recent_files if item != resolved),
        ][:MAX_RECENT]

    def existing_recent_files(self) -> list[pathlib.Path]:
        return [pathlib.Path(item) for item in self.recent_files
                if pathlib.Path(item).is_file()]


def config_path(environ: Optional[Mapping[str, str]] = None,
                platform: Optional[str] = None) -> pathlib.Path:
    """Use each platform's conventional per-user application directory."""
    env = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    if system == "win32":
        base = env.get("APPDATA") or env.get("LOCALAPPDATA")
        if base:
            return pathlib.Path(base) / "IQDraw" / "studio.json"
    elif system == "darwin":
        return (pathlib.Path(env.get("HOME", "~")).expanduser()
                / "Library" / "Application Support" / "IQDraw" / "studio.json")
    base = env.get("XDG_CONFIG_HOME")
    if base:
        return pathlib.Path(base) / "iqdraw" / "studio.json"
    return (pathlib.Path(env.get("HOME", "~")).expanduser()
            / ".config" / "iqdraw" / "studio.json")


def load_state(path: pathlib.Path) -> StudioState:
    """Read valid known settings and quietly recover from stale/corrupt files."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return StudioState()
    if not isinstance(raw, dict):
        return StudioState()
    state = StudioState()
    recent = raw.get("recent_files")
    if isinstance(recent, list):
        state.recent_files = [item for item in recent
                              if isinstance(item, str)][:MAX_RECENT]
    if raw.get("detail") in ("simple", "cad"):
        state.detail = raw["detail"]
    if raw.get("context_detail") in ("same", "simple", "cad"):
        state.context_detail = raw["context_detail"]
    for name in ("hero", "checks", "strict", "export_svg", "export_png",
                 "trust_notice_seen"):
        if isinstance(raw.get(name), bool):
            setattr(state, name, raw[name])
    return state


def save_state(path: pathlib.Path, state: StudioState) -> None:
    """Atomically save settings so an interrupted write cannot corrupt them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def bundled_examples(package_dir: pathlib.Path) -> list[pathlib.Path]:
    """Return public examples when running from a checkout or installed wheel."""
    directory = package_dir / "examples"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.py")
                  if not path.name.startswith("_"))
