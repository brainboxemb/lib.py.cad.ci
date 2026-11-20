# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.7.0` is released at commit
`8955c74055105b06d6af69e0d2f82b6b1fbf575a`.

External acceptance found one release compatibility defect: newly generated
item evidence uses schema 2, while the durable build-store validator still
accepts only schema 1.

## Current goal

Complete #52 as a 0.7.1 patch release.

Current candidate output must use the current item evidence schema. Existing
stored durable output from the previous release must remain readable.

## Execution order

1. Define current-candidate versus legacy-stored evidence compatibility.
2. Require schema 2 for newly prepared candidate items.
3. Accept stored durable item evidence schema 1 or 2 during migration.
4. Keep unknown schemas rejected.
5. Add direct build-store regression tests for both paths.
6. Release 0.7.1 after green CI.
7. Update tool.cad.ci to a 0.12.1 exact library pin.
8. Continue the existing tool.cad.ci.test PR against that patch stack.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #52 Accept current item evidence schema in build store without breaking legacy durable state | now | Release regression found by external acceptance; fix before continuing the 0.12.x stack acceptance. |
| #46 Avoid full library test run for documentation-only changes | now | Separate docs-only real-consumer proof is already running in PR #51; do not mix product code into it. |

## Boundary

This patch changes only build-store evidence compatibility. It does not change
SCons execution, timing semantics, build manifest schema or selection.
