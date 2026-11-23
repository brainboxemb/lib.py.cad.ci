# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Released and accepted baseline

- current released library: `lib.py.cad.ci 0.14.0` @
  `b24e9a3826dfc07e07b4f3fd9971fcb4ab5aa12d`;
- `tool.cad.ci v0.31.0` @
  `27bdf67077ddd485cea95ba199069249c20c2a46` pins that exact release;
- `tool.cad.ci.test` #223 externally accepted that stack;
- #102 post-build Pages renderer implementation is merged on `main` at
  `be84fc67e5bc8ba09b79a5f75d6999cb3315199e`; implementation PR #103 and
  the post-merge built-wheel CI are green.

## Current work

### #104 — release 0.15.0

**Now.** Publish the merged #102 contract as exact `lib.py.cad.ci 0.15.0`.

The release declaration changes only version/changelog/plan metadata. The normal
main release workflow must publish `v0.15.0` from the exact tested main commit.

After release:

1. verify the exact release/tag target;
2. update/release `tool.cad.ci` against that exact library;
3. black-box qualify the resulting tool in `tool.cad.ci.test`;
4. only then resume Forge #740.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #104 Release 0.15.0 post-build Pages renderer | **now** | Merge release declaration, verify exact v0.15.0 publication. |
| #89 Align historical changelog | **later / docs-only** | Apply shared changelog presentation without runtime/API changes. |

## Non-goals

- no runtime behavior change in the release declaration;
- no tool/consumer migration before exact release verification;
- no second scheduler/SCons graph/cache/reuse engine;
- no consumer/domain-specific publication logic.
