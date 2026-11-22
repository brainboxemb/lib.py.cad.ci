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

Issue #91 is active: separate declarative item configuration from builder
implementation while keeping the existing SCons execution engine.

Current branch: `issue/91-builder-boundary`.

Target:
- root `cad-ci.yml` may map builder names to repository directories;
- item `ci.yml` selects a builder and contains no command implementation;
- `builder.yml` owns executable steps;
- builder changes select/rebuild every using item;
- legacy inline steps remain readable during migration.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #91 Separate declarative item configuration from builder implementation | **active** | Implement, unit-test, release, then expose through tool.cad.ci and external acceptance. |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state.
