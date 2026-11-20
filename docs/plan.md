# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.4` is released at exact commit
`4e033fd17e911b3feb92b1a34433b884ca788ab6`.

The current SCons engine is correct but explicitly serial in practice:
`run_scons()` invokes SCons without a job count, so independent targets execute
one at a time.

A real selective Forge batch proved selection correctness but exposed the
scaling cost:

- 10 model items;
- 40 independent reference child items;
- no unrelated items;
- ~3m21 SCons graph wall time;
- only ~35s belonged to the ten model checks;
- serial reference execution dominated the remainder.

Simply adding `scons -j` is unsafe with the current dependency materialization:
multiple consumers of one dependency can currently restore the same shared
`build/<dependency>` paths.

## Current goal

Complete #69: support explicit bounded parallel SCons execution without shared
dependency-materialization races.

Default remains `jobs=1`. Parallelism is opt-in until the released tool
explicitly exposes the setting.

During a consumer action, direct dependencies use target-private snapshots
materialized from their immutable final bundles. Public `build/<dependency>`
output remains post-run materialized exactly as today.

## Required proof

- `run_repository(..., jobs=N)` validates a positive integer;
- SCons receives the explicit job count;
- default jobs=1 preserves current behavior;
- each consumer step gets a private direct-dependency snapshot;
- two parallel consumers of one dependency never write the same dependency
  snapshot/output path;
- a missing/tampered public dependency output does not create a consumer race;
- previous-step output within one item remains ordered/materialized in the item
  output root;
- dependency context remains valid for the complete consumer command;
- post-run public materialization/publication is unchanged;
- engine schema invalidates prior target state because execution/materialization
  semantics changed;
- serial, parallel, failure, timeout and CacheDir evidence remain deterministic;
- the complete library suite and extended SCons acceptance matrix pass.

## Execution order

1. Define parallel execution/materialization semantics in requirements/design.
2. Extend acceptance before implementation.
3. Implement target-private dependency snapshots and explicit jobs.
4. Run complete library tests, including a parallel shared-dependency proof.
5. Release the library.
6. Pin/expose the release in `tool.cad.ci` as a thin `--jobs`/workflow input.
7. Pass `tool.cad.ci.test` black-box parallel acceptance.
8. Adopt bounded jobs in Forge and remeasure the 10-case reference graph.
9. Only then start the remaining Qualification batch.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #69 Support bounded parallel SCons execution with safe dependency materialization | now | Correct selective Forge batch shows serial reference execution is the dominant wall-time cost; generic SCons execution/materialization belongs here. |

Immediate chain:

`#69 library -> tool exposure -> external acceptance -> Forge remeasure -> remaining Qualification batch`.
