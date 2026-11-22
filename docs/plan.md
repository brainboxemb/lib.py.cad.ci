# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-22).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Released and accepted baseline

- `lib.py.cad.ci 0.11.1` @
  `fa6bf244381dde609a0b04de673d774911c52fea`.
- Main CI/release run `45044386866` succeeded.
- `tool.cad.ci 0.21.0` consumes this exact release at
  `b1474f6be66dc0236f2a5c2555af07a100447255`.
- External released-stack acceptance run `45045346481` succeeded.

Issue #87 moved durable complete-scope validation/state/publication composition
out of `tool.cad.ci` and back into this library. The library is again the
single source of truth for that generic state.

## Current work

No generic CAD-CI implementation is active. The repository is back in
demand-driven mode.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state.
