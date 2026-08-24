# IQDraw Studio development plan

This plan keeps the desktop app easy to extend without letting a broad change
quietly destabilize the renderer. The lanes are about blast radius, not about
which tool is "smart": small, mechanically verifiable tasks are safe to hand
to a lower-trust coding agent; behavior that can change builds or output stays
under close review.

## Product promise

A teacher should be able to install IQDraw, open a worked example, create a
first build, understand every check, and print a booklet without learning the
CLI. The GUI must remain offline-capable and must never fork the renderer into
a second implementation.

## Shipped foundation

- Modern, system-aware CustomTkinter desktop app with a guided new-build flow.
- Step, inventory, and check review before rendering.
- Recent projects, bundled examples, persistent render preferences, menus,
  keyboard shortcuts, source auto-reload, and output-folder access.
- HTML, per-step SVG, and optional PNG output through the existing CLI.
- Build inspection in a disposable helper process. This protects GUI state,
  but is explicitly not presented as a security sandbox.
- Corruption-tolerant, atomic per-user preference storage.

## Lane A: safe delegated tasks

These are suitable for PC or another lower-trust coding agent. Give it **one
task at a time**, keep the named file boundary, and require the stated check.

### A1. GUI copy and accessibility review

- Allowed files: `gui.py`, `README.md`, `tests/test_gui.py`.
- Scope: improve labels, access keys, focus order, and help text only.
- Do not change subprocess commands, spec loading, rendering, or persistence.
- Acceptance: `./run-tests.sh test_gui` passes and every control remains
  reachable by keyboard.

### A2. More clean example builds

- Allowed files: one new file under `examples/` and matching example tests.
- Scope: a 5–10 step original build using parts that already exist.
- Do not add geometry, checks, dependencies, copied competition designs, or
  third-party CAD.
- Acceptance: the new example is check-clean and renders at simple detail.

### A3. Documentation screenshots and walkthrough

- Allowed files: `README.md`, `docs/` assets, and documentation links only.
- Scope: a short install-to-first-booklet walkthrough and current screenshots.
- Do not edit Python or commit generated booklets.
- Acceptance: every command is run from a fresh checkout and every linked file
  exists with case-correct paths.

### A4. Preference edge-case tests

- Allowed files: `tests/test_gui.py` only.
- Scope: malformed JSON shapes, missing recent files, recent-file limit, and
  platform config-path cases.
- Do not weaken assertions or modify production code.
- Acceptance: new tests fail against a deliberately broken helper and pass on
  the current implementation.

### A5. Packaging metadata audit

- Allowed files: `pyproject.toml`, `README.md`, and a written audit report.
- Scope: classifiers, entry-point documentation, wheel-content verification.
- Do not add dependencies or release/upload anything.
- Acceptance: build both sdist and wheel in a temporary directory, inspect
  their file lists, and report results; a maintainer reviews before merge.

## Lane B: close-review core work

These changes cross process, data, rendering, or distribution boundaries and
should remain with the primary GPT workflow plus full review.

### B1. In-app visual step preview

Design a preview protocol that renders selected steps on demand without
requiring a second SVG renderer. Prefer converting the existing SVG through an
optional, clearly detected adapter. It needs cancellation, stale-result
suppression, bounded caching, and a useful fallback when the adapter is absent.

### B2. Guided non-code authoring

Prototype a structured editor for steps and placements. The hard requirement
is round-tripping: it may generate a new spec, but it must never silently
rewrite an arbitrary Python spec containing loops, imports, or assemblies.
Start with a separate `.iqdraw.json` format and explicit import/export rather
than pretending all Python can be edited as a form.

### B3. Installers and signed releases

Add CI-built Windows and macOS desktop artifacts, versioned release notes,
checksums, and a reproducible smoke test. Keep the ordinary Python package as
the source of truth. Code signing, release credentials, and uploads require a
human-controlled release step.

### B4. Cooperative cancellation and progress

Replace the indeterminate render worker with a small machine-readable CLI
progress protocol. Preserve normal human-readable CLI output, terminate child
processes cleanly on app exit, and test cancellation without leaving partial
booklets presented as successful output.

### B5. Trust boundary research

Document realistic options for opening untrusted specs. A helper process alone
is not a sandbox. Compare OS sandboxing, a declarative input format, and an
explicit trusted-project model before promising security in the UI.

## Delegation contract

When handing out a Lane A card:

1. Create a dedicated branch and quote the card verbatim in the task.
2. State the exact allowed files. Reject edits outside them.
3. Require the focused test and `git diff --check` in the handoff.
4. Do not let the delegated task add packages, modify renderer geometry, change
   CLI semantics, delete tests, commit generated output, or publish anything.
5. Review the diff; never merge based only on the agent's summary.
6. Run the full suite after combining multiple small tasks.

## Recommended order

1. Delegate A4 and A3 independently; they improve confidence and onboarding
   without touching behavior.
2. Keep B1 with the primary workflow; a real preview is the highest-value next
   product feature.
3. Delegate A2 after choosing the educational concept for the example.
4. Take B4 before shipping installers so desktop users can cancel large jobs.
5. Research B5 before marketing the app as safe for downloaded build files.
