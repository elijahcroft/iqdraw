"""A friendly desktop front end for IQDraw.

The GUI deliberately drives the same command-line entry point as terminal
users.  There is one rendering path to maintain, and a failed spec produces
the same useful line-numbered error in both interfaces.
"""

from __future__ import annotations

import os
import pathlib
import queue
import json
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from typing import Optional

from . import parts
from .__main__ import STARTER, load_build
from .check import check
from .gui_state import (
    StudioState, bundled_examples, config_path, load_state, save_state,
)


DETAIL_OPTIONS = {
    "cad": "CAD models (recommended)",
    "simple": "Procedural models (faster)",
}
CONTEXT_OPTIONS = {
    "same": "Match new parts",
    "cad": "CAD models",
    "simple": "Procedural models (smaller file)",
}


def _option_label(value: str, options: dict[str, str]) -> str:
    """Translate a stored/CLI value into friendly Studio copy."""
    return options.get(value, options[next(iter(options))])


def _option_value(label: str, options: dict[str, str]) -> str:
    """Translate friendly Studio copy back to a stable stored/CLI value."""
    return next((value for value, copy in options.items() if copy == label),
                next(iter(options)))


@dataclass(frozen=True)
class RenderSettings:
    spec: pathlib.Path
    output: pathlib.Path
    detail: str = parts.DEFAULT_DETAIL
    context_detail: str = "same"
    hero: bool = True
    checks: bool = True
    strict: bool = False
    svg_dir: Optional[pathlib.Path] = None
    png: bool = False
    source_mtime_ns: Optional[int] = None


def render_command(settings: RenderSettings) -> list[str]:
    """Return the CLI command represented by the form (kept easy to test)."""
    command = [sys.executable, "-m", "iqdraw", str(settings.spec),
               "-o", str(settings.output), "--detail", settings.detail]
    if settings.context_detail != "same":
        command.extend(("--context-detail", settings.context_detail))
    if not settings.hero:
        command.append("--no-hero")
    if not settings.checks:
        command.append("--no-check")
    elif settings.strict:
        command.append("--strict")
    if settings.svg_dir:
        command.extend(("--svg-dir", str(settings.svg_dir)))
    if settings.png:
        command.append("--png")
    return command


def source_is_current(settings: RenderSettings) -> bool:
    """Whether a completed render still represents the source it started on."""
    if settings.source_mtime_ns is None:
        return True
    try:
        return settings.spec.stat().st_mtime_ns == settings.source_mtime_ns
    except OSError:
        return False


def inspection_command(path: pathlib.Path) -> list[str]:
    """Build inspection runs separately so spec globals cannot pollute the GUI."""
    return [sys.executable, "-m", "iqdraw.gui_inspect", str(path)]


