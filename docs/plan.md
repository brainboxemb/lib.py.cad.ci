# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.9.1` is released at exact commit
`8403c426776dbad5beb17c35674562dc916e9a1f`.

0.9.1 adds generic named complete build scopes and named Pages subtrees.
`tool.cad.ci 0.16.0` consumes that release and is now under external
acceptance in `tool.cad.ci.test` #60.

That black-box acceptance exposed one release blocker unrelated to the named
scope mechanics: current SCons output writes `engine_schema = 2`, while
`build_store.py` still validates new candidate evidence against schema 1.
Fresh output is therefore rejected before durable publication.

## Current goal

Complete #74 and release a patch that makes durable build-store validation
accept the current SCons engine schema actually produced by this library.

Do not change named-scope behavior in this patch.

## Required proof

- current SCons item evidence uses engine schema 2;
- build-store candidate validation expects engine schema 2;
- test fixtures no longer mask the mismatch with hand-written schema 1;
- a regression test proves real current item evidence can be prepared into a
  durable scope;
- all existing main, named and PR publication tests remain green.

## Execution order

1. [#74, now] Align build-store validation/tests with SCons engine schema 2.
2. [#74] Release the exact green patch revision.
3. [tool.cad.ci] Repin the patch release without adding tool behavior.
4. [tool.cad.ci.test #60] Rerun the complete released-stack acceptance.
5. [Forge #572] Continue the development-lane migration only after acceptance is green.

## Open issue assessment — 2026-11-21

| Issue | Status | Assessment |
| --- | --- | --- |
| #74 Align durable build-store validation with SCons engine schema 2 | now | Release blocker found by external acceptance; current library rejects its own fresh evidence. |
| #71 Reduce fixed selective-run startup overhead before first SCons target | later | Independent performance work; do not mix with the schema compatibility patch. |

Immediate chain:

`#74 patch -> tool repin -> acceptance #60 -> Forge #572`.
