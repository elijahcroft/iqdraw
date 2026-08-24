# IQDraw roadmap

IQDraw's goal is to let a teacher turn a build idea into clear, accessible,
printable instructions without needing CAD expertise or a web service.

## Now: trustworthy public foundation

- Keep the repository self-contained: package, tests, and worked examples.
- Ship only original procedural geometry under the MIT license.
- Test supported Python versions and render a real example in GitHub Actions.
- Give first-time users a safe `iqdraw --new` starting point.
- Document contribution rules and provide focused bug and part requests.

## Next: make authoring easier

- Continue the desktop work in [`STUDIO_PLAN.md`](STUDIO_PLAN.md), with
  explicit low-risk delegation lanes and close-review core projects.
- Add `iqdraw parts` with a generated visual catalogue and searchable names.
- Add a browser-based coordinate inspector for placing and rotating a part.
- Report inventory against common classroom kits and flag missing quantities.
- Add an author checklist and a small tutorial build that takes under 10 minutes.
- Publish example output through GitHub Pages so teachers can evaluate IQDraw
  before installing it.

## Later: lesson-production workflow

- Add reusable title-page themes and school branding without changing specs.
- Export structured build data for lesson-plan and handout generators.
- Support translations while keeping part names and coordinates stable.
- Add snapshot-based visual regression tests for the procedural catalogue.
- Explore a data format or guided editor for teachers who do not use Python.

## Guardrails

- Generated booklets must work offline, print cleanly, and remain readable
  without color.
- New checks must avoid false positives on valid builds.
- Competition examples must reinforce student iteration rather than present a
  competition robot to copy unchanged.
- Third-party trademarks and geometry remain the property of their owners.
