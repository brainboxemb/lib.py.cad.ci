# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted implementation baseline

- #114 runtime-owned build123d interpreter batching is merged at
  `42d884c09ca08e9f2891fa0ae0792852266d0c19` and green on main;
- `lib.py.cad.verification v0.16.0` is immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external acceptance #240 remains the release/real-runtime gate before Forge
  adoption.

## Current work

### #116 — publish immutable 0.17.1

**Now.**

Promote the #114 compatibility fix as a patch release:

1. VERSION, pyproject.toml and CHANGELOG.md declare 0.17.1;
2. release PR installed-wheel/SCons CI is green;
3. merge the release PR;
4. verify `v0.17.1` targets the exact tested release commit;
5. repin the thin tool with no new tool-owned behavior;
6. rerun external acceptance #240 on the exact patch stack.

### #106 — extract reusable batched CAD builders from Forge

**Blocked on #116 + #240.**

After the real released runtime passes black-box acceptance, migrate Forge away
from duplicated reference batch/package wiring.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #116 Publish 0.17.1 runtime interpreter patch | **now** | Finish immutable release gate. |
| #106 Extract reusable batched CAD builders from Forge | **blocked by #116/#240** | Resume Forge migration after external acceptance. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- one compatible N-model build+verification batch means one Docker runtime
  start;
- isolated engines use at most one process per active engine/interpreter group,
  never per model;
- current/cache results avoid Docker and engine-process startup entirely;
- real runtime compatibility remains an external acceptance concern.
