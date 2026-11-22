# Repository plan

This file is the current source of truth for unfinished work in `lib.py.cad.ci`.

The repository owns generic CAD-CI planning/execution semantics. Consumer- or
domain-specific behavior belongs in consumer repositories.

## Current released and accepted state

`lib.py.cad.ci 0.11.0` is released at exact commit
`e621daf6e309bdd0e3f643a12007f1b66490696d`.

Current externally accepted thin tool:

- `tool.cad.ci 0.18.1` @
  `e29d3127d5d3f9310f3cab4e27430a64a61c21cc`;
- `tool.cad.ci.test` #77 / PR #78 / run `45019713862` — success.

Accepted library behavior includes selective active-closure startup, bounded
SCons jobs, deterministic target-private dependency snapshots, durable
publication support, dependency-output `copy:`, and signature-safe opt-in
`selection_context: direct_dependents` with schema-5 public step evidence.

## Current work

No generic CAD-CI implementation is active.

Issue #83 is released and externally accepted. Forge #661 may now consume the
released 0.11.0 / 0.18.1 pair and apply the active direct-dependent context at
its domain-specific shared-batch boundary.

## Open issue assessment — 2026-11-22

No open library issues remain after #83 is closed.

## Non-goals

- no changed-path planner beyond the existing CAD-CI selector;
- no domain-specific batch/model/reference concepts;
- no implicit filtering of command work;
- no new scheduler or freshness engine;
- no per-consumer process/container fan-out.

The repository is back in demand-driven mode.
