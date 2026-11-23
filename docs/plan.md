# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted release baseline

- `lib.py.cad.ci v0.17.1` is immutable at
  `00d0a763413650339945ca2d9bcfa4265e8dff35`;
- `tool.cad.ci v0.33.1` is immutable at
  `e319979fd6352ca6be2f95ff7227715f00253e96`;
- build123d now executes successfully through the runtime-owned isolated
  interpreter;
- external acceptance #240 exposed one remaining bind-mount ownership bug on
  the subsequent shared-runtime rebuild.

## Current work

### #118 — preserve host ownership of shared runtime outputs

**Now / release blocker for #106 and acceptance #240.**

The cold real-runtime build succeeds. A later verification-definition rebuild
fails before Docker starts because the prior container created root-owned
`items/` output under the host bind mount.

Fix only the owner-layer runtime plumbing:

1. run the shared Docker container with the host numeric UID:GID;
2. set a writable container HOME;
3. keep one Docker container and current engine batching unchanged;
4. add structural command-shape coverage;
5. publish a patch release;
6. repin the thin tool and rerun the same #240 cold/current/rebuild acceptance.

Evidence: tool.cad.ci.test PR #241 / Actions run `45187103416`.

### #106 — extract reusable batched CAD builders from Forge

**Blocked on #118 patch release + #240 acceptance.**

Resume Forge migration only after the released generic stack passes the full
cold/current/rebuild black-box case.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #118 Preserve host ownership of shared CAD runtime outputs | **now** | Implement, patch release, repin tool, rerun #240. |
| #106 Extract reusable batched CAD builders from Forge | **blocked by #118/#240** | Resume Forge migration after external acceptance. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- one compatible N-model build+verification batch means one Docker runtime
  start;
- isolated engines use at most one process per active engine/interpreter group;
- current/cache results avoid Docker and engine-process startup entirely;
- output ownership must not require post-run recursive filesystem passes.