def create_starter(path: pathlib.Path, title: str) -> None:
    """Create, but never overwrite, a starter spec with a useful title."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_title = (title.strip() or path.stem.replace("-", " ").title())
    body = STARTER.replace('"My Build"', repr(safe_title), 1)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(body)


def inspect_build(path: pathlib.Path) -> dict:
    """Load a spec and return the small, display-oriented build summary."""
    build = load_build(path)
    inventory = build.inventory()
    return {
        "title": build.title,
        "subtitle": build.subtitle,
        "steps": len(build.steps),
        "parts": sum(inventory.values()),
        "part_types": len(inventory),
        "problems": [str(problem) for problem in check(build)],
        "step_rows": [
            (number, step.section.title if step.section else "Build",
             step.note or "Check your work", sum(step.part_counts().values()))
            for number, step in enumerate(build.steps, 1)
        ],
        "inventory": sorted(
            ((parts.get(name, color).label, qty)
             for (name, color), qty in inventory.items()),
            key=lambda row: row[0].lower(),
        ),
    }


def _open_in_system(path: pathlib.Path) -> bool:
    """Open a local file with its platform default application."""
    path = path.resolve()
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return True
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if opener:
        command = [opener, str(path)]
        if pathlib.Path(opener).name == "gio":
            command.insert(1, "open")
        subprocess.Popen(command)
        return True
    return webbrowser.open(path.as_uri())


def _tk():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError as exc:  # pragma: no cover - depends on OS packaging
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        if "linuxbrew" in sys.executable or "linuxbrew" in sys.prefix:
            remedy = f"Run: brew install python-tk@{version}"
        elif sys.platform.startswith("linux"):
            remedy = ("Install your distribution's Tk package for this Python "
                      "version (often python3-tk), then recreate the environment.")
        else:
            remedy = "Reinstall Python with Tcl/Tk support enabled."
        raise SystemExit(
            "IQDraw Studio cannot start because this Python interpreter has "
            f"no Tk support:\n  {sys.executable}\n\n{remedy}\n\n"
            f"Technical detail: {exc}"
        ) from exc
    try:
        import customtkinter as ctk
    except ImportError as exc:  # pragma: no cover - installation is external
        raise SystemExit(
            "IQDraw Studio cannot import CustomTkinter. Install this checkout "
            f"with:\n  {sys.executable} -m pip install -e .\n\n"
            f"Technical detail: {exc}"
        ) from exc
    return ctk, tk, filedialog, messagebox


class IQDrawApp:
    """Native desktop interface; constructed only after Tk is available."""

    BG = ("#F3F6FA", "#0B1120")
    CARD = ("#FFFFFF", "#131C2E")
    CARD_ALT = ("#F7F9FC", "#19243A")
    INK = ("#152033", "#F3F7FF")
    MUTED = ("#667085", "#9AA8BE")
    BORDER = ("#DFE5EF", "#283750")
    BLUE = "#246BFD"
    BLUE_DARK = "#1855D1"
    FOCUS = "#D97706"
    GREEN = ("#087A4C", "#39D69A")
    AMBER = "#D88912"

    def __init__(self, root):
        self.ctk, self.tk, self.filedialog, self.messagebox = _tk()
        self.root = root
        self.spec_path: pathlib.Path | None = None
        self._state_path = config_path()
        self.state = load_state(self._state_path)
        self.examples = bundled_examples(pathlib.Path(__file__).resolve().parent)
        self._loaded_mtime: Optional[float] = None
        self._working = False
        self._rendering = False
        self._events: queue.Queue = queue.Queue()
        self._configure_window()
        self._build_theme()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<FocusIn>", self._check_source_changed, add="+")
        self.root.after(80, self._poll_events)

    def _configure_window(self):
        self.root.title("IQDraw Studio")
        # Tiling compositors can ignore Tk's minimum size and squeeze the
        # studio into a quarter-screen tile. The dialog type asks them to open
        # this tool-sized window floating; users can still tile it afterwards.
        if sys.platform.startswith("linux"):
            try:
                self.root.attributes("-type", "dialog")
            except self.tk.TclError:
                pass
        self.root.geometry("1100x720")
        self.root.minsize(760, 560)
        self.root.configure(fg_color=self.BG)

    def _build_theme(self):
        self.ctk.set_appearance_mode("system")
        self.ctk.set_default_color_theme("blue")
        self.font_title = self.ctk.CTkFont(size=29, weight="bold")
        self.font_heading = self.ctk.CTkFont(size=16, weight="bold")
        self.font_metric = self.ctk.CTkFont(size=25, weight="bold")
        self.font_label = self.ctk.CTkFont(size=12, weight="bold")
        self.font_body = self.ctk.CTkFont(size=13)
        self.font_small = self.ctk.CTkFont(size=11)

    def _build_menu(self):
        accelerator = "Cmd" if sys.platform == "darwin" else "Ctrl"
        menu = self.tk.Menu(self.root)
        file_menu = self.tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New build…", accelerator=f"{accelerator}+N",
                              command=self.new_build)
        file_menu.add_command(label="Open build…", accelerator=f"{accelerator}+O",
                              command=self.choose_build)
        self.recent_menu = self.tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open recent", menu=self.recent_menu)
        self.examples_menu = self.tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open example", menu=self.examples_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)

        self.build_menu = self.tk.Menu(menu, tearoff=False)
        self.build_menu.add_command(label="Reload build", accelerator=f"{accelerator}+R",
                                    command=self.reload)
        self.build_menu.add_command(label="Edit source", accelerator=f"{accelerator}+E",
                                    command=self.edit_source)
        self.build_menu.add_separator()
        self.build_menu.add_command(label="Create booklet",
                                    accelerator=f"{accelerator}+G",
                                    command=self.generate)
        self.build_menu.add_command(label="Open latest booklet",
                                    command=self.open_output)
        self.build_menu.add_command(label="Show output folder",
                                    command=self.open_output_folder)
        menu.add_cascade(label="Build", menu=self.build_menu)

        help_menu = self.tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Getting started", accelerator="F1",
                              command=self.show_getting_started)
        help_menu.add_command(label="About IQDraw Studio", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)
        self._rebuild_file_menus()

    def _rebuild_file_menus(self):
        self.recent_menu.delete(0, "end")
        recent = self.state.existing_recent_files()
        if recent:
            for path in recent:
                self.recent_menu.add_command(
                    label=f"{path.name}  —  {path.parent}",
                    command=lambda selected=path: self.open_path(selected),
                )
            self.recent_menu.add_separator()
            self.recent_menu.add_command(label="Clear recent files",
                                         command=self.clear_recent)
        else:
            self.recent_menu.add_command(label="No recent builds", state="disabled")
        self.examples_menu.delete(0, "end")
        if self.examples:
            for path in self.examples:
                self.examples_menu.add_command(
                    label=path.stem.replace("-", " ").title(),
                    command=lambda selected=path: self.open_path(selected, trusted=True),
                )
        else:
            self.examples_menu.add_command(label="No examples installed", state="disabled")

    def _bind_shortcuts(self):
        modifier = "Command" if sys.platform == "darwin" else "Control"
        bindings = {
            f"<{modifier}-n>": self.new_build,
            f"<{modifier}-o>": self.choose_build,
            f"<{modifier}-r>": self.reload,
            f"<{modifier}-e>": self.edit_source,
            f"<{modifier}-g>": self.generate,
            f"<{modifier}-Return>": self.generate,
            "<F1>": self.show_getting_started,
        }
        for sequence, callback in bindings.items():
            self.root.bind(sequence, lambda _event, fn=callback: fn())

    def _build_ui(self):
        outer = self.ctk.CTkFrame(self.root, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=28, pady=(22, 16))

        header = self.ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", pady=(0, 18))
        titles = self.ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        self.ctk.CTkLabel(titles, text="IQDraw Studio", font=self.font_title,
                          text_color=self.INK).pack(anchor="w")
        self.ctk.CTkLabel(
            titles,
            text="Design, check, and publish clear VEX IQ build instructions.",
            font=self.font_body, text_color=self.MUTED,
        ).pack(anchor="w", pady=(2, 0))
        self._secondary_button(
            header, "New build", self.new_build, width=105,
        ).pack(
            side="right", padx=(8, 0))
        self._primary_button(
            header, "Open build", self.choose_build, width=105,
        ).pack(
            side="right")

        source = self.ctk.CTkFrame(
            outer, fg_color=self.CARD, corner_radius=14,
            border_width=1, border_color=self.BORDER,
        )
        source.pack(fill="x", pady=(0, 14))
        self.ctk.CTkLabel(source, text="CURRENT BUILD", font=self.font_label,
                          text_color=self.MUTED).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        self.path_var = self.tk.StringVar(value="No build selected")
        self.ctk.CTkLabel(
            source, textvariable=self.path_var, font=self.font_body,
            text_color=self.INK, anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 14))
        self.reload_button = self._ghost_button(
            source, "Reload", self.reload, state="disabled")
        self.reload_button.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        self.edit_button = self._ghost_button(
            source, "Edit source", self.edit_source, state="disabled")
        self.edit_button.grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self.folder_button = self._ghost_button(
            source, "Show folder", self.open_source_folder, state="disabled")
        self.folder_button.grid(row=0, column=3, rowspan=2,
                                padx=(8, 18))
        source.columnconfigure(0, weight=1)

        status = self.ctk.CTkFrame(outer, fg_color="transparent")
        status.pack(fill="x", side="bottom", pady=(12, 0))
        self.status_var = self.tk.StringVar(value="Choose a build file to begin.")
        self.ctk.CTkLabel(
            status, textvariable=self.status_var, font=self.font_small,
            text_color=self.MUTED,
        ).pack(side="left")
        self.progress = self.ctk.CTkProgressBar(
            status, mode="indeterminate", width=155, height=8,
            progress_color=self.BLUE,
        )
        self.progress.set(0)

        body = self.ctk.CTkTabview(
            outer, fg_color="transparent", corner_radius=12,
            segmented_button_selected_color=self.BLUE,
            segmented_button_selected_hover_color=self.BLUE_DARK,
        )
        self.workspace_tabs = body
        body.pack(fill="both", expand=True)
        review_page = body.add("Review build")
        export_page = body.add("Create booklet")
        self._register_segmented_buttons(body)
        overview = self.ctk.CTkFrame(
            review_page, fg_color=self.CARD, corner_radius=14,
            border_width=1, border_color=self.BORDER,
        )
        settings = self.ctk.CTkFrame(
            export_page, fg_color=self.CARD, corner_radius=14,
            border_width=1, border_color=self.BORDER,
        )
        overview.pack(fill="both", expand=True, padx=2, pady=2)
        settings.pack(fill="both", expand=True, padx=2, pady=2)
        self._build_overview(overview)
        settings_body = self.ctk.CTkScrollableFrame(
            settings, fg_color="transparent", corner_radius=0,
        )
        self._build_settings(settings_body, settings)
        # Pack the pinned action footer (created by `_build_settings`) before
        # this expanding body so Tk always reserves the footer's full height.
        settings_body.pack(fill="both", expand=True, padx=1, pady=(1, 0))

    def _build_overview(self, parent):
        self.title_var = self.tk.StringVar(value="Build overview")
        self.subtitle_var = self.tk.StringVar(value="Steps and validation will appear here.")
        self.ctk.CTkLabel(
            parent, textvariable=self.title_var, font=self.font_heading,
            text_color=self.INK,
        ).pack(anchor="w", padx=20, pady=(18, 0))
        self.ctk.CTkLabel(
            parent, textvariable=self.subtitle_var, font=self.font_body,
            text_color=self.MUTED,
        ).pack(anchor="w", padx=20, pady=(2, 12))

        metrics = self.ctk.CTkFrame(parent, fg_color="transparent")
        metrics.pack(fill="x", padx=20, pady=(0, 11))
        self.metric_vars = []
        for col, name in enumerate(("STEPS", "PARTS", "PART TYPES")):
            metrics.grid_columnconfigure(col, weight=1)
            cell = self.ctk.CTkFrame(
                metrics, fg_color=self.CARD_ALT, corner_radius=10,
            )
            cell.grid(row=0, column=col, sticky="ew",
                      padx=(0 if col == 0 else 4, 0 if col == 2 else 4))
            var = self.tk.StringVar(value="—")
            self.metric_vars.append(var)
            self.ctk.CTkLabel(
                cell, textvariable=var, font=self.font_metric,
                text_color=self.INK,
            ).pack(anchor="w", padx=14, pady=(9, 0))
            self.ctk.CTkLabel(
                cell, text=name, font=self.font_small, text_color=self.MUTED,
            ).pack(anchor="w", padx=14, pady=(0, 9))

        self.tabs = self.ctk.CTkTabview(
            parent, fg_color="transparent", corner_radius=10,
            segmented_button_selected_color=self.BLUE,
            segmented_button_selected_hover_color=self.BLUE_DARK,
        )
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        steps_tab = self.tabs.add("Steps")
        inventory_tab = self.tabs.add("Parts")
        checks_tab = self.tabs.add("Checks")
        self._register_segmented_buttons(self.tabs)
        self.checks_tab_name = "Checks"
        self.steps_frame = self.ctk.CTkScrollableFrame(
            steps_tab, fg_color="transparent", corner_radius=0,
        )
        self.steps_frame.pack(fill="both", expand=True, padx=2, pady=2)
        self.inventory_frame = self.ctk.CTkScrollableFrame(
            inventory_tab, fg_color="transparent", corner_radius=0,
        )
        self.inventory_frame.pack(fill="both", expand=True, padx=2, pady=2)
        self.checks_text = self.ctk.CTkTextbox(
            checks_tab, wrap="word", fg_color=self.CARD_ALT,
            text_color=self.INK, corner_radius=10, border_width=0,
            font=self.font_body,
        )
        self.checks_text.pack(fill="both", expand=True, padx=2, pady=2)
        self._set_checks("Open a build to run its checks.")
        self._show_welcome()

    def _show_welcome(self):
        """Put a useful first action in the otherwise empty review panel."""
        self._clear_frame(self.steps_frame)
        card = self.ctk.CTkFrame(
            self.steps_frame, fg_color=self.CARD_ALT, corner_radius=12,
            border_width=1, border_color=self.BORDER,
        )
        card.pack(fill="x", pady=5)
        self.ctk.CTkLabel(
            card, text="Start with a build", font=self.font_heading,
            text_color=self.INK,
        ).pack(anchor="w", padx=18, pady=(16, 0))
        self.ctk.CTkLabel(
            card,
            text=("Open a Python build spec, create a starter, or explore a "
                  "worked example. IQDraw will review every step before you "
                  "create the booklet."),
            font=self.font_body, text_color=self.MUTED, justify="left",
            wraplength=560,
        ).pack(anchor="w", padx=18, pady=(4, 14))
        actions = self.ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 18))
        self._primary_button(
            actions, "Open build", self.choose_build, width=120,
        ).pack(side="left")
        self._secondary_button(
            actions, "New build", self.new_build, width=112,
        ).pack(side="left", padx=(8, 0))
        if self.examples:
            self._secondary_button(
                actions, "Try an example", self.open_example, width=126,
            ).pack(side="left", padx=(8, 0))

    def _build_settings(self, parent, actions_parent):
        self.ctk.CTkLabel(
            parent, text="Create booklet", font=self.font_heading,
            text_color=self.INK,
        ).pack(anchor="w", padx=20, pady=(18, 0))
        self.ctk.CTkLabel(
            parent, text="Choose the output and drawing options.",
            font=self.font_body, text_color=self.MUTED,
        ).pack(anchor="w", padx=20, pady=(2, 14))
        form = self.ctk.CTkFrame(parent, fg_color="transparent")
        form.pack(fill="x", padx=20)
        self.output_var = self.tk.StringVar()
        self._field_label(form, "Output HTML", 0, columnspan=2)
        output_row = self.ctk.CTkFrame(form, fg_color="transparent")
        output_row.grid(row=1, column=0, columnspan=2, sticky="ew",
                        pady=(4, 13))
        self.output_entry = self.ctk.CTkEntry(
            output_row, textvariable=self.output_var, height=35,
            fg_color=self.CARD_ALT, border_color=self.BORDER,
        )
        self.output_entry.pack(side="left", fill="x", expand=True)
        self._keyboard_entry(self.output_entry)
        self._ghost_button(
            output_row, "Choose…", self.choose_output, width=78,
        ).pack(side="left", padx=(7, 0))

        self.detail_var = self.tk.StringVar(
            value=_option_label(self.state.detail, DETAIL_OPTIONS))
        self._field_label(form, "Model geometry", 2, column=0)
        self.context_var = self.tk.StringVar(
            value=_option_label(self.state.context_detail, CONTEXT_OPTIONS))
        self._field_label(form, "Previously built parts", 2, column=1)
        detail = self.ctk.CTkOptionMenu(
            form, variable=self.detail_var, values=list(DETAIL_OPTIONS.values()),
            height=35, fg_color=self.CARD_ALT, button_color=self.BLUE,
            button_hover_color=self.BLUE_DARK, text_color=self.INK,
        )
        detail.grid(row=3, column=0, sticky="ew", padx=(0, 7), pady=(4, 4))
        self._keyboard_control(detail, detail._clicked)
        context = self.ctk.CTkOptionMenu(
            form, variable=self.context_var,
            values=list(CONTEXT_OPTIONS.values()), height=35,
            fg_color=self.CARD_ALT, button_color=self.BLUE,
            button_hover_color=self.BLUE_DARK, text_color=self.INK,
        )
        context.grid(row=3, column=1, sticky="ew", padx=(7, 0), pady=(4, 4))
        self._keyboard_control(context, context._clicked)
        cad_status = ("Local CAD model library detected."
                      if parts.HAS_CAD_MESHES else
                      "CAD is the default; parts without a local mesh use the "
                      "included precision model.")
        self.ctk.CTkLabel(
            form, text=cad_status, font=self.font_small,
            text_color=self.GREEN if parts.HAS_CAD_MESHES else self.MUTED,
            anchor="w", justify="left", wraplength=390,
        ).grid(row=4, column=0, sticky="ew", padx=(0, 7), pady=(0, 13))
        self.ctk.CTkLabel(
            form,
            text="Use procedural context to make large booklets smaller.",
            font=self.font_small, text_color=self.MUTED,
            anchor="w", justify="left", wraplength=390,
        ).grid(row=4, column=1, sticky="ew", padx=(7, 0), pady=(0, 13))

        self.ctk.CTkFrame(form, height=1, fg_color=self.BORDER).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(2, 11))
        self._field_label(form, "BOOKLET", 6, column=0)
        self._field_label(form, "EXTRA FILES", 6, column=1)

        self.hero_var = self.tk.BooleanVar(value=self.state.hero)
        self.check_var = self.tk.BooleanVar(value=self.state.checks)
        self.strict_var = self.tk.BooleanVar(value=self.state.strict)
        self.svg_var = self.tk.BooleanVar(value=self.state.export_svg)
        self.png_var = self.tk.BooleanVar(value=self.state.export_png)
        hero_check = self.ctk.CTkCheckBox(
            form, text="Include finished model on cover", variable=self.hero_var,
            font=self.font_body, checkbox_width=20, checkbox_height=20,
        )
        hero_check.grid(row=7, column=0, sticky="w", padx=(0, 7), pady=4)
        self._keyboard_control(hero_check, hero_check.toggle)
        checks = self.ctk.CTkCheckBox(
            form, text="Run build checks", variable=self.check_var,
            command=self._sync_strict, font=self.font_body,
            checkbox_width=20, checkbox_height=20,
        )
        checks.grid(row=8, column=0, sticky="w", padx=(0, 7), pady=4)
        self._keyboard_control(checks, checks.toggle)
        self.strict_check = self.ctk.CTkCheckBox(
            form, text="Stop if a check finds a problem",
            variable=self.strict_var, font=self.font_body,
            checkbox_width=20, checkbox_height=20,
        )
        self.strict_check.grid(row=9, column=0, sticky="w", padx=(0, 7), pady=4)
        self._keyboard_control(self.strict_check, self.strict_check.toggle)
        svg = self.ctk.CTkCheckBox(
            form, text="Also save one SVG per step", variable=self.svg_var,
            font=self.font_body, checkbox_width=20, checkbox_height=20,
        )
        svg.grid(row=7, column=1, sticky="w", padx=(7, 0), pady=4)
        self._keyboard_control(svg, svg.toggle)
        png = self.ctk.CTkCheckBox(
            form, text="Also save PNG step images", variable=self.png_var,
            font=self.font_body, checkbox_width=20, checkbox_height=20,
        )
        png.grid(row=8, column=1, sticky="w", padx=(7, 0), pady=4)
        self._keyboard_control(png, png.toggle)
        if not shutil.which("rsvg-convert"):
            self._set_control_state(png, "disabled")
            self.png_var.set(False)
        form.columnconfigure(0, weight=1, uniform="settings")
        form.columnconfigure(1, weight=1, uniform="settings")

        footer = self.ctk.CTkFrame(
            actions_parent, fg_color=self.CARD_ALT, corner_radius=0,
        )
        footer.pack(fill="x", side="bottom", padx=1, pady=(0, 1))
        self.generate_button = self._primary_button(
            footer, "Create booklet", self.generate, state="disabled",
        )
        self.generate_button.pack(fill="x", padx=18, pady=(12, 7))
        output_actions = self.ctk.CTkFrame(footer, fg_color="transparent")
        output_actions.pack(fill="x", padx=18, pady=(0, 12))
        self.open_button = self._secondary_button(
            output_actions, "Open latest booklet", self.open_output,
            state="disabled",
        )
        self.open_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.folder_output_button = self._secondary_button(
            output_actions, "Show output folder", self.open_output_folder,
            state="disabled",
        )
        self.folder_output_button.pack(
            side="left", fill="x", expand=True, padx=(4, 0))
        self._sync_strict()

    def _field_label(self, parent, text, row, column=0, columnspan=1):
        self.ctk.CTkLabel(
            parent, text=text, font=self.font_small, text_color=self.MUTED,
        ).grid(row=row, column=column, columnspan=columnspan, sticky="w")

    def _primary_button(self, parent, text, command, **kwargs):
        button = self.ctk.CTkButton(
            parent, text=text, command=command, height=40,
            corner_radius=9, fg_color=self.BLUE, hover_color=self.BLUE_DARK,
            font=self.font_body, **kwargs,
        )
        self._keyboard_control(button, button.invoke)
        return button

    def _secondary_button(self, parent, text, command, **kwargs):
        button = self.ctk.CTkButton(
            parent, text=text, command=command, height=40, corner_radius=9,
            fg_color=self.CARD, hover_color=self.CARD_ALT,
            border_width=1, border_color=self.BORDER, text_color=self.INK,
            font=self.font_body, **kwargs,
        )
        self._keyboard_control(button, button.invoke)
        return button

    def _ghost_button(self, parent, text, command, **kwargs):
        kwargs.setdefault("width", 88)
        button = self.ctk.CTkButton(
            parent, text=text, command=command, height=36,
            corner_radius=8, fg_color="transparent",
            hover_color=self.CARD_ALT, text_color=self.BLUE,
            font=self.font_small, **kwargs,
        )
        self._keyboard_control(button, button.invoke)
        return button

    def _keyboard_control(self, widget, activate):
        """Make a CustomTkinter canvas control reachable and usable by Tab."""
        canvas = getattr(widget, "_canvas", None)
        if canvas is None:
            return widget
        if getattr(widget, "_iqdraw_keyboard", False):
            return widget
        widget._iqdraw_keyboard = True
        # Tk canvas highlights are square, so keep the ring out of the way
        # until the control actually has focus.  That preserves CTk's rounded
        # silhouette while still making keyboard position unmistakable.
        enabled = str(widget.cget("state")) != "disabled"
        canvas.configure(takefocus=1 if enabled else 0, highlightthickness=0)

        def show_focus(_event):
            canvas.configure(
                highlightthickness=2,
                highlightbackground=self.FOCUS,
                highlightcolor=self.FOCUS,
            )

        def hide_focus(_event):
            canvas.configure(highlightthickness=0)

        def invoke(_event):
            if str(widget.cget("state")) != "disabled":
                activate()
            return "break"

        canvas.bind("<FocusIn>", show_focus, add="+")
        canvas.bind("<FocusOut>", hide_focus, add="+")
        canvas.bind("<Return>", invoke, add="+")
        canvas.bind("<space>", invoke, add="+")
        return widget

    @staticmethod
    def _set_control_state(widget, state):
        """Keep a CTk control's focusability in sync with its state."""
        widget.configure(state=state)
        canvas = getattr(widget, "_canvas", None)
        if canvas is not None and getattr(widget, "_iqdraw_keyboard", False):
            canvas.configure(takefocus=0 if state == "disabled" else 1)

    def _keyboard_entry(self, entry):
        """Give the native entry inside CTkEntry a visible focus state."""
        native = entry._entry
        native.configure(takefocus=1)
        native.bind(
            "<FocusIn>", lambda _event: entry.configure(border_color=self.FOCUS),
            add="+",
        )
        native.bind(
            "<FocusOut>", lambda _event: entry.configure(border_color=self.BORDER),
            add="+",
        )

    def _register_segmented_buttons(self, tabview):
        """Expose CustomTkinter's tab buttons to ordinary focus traversal."""
        segmented = getattr(tabview, "_segmented_button", None)
        for button in getattr(segmented, "_buttons_dict", {}).values():
            self._keyboard_control(button, button.invoke)

    def _sync_strict(self):
        state = "normal" if self.check_var.get() else "disabled"
        self._set_control_state(self.strict_check, state)

    def choose_build(self):
        if self._rendering:
            self.messagebox.showinfo(
                "Booklet is being created",
                "Wait for the current booklet to finish before opening another build.")
            return
        selected = self.filedialog.askopenfilename(
            title="Open an IQDraw build", filetypes=(("Python build", "*.py"), ("All files", "*")))
        if selected:
            self.open_path(pathlib.Path(selected))

    def open_path(self, path: pathlib.Path, trusted=False):
        if self._rendering:
            self.messagebox.showinfo(
                "Booklet is being created",
                "Wait for the current booklet to finish before opening another build.")
            return
        path = path.expanduser().resolve()
        if not path.is_file():
            self.messagebox.showerror(
                "Build not found", f"This file is no longer available:\n{path}")
            self.state.recent_files = [item for item in self.state.recent_files
                                       if item != str(path)]
            self._save_state()
            self._rebuild_file_menus()
            return
        if not trusted and not self._confirm_trusted(path):
            return
        self.load(path)

    def _confirm_trusted(self, path):
        if path in self.state.existing_recent_files():
            return True
        explanation = (
            "IQDraw build files are Python programs. They can do anything "
            "your Python account can do, so only open files you trust.\n\n"
            "IQDraw loads the file in a separate helper process for "
            "reliability, but that helper is not a security sandbox.\n\n"
            if not self.state.trust_notice_seen else
            "IQDraw build files are Python programs, so only open files you "
            "trust. The inspection helper is not a security sandbox.\n\n"
        )
        accepted = self.messagebox.askokcancel(
            "Open a trusted build",
            explanation + f"Open this file?\n{path}",
            icon="warning",
        )
        if accepted:
            self.state.trust_notice_seen = True
            self._save_state()
        return accepted

    def open_example(self):
        if not self.examples:
            self.messagebox.showinfo("Examples", "No bundled examples were found.")
            return
        dialog = self.ctk.CTkToplevel(self.root)
        dialog.title("Try an IQDraw example")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(fg_color=self.BG)
        dialog.geometry("470x430")
        frame = self.ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=22, pady=20)
        self.ctk.CTkLabel(
            frame, text="Choose a worked example", font=self.font_heading,
            text_color=self.INK,
        ).pack(anchor="w")
        self.ctk.CTkLabel(
            frame, text="Examples progress from a small frame to a full robot.",
            font=self.font_body, text_color=self.MUTED,
        ).pack(anchor="w", pady=(3, 12))
        choices = self.ctk.CTkScrollableFrame(
            frame, fg_color=self.CARD, corner_radius=12,
            border_width=1, border_color=self.BORDER,
        )
        choices.pack(fill="both", expand=True)

        def selected(path):
            dialog.destroy()
            self.open_path(path, trusted=True)

        for path in self.examples:
            self.ctk.CTkButton(
                choices, text=path.stem.replace("-", " ").title(),
                command=lambda item=path: selected(item), anchor="w",
                height=42, corner_radius=8, fg_color="transparent",
                hover_color=self.CARD_ALT, text_color=self.INK,
                font=self.font_body,
            ).pack(fill="x", padx=5, pady=3)
        self._secondary_button(
            frame, "Cancel", dialog.destroy,
        ).pack(anchor="e", pady=(12, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        dialog.focus_set()

    def new_build(self):
        if self._rendering:
            self.messagebox.showinfo(
                "Booklet is being created",
                "Wait for the current booklet to finish before creating another build.")
            return
        selected = self.filedialog.asksaveasfilename(
            title="Create a new IQDraw build", defaultextension=".py",
            filetypes=(("Python build", "*.py"),), initialfile="my-build.py")
        if not selected:
            return
        path = pathlib.Path(selected)
        dialog = self.ctk.CTkInputDialog(
            title="Build title",
            text="What are you building?\n\n"
                 f"Suggested: {path.stem.replace('-', ' ').title()}",
        )
        title = dialog.get_input()
        if title is None:
            return
        if not title.strip():
            title = path.stem.replace("-", " ").title()
        try:
            create_starter(path, title)
        except FileExistsError:
            self.messagebox.showerror("File already exists", f"Nothing was changed:\n{path}")
            return
        except OSError as exc:
            self.messagebox.showerror("Build couldn't be created", str(exc))
            return
        self.load(path)
        self.edit_source()

    def load(self, path: pathlib.Path):
        self.spec_path = path.resolve()
        self._inspection_serial = getattr(self, "_inspection_serial", 0) + 1
        self.path_var.set(str(self.spec_path))
        self.output_var.set(str(self.spec_path.with_suffix(".html")))
        self._set_control_state(self.reload_button, "normal")
        self._set_control_state(self.edit_button, "normal")
        self._set_control_state(self.folder_button, "normal")
        self._set_control_state(self.generate_button, "disabled")
        self.title_var.set(
            f"Reading {self.spec_path.stem.replace('-', ' ').title()}…")
        self.subtitle_var.set("Inspecting steps, inventory, and build checks.")
        for var in self.metric_vars:
            var.set("…")
        self._clear_frame(self.steps_frame)
        self.ctk.CTkLabel(
            self.steps_frame, text="Reading build…", font=self.font_body,
            text_color=self.MUTED,
        ).pack(anchor="w", padx=8, pady=12)
        self._busy("Reading build and running checks…")
        threading.Thread(target=self._inspect_worker,
                         args=(self.spec_path, self._inspection_serial),
                         daemon=True).start()

    def reload(self):
        if self.spec_path:
            self.load(self.spec_path)

    def _inspect_worker(self, path, serial):
        try:
            result = subprocess.run(
                inspection_command(path), capture_output=True, text=True,
                cwd=str(path.parent), timeout=30,
            )
            if result.returncode:
                message = (result.stderr or result.stdout or
                           "The inspection helper stopped unexpectedly.").strip()
                self._events.put(("inspect_error", serial, message))
                return
            self._events.put(("inspected", serial, json.loads(result.stdout)))
        except subprocess.TimeoutExpired:
            self._events.put((
                "inspect_error", serial,
                "The build took longer than 30 seconds to inspect. Check its "
                "top-level code for long-running work, then reload it.",
            ))
        except (OSError, ValueError) as exc:
            self._events.put(("inspect_error", serial,
                              str(exc) or exc.__class__.__name__))

    def _show_summary(self, summary):
        self.title_var.set(summary["title"])
        self.subtitle_var.set(summary["subtitle"] or "IQDraw build")
        for var, value in zip(self.metric_vars,
                              (summary["steps"], summary["parts"], summary["part_types"])):
            var.set(str(value))
        self._clear_frame(self.steps_frame)
        for number, section, note, count in summary["step_rows"]:
            self._add_step_row(number, section, note, count)
        self._clear_frame(self.inventory_frame)
        for label, qty in summary["inventory"]:
            self._add_inventory_row(label, qty)
        problems = summary["problems"]
        if problems:
            self._set_checks(f"{len(problems)} item(s) need attention:\n\n" +
                             "\n\n".join(problems))
            self._rename_checks_tab(f"Checks ({len(problems)})")
        else:
            self._set_checks("✓ No problems found. This build is ready to render.")
            self._rename_checks_tab("Checks ✓")
        if self.spec_path:
            try:
                self._loaded_mtime = self.spec_path.stat().st_mtime
            except OSError:
                self._loaded_mtime = None
            self.state.remember(self.spec_path)
            self._capture_preferences()
            self._save_state()
            self._rebuild_file_menus()
        self._set_control_state(self.generate_button, "normal")
        detail = _option_value(self.detail_var.get(), DETAIL_OPTIONS)
        geometry = ("CAD models selected" if detail == "cad"
                    else "Procedural models selected")
        self._idle(
            f"Ready · {summary['steps']} steps · {summary['parts']} parts · {geometry}")

    def _set_checks(self, message):
        self.checks_text.configure(state="normal")
        self.checks_text.delete("1.0", "end")
        self.checks_text.insert("1.0", message)
        self.checks_text.configure(state="disabled")

    @staticmethod
    def _clear_frame(frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def _add_step_row(self, number, section, note, count):
        row = self.ctk.CTkFrame(
            self.steps_frame, fg_color=self.CARD_ALT, corner_radius=9,
        )
        row.pack(fill="x", pady=4)
        badge = self.ctk.CTkLabel(
            row, text=str(number), width=34, height=34, corner_radius=17,
            fg_color=self.BLUE, text_color="white", font=self.font_label,
        )
        badge.pack(side="left", padx=(10, 9), pady=9)
        copy = self.ctk.CTkFrame(row, fg_color="transparent")
        copy.pack(side="left", fill="x", expand=True, pady=7)
        self.ctk.CTkLabel(
            copy, text=section.upper(), font=self.font_small,
            text_color=self.MUTED, anchor="w",
        ).pack(fill="x")
        self.ctk.CTkLabel(
            copy, text=note, font=self.font_body, text_color=self.INK,
            anchor="w", justify="left", wraplength=430,
        ).pack(fill="x", pady=(1, 0))
        self.ctk.CTkLabel(
            row, text=f"+{count}", width=44, font=self.font_label,
            text_color=self.MUTED,
        ).pack(side="right", padx=10)

    def _add_inventory_row(self, label, qty):
        row = self.ctk.CTkFrame(
            self.inventory_frame, fg_color=self.CARD_ALT, corner_radius=9,
        )
        row.pack(fill="x", pady=4)
        self.ctk.CTkLabel(
            row, text=label, font=self.font_body, text_color=self.INK,
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=13, pady=10)
        self.ctk.CTkLabel(
            row, text=f"{qty}×", font=self.font_label, text_color=self.BLUE,
        ).pack(side="right", padx=13)

    def _rename_checks_tab(self, name):
        if name == self.checks_tab_name:
            return
        self.tabs.rename(self.checks_tab_name, name)
        self.checks_tab_name = name
        self._register_segmented_buttons(self.tabs)

    def choose_output(self):
        initial = pathlib.Path(self.output_var.get()) if self.output_var.get() else None
        selected = self.filedialog.asksaveasfilename(
            title="Save instruction booklet", defaultextension=".html",
            filetypes=(("Web booklet", "*.html"),),
            initialdir=str(initial.parent) if initial else None,
            initialfile=initial.name if initial else "instructions.html")
        if selected:
            self.output_var.set(selected)

    def _settings(self):
        if not self.spec_path:
            raise ValueError("Choose a build file first.")
        output_text = self.output_var.get().strip()
        if not output_text:
            raise ValueError("Choose where to save the booklet.")
        output = pathlib.Path(output_text).expanduser()
        if output.suffix.lower() not in (".html", ".htm"):
            output = output.with_suffix(".html")
            self.output_var.set(str(output))
        try:
            source_mtime_ns = self.spec_path.stat().st_mtime_ns
        except OSError as exc:
            raise ValueError(f"The build source is no longer available: {exc}") from exc
        return RenderSettings(self.spec_path, output.resolve(),
                              _option_value(self.detail_var.get(), DETAIL_OPTIONS),
                              _option_value(self.context_var.get(), CONTEXT_OPTIONS),
                              self.hero_var.get(), self.check_var.get(),
                              self.strict_var.get(),
                              (output.resolve().parent / f"{output.stem}-steps"
                               if self.svg_var.get() or self.png_var.get() else None),
                              self.png_var.get(), source_mtime_ns)

    def generate(self):
        if self._working or self._rendering:
            return
        try:
            settings = self._settings()
        except ValueError as exc:
            self.messagebox.showerror("Can't generate booklet", str(exc))
            return
        self._capture_preferences()
        self._save_state()
        try:
            settings.output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.messagebox.showerror("Can't create output folder", str(exc))
            return
        self._set_control_state(self.generate_button, "disabled")
        self._set_control_state(self.open_button, "disabled")
        self._rendering = True
        self._busy("Drawing the booklet… Larger builds may take a moment.")
        threading.Thread(target=self._render_worker, args=(settings,), daemon=True).start()

    def _render_worker(self, settings):
        try:
            result = subprocess.run(render_command(settings), capture_output=True, text=True,
                                    cwd=str(settings.spec.parent))
            self._events.put(("rendered", settings, result))
        except OSError as exc:
            self._events.put(("render_error", settings, str(exc)))

    def _poll_events(self):
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "inspected" and event[1] == self._inspection_serial:
                    self._show_summary(event[2])
                elif kind == "inspect_error" and event[1] == self._inspection_serial:
                    self.title_var.set("Build couldn't be opened")
                    self.subtitle_var.set("Fix the source issue, then reload the build.")
                    for var in self.metric_vars:
                        var.set("—")
                    self._clear_frame(self.steps_frame)
                    self.ctk.CTkLabel(
                        self.steps_frame,
                        text="The source could not be inspected. Use Edit source, "
                             "fix the reported issue, then reload.",
                        font=self.font_body, text_color=self.MUTED,
                        justify="left", wraplength=560,
                    ).pack(anchor="w", padx=8, pady=12)
                    self._idle("Could not read this build.")
                    self.messagebox.showerror("Build couldn't be opened", event[2])
                elif kind == "rendered":
                    self._render_done(event[1], event[2])
                elif kind == "render_error":
                    self._rendering = False
                    self._set_control_state(self.generate_button, "normal")
                    self._idle("Booklet generation failed.")
                    self.messagebox.showerror("Booklet couldn't be created", event[2])
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _render_done(self, settings, result):
        self._rendering = False
        self._set_control_state(self.generate_button, "normal")
        if result.returncode:
            self._idle("Booklet generation failed.")
            message = (result.stderr or result.stdout or "Unknown rendering error").strip()
            self.messagebox.showerror("Booklet couldn't be created", message)
            return
        self._set_control_state(self.open_button, "normal")
        self._set_control_state(self.folder_output_button, "normal")
        if not source_is_current(settings):
            self._idle("Booklet created from an older version of the source.")
            self.messagebox.showwarning(
                "Source changed while drawing",
                "The build source changed while IQDraw was creating the "
                "booklet, so the output may be out of date. Studio will "
                "reload the latest source now; create the booklet again "
                "after the checks finish.",
            )
            self.load(settings.spec)
            return
        self._idle((result.stdout or f"Created {settings.output}").strip())
        warnings = result.stderr.strip()
        if warnings:
            self.messagebox.showwarning("Booklet created with check results", warnings)
        else:
            try:
                _open_in_system(settings.output)
            except OSError as exc:
                self.messagebox.showerror("Can't open booklet", str(exc))

    def open_output(self):
        try:
            output = pathlib.Path(self.output_var.get())
            if not output.exists():
                raise FileNotFoundError(output)
            _open_in_system(output)
        except (OSError, FileNotFoundError) as exc:
            self.messagebox.showerror("Can't open booklet", str(exc))

    def edit_source(self):
        if not self.spec_path:
            return
        try:
            _open_in_system(self.spec_path)
        except OSError as exc:
            self.messagebox.showerror("Can't open source", str(exc))

    def open_source_folder(self):
        if self.spec_path:
            self._open_folder(self.spec_path.parent)

    def open_output_folder(self):
        text = self.output_var.get().strip()
        if text:
            self._open_folder(pathlib.Path(text).expanduser().resolve().parent)

    def _open_folder(self, path):
        try:
            if not path.is_dir():
                raise FileNotFoundError(path)
            _open_in_system(path)
        except (OSError, FileNotFoundError) as exc:
            self.messagebox.showerror("Can't open folder", str(exc))

    def clear_recent(self):
        self.state.recent_files = []
        self._save_state()
        self._rebuild_file_menus()

    def _capture_preferences(self):
        if not hasattr(self, "detail_var"):
            return
        self.state.detail = _option_value(self.detail_var.get(), DETAIL_OPTIONS)
        self.state.context_detail = _option_value(
            self.context_var.get(), CONTEXT_OPTIONS)
        self.state.hero = self.hero_var.get()
        self.state.checks = self.check_var.get()
        self.state.strict = self.strict_var.get()
        self.state.export_svg = self.svg_var.get()
        self.state.export_png = self.png_var.get()

    def _save_state(self):
        try:
            save_state(self._state_path, self.state)
        except OSError:
            # Preferences should never stop somebody from opening or drawing.
            pass

    def _check_source_changed(self, _event=None):
        if self._working or not self.spec_path or self._loaded_mtime is None:
            return
        try:
            changed = self.spec_path.stat().st_mtime != self._loaded_mtime
        except OSError:
            return
        if changed:
            self.load(self.spec_path)

    def show_getting_started(self):
        self.messagebox.showinfo(
            "Getting started with IQDraw",
            "1. Choose Try an example to see a finished build.\n\n"
            "2. Choose New build to create your own short Python spec.\n\n"
            "3. Edit the steps, then return to IQDraw Studio. The app reloads "
            "when the source changes.\n\n"
            "4. Review Steps, Parts, and Checks. Choose Create booklet to "
            "create a printable, offline HTML guide.\n\n"
            "Tip: CAD models are the default. If a local CAD mesh is not "
            "available for a part, IQDraw automatically uses its included "
            "precision model.",
        )

    def show_about(self):
        self.messagebox.showinfo(
            "About IQDraw Studio",
            "IQDraw Studio\n\n"
            "Printable VEX IQ (2nd generation) build instructions from a small "
            "Python specification.\n\n"
            "Works offline. Generated booklets are self-contained HTML files.",
        )

    def close(self):
        self._capture_preferences()
        self._save_state()
        self.root.destroy()

    def _busy(self, message):
        self._working = True
        self.status_var.set(message)
        if not self.progress.winfo_manager():
            self.progress.pack(side="right")
        self.progress.start()

    def _idle(self, message):
        self._working = False
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set(message)


def main(argv=None):
    """Launch IQDraw Studio, optionally opening a spec passed by path."""
    ctk, _, _, _ = _tk()
    root = ctk.CTk()
    app = IQDrawApp(root)
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        app.open_path(pathlib.Path(args[0]))
    root.mainloop()


if __name__ == "__main__":
    main()
