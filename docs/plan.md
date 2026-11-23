# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted baseline

- `lib.py.cad.ci v0.17.0` is immutable at
  `a68bcd9e3940b21872dea5fc210bcd9a26519ebc`;
- `tool.cad.ci v0.33.0` is immutable at
  `b496c35d672227c0b143493b6b7202ea262cc857` and pins that exact library;
- `lib.py.cad.verification v0.16.0` is immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external acceptance #240 correctly exposed one remaining runtime-owner bug
  before Forge adoption.

## Current work

### #114 — runtime-owned build123d interpreter batch

**Now / release blocker for #106 and acceptance #240.**

The immutable `cad-reference:v0.3.4` runtime intentionally isolates build123d
under `/opt/build123d/bin/python`. v0.17.0 incorrectly imports build123d from
the runtime's main Python.

Fix the owner layer without weakening batching:

1. declare the runtime-owned interpreter in built-in builder metadata;
2. execute all active build123d rows in one child engine process inside the
   existing shared reference container;
3. keep CadQuery in the main runtime Python;
4. keep verification in the main runtime after successful export;
5. retain complete per-model failure observability;
6. prove one child process for N build123d rows with cheap fake-process tests;
7. publish a patch release and repin the thin tool;
8. rerun external acceptance #240 against the immutable patch stack.

Evidence: tool.cad.ci.test PR #241 / Actions run `45183478157`.

### #106 — extract reusable batched CAD builders from Forge

**Blocked on #114 patch release + #240 acceptance.**

Once the released generic runtime boundary passes real acceptance, migrate Forge
away from duplicated reference batch/package wiring.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #114 Run build123d built-in batches through the runtime-owned interpreter | **now** | Implement, release patch, repin tool, rerun #240. |
| #106 Extract reusable batched CAD builders from Forge | **blocked by #114/#240** | Resume Forge migration after external acceptance. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- one compatible N-model build+verification batch means one Docker runtime
  start;
- an isolated engine may add at most one process per active engine/interpreter
  group, never per model;
- current/cache results avoid Docker and engine-process startup entirely;
- no second planner/cache/runtime scheduler is introduced;
- normal CI uses structural process-count tests; real runtime compatibility
  stays in `tool.cad.ci.test`.
