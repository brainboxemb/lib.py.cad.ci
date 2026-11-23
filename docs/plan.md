# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Release candidate baseline

- configurable durable output-branch behavior from #98 is merged on `main` at
  `998f6ed6f414575a2eefdd4b967e6f2800a1735c`;
- PR #99 library CI passed against the installed wheel;
- the candidate preserves `build` / `gh-pages` defaults and allows alternate
  generated refs such as `test-output/build` and
  `test-output/gh-pages`;
- `tool.cad.ci` #147 remains blocked until this exact library behavior is
  released.

## Current work

### #100 — release 0.14.0

**Now.** Publish the merged #98 contract as exact `lib.py.cad.ci 0.14.0`.
The normal main release workflow must create `v0.14.0` only from the exact
main commit containing the VERSION/pyproject/changelog declaration.

After release, verify the tag target and let `tool.cad.ci` #147 consume only
that exact released commit.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #100 Release 0.14.0 configurable durable output branches | **now** | Merge release declaration after CI; verify exact published release. |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state.
