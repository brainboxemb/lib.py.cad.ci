# Repository plan

This file is the current source of truth for unfinished work in `lib.py.cad.ci`.

The repository owns generic CAD-CI planning/execution semantics. Consumer- or
domain-specific behavior belongs in consumer repositories.

## Current released and accepted state

`lib.py.cad.ci 0.10.0` is released at exact commit
`397fb04005b46de8d433cb18c091b1e73714b877`.

Current externally accepted thin tool:

- `tool.cad.ci 0.18.0` @
  `b62f9d0b169aa201a3c66c3166f364396b2d71bc`;
- `tool.cad.ci.test` #73 / PR #74 / run `45010776155` — success.

Accepted library behavior includes selective active-closure startup, bounded
SCons jobs, deterministic target-private dependency snapshots, durable
publication support, and dependency-output `copy:`.

## Current work

### #83 — signature-safe active direct-dependent context

`lib.py.cad.ci 0.11.0` is released at exact commit
`e621daf6e309bdd0e3f643a12007f1b66490696d`. Library implementation and release are complete; final ecosystem acceptance now runs in `tool.cad.ci.test` #77 / PR #78 through released `tool.cad.ci 0.18.1`.

Status: **now**.

Consumer evidence from Forge #661:

- no-model-change run `45012216695`: shared model/reference batches do not run;
- one-model PR #668 / run `45012288226`: only 6 SCons targets are active, but
  the selected shared model batch still executes all 36 models;
- explicit full run `45011709878`: all 229 targets/all models execute, as
  intended.

Top-level selection is therefore already correct. The generic gap is that an
active shared producer command cannot see which of its **direct dependent
consumer items** are active.

Minimal contract:

```yaml
steps:
  - id: batch
    selection_context: direct_dependents
    run: [...]
    outputs: [...]
```

For that command step CAD-CI exposes a deterministic sorted
`CAD_CI_ACTIVE_DEPENDENTS_JSON` list containing active direct dependent item
ids.

The list is part of the step target signature/cache identity. A different
active-dependent set therefore invalidates/rebuilds the batch target rather
than reusing a partial subset result.

Execution order:

1. requirements/design/acceptance before code;
2. implement step-level opt-in only;
3. prove one-dependent, changed-dependent, full, no-op, CURRENT/CacheDir and
   jobs>1 behavior;
4. release the library;
5. repin/release the thin tool;
6. externally accept the exact released pair;
7. only then let Forge #661 filter its shared batches.

## Open issue assessment — 2026-11-22

| Issue | Status | Assessment |
| --- | --- | --- |
| #83 Expose signature-safe active consumer selection to shared batch actions | **blocked** | Library 0.11.0 is released at `e621daf6…`; close after released tool 0.18.1 passes `tool.cad.ci.test` #77 / PR #78. |

## Non-goals

- no changed-path planner beyond the existing CAD-CI selector;
- no domain-specific batch/model/reference concepts;
- no implicit filtering of command work;
- no new scheduler or freshness engine;
- no per-consumer process/container fan-out.

After #83 is released and externally accepted this repository returns to
demand-driven mode.
