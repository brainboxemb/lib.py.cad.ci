# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-22).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Release candidate baseline

- durable publication/config implementation from #94 is merged on `main` at
  `3b6234a49bdaeff220c0903bc072f18e962ef1e6`;
- PR #95 library CI passed in run `45065937583`;
- release #96 declares `lib.py.cad.ci 0.13.0`;
- the released 0.13.0 commit becomes the required exact pin for
  `tool.cad.ci` #137;
- only after tool release and external acceptance in
  `tool.cad.ci.test` #141 may CAD #288 / Forge #740 adopt the new lifecycle.

## Current work

### #96 — release 0.13.0

**Now.** Publish the merged #94 contract as an exact tested library release.
The normal main release workflow must create `v0.13.0` only from the exact
main commit that contains the VERSION/pyproject/changelog bump.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #96 Release 0.13.0 durable publication contract | **now** | Merge release declaration after CI; verify exact published release. |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state.
