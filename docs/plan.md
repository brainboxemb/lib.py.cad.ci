# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-22).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Released and accepted baseline

- `lib.py.cad.ci 0.12.0` @
  `64656db8df528a5c0de799e62c0f028fd0133486`;
- main CI/release run `45062701636` succeeded;
- `tool.cad.ci v0.25.0` consumes this exact library release at
  `92b9cbb59bf24f6b47ba1fae267f67f2becc503f`;
- external released-stack acceptance run `45063617081` succeeded in
  `tool.cad.ci.test` PR #135, including two items sharing one builder while
  both item `ci.yml` files remain declarative.

Issue #91 is complete. Root `cad-ci.yml` may name repository-owned builders,
item `ci.yml` selects a builder, and `builder.yml` owns executable steps.
Builder changes participate in selection and SCons signatures. Legacy inline
steps remain available only as the migration compatibility path.

Issue #87 previously moved durable complete-scope validation/state/publication
composition out of `tool.cad.ci` and back into this library. The library
remains the single source of truth for generic CAD-CI state and execution
semantics.

## Current work

### #94 — config-owned durable lane integration

**Now.** Add optional root Pages-source configuration and one high-level
main/named complete-scope integration API. This is the generic owner-layer
blocker for the action-free durable workflow in tool.cad.ci #137 and consumer
migrations in CAD #288 / Forge #740.

Keep GitHub Actions and domain site generators out of this library.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #94 Config-owned durable Pages/lane integration | **now** | Define config semantics, implement/test library composition, release. |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state.
