# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted implementation baseline

- #118 host-owned shared runtime output is merged at
  `89ba68f12fc95911e2151537c31f2046a7d7e978` and green on main;
- `lib.py.cad.verification v0.16.0` remains immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external acceptance #240 remains the real-runtime gate before Forge adoption.

## Current work

### #120 — publish immutable 0.17.2

**Now.**

Promote the #118 bind-mount ownership fix as a patch release:

1. VERSION, pyproject.toml and CHANGELOG.md declare 0.17.2;
2. release PR installed-wheel/SCons CI is green;
3. merge the release PR;
4. verify `v0.17.2` targets the exact tested release commit;
5. repin the thin tool with no new tool-owned behavior;
6. rerun external acceptance #240 on the exact patch stack.

### #106 — extract reusable batched CAD builders from Forge

**Blocked on #120 + #240.**

After the real released runtime passes cold/current/rebuild black-box acceptance,
migrate Forge away from duplicated reference batch/package wiring.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #120 Publish 0.17.2 host-output ownership patch | **now** | Finish immutable release gate. |
| #106 Extract reusable batched CAD builders from Forge | **blocked by #120/#240** | Resume Forge migration after external acceptance. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- one compatible N-model build+verification batch means one Docker runtime
  start;
- isolated engines use at most one process per active engine/interpreter group;
- current/cache results avoid Docker and engine-process startup entirely;
- output ownership requires no post-run recursive filesystem repair.
