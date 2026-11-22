# Repository plan

This file is the current source of truth for unfinished work in `lib.py.cad.ci`.

The repository owns generic CAD-CI planning/execution, durable build-store,
Pages and generated-branch publication semantics. Tool/workflow repositories
adapt these APIs; they do not reimplement them.

## Current released baseline

`lib.py.cad.ci 0.11.0` is released at exact commit
`e621daf6e309bdd0e3f643a12007f1b66490696d`.

The currently accepted released stack remains unchanged while issue #87 is
developed. Consumers must not pin this branch.

## Current work

### #87 — durable complete-scope API

Repository-wide audit of `tool.cad.ci` found duplicated generic durable-scope
logic in its workflow helper. The duplicate validator has already diverged from
this library: this library reserves complete scope `pr`, while the tool copy
did not.

Work order:

1. Define durable scope state/resolution requirements and design here.
2. Implement `cad_ci.durable` by composing existing planner/build-store/Git
   publication functions; no new storage or execution engine.
3. Unit-test missing/existing main/named scopes, validation, provenance,
   selection and publication delegation.
4. Release the library only after its CI is green.
5. Update `tool.cad.ci` to the exact library release and remove its duplicate
   validator/manifest/parser/publication orchestration.
6. Re-run `tool.cad.ci.test` before any Forge/CAD repin.

## Open issue assessment — 2026-11-22

| Issue | Status | Next |
| --- | --- | --- |
| #87 Move durable complete-scope semantics out of tool.cad.ci | **now** | Library API + tests, then thin the tool. |

## Non-goals

- no changed-path planner beyond the existing selector;
- no new scheduler or freshness engine;
- no new durable manifest schema;
- no GitHub-specific concepts in the library;
- no domain-specific Forge/CAD behavior.
