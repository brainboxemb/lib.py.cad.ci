# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, reusable CAD engine
builders, verification integration, durable build-store and publication semantics.

## Accepted baseline

- #108 library-foundation work is merged at
  `2b413782a2274c30506991993c71b717d3f05fa7` and its installed-wheel/SCons
  suite is green;
- `lib.py.cad.verification v0.16.0` is immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- `tool.cad.ci v0.32.0` remains the last externally accepted tool stack while
  this owner-layer work is in progress.

## Current work

### #110 — compose generic builders with reusable CAD verification

**Now / prerequisite for completing #106.**

Add first-class declarative verification wiring without duplicating verification
semantics:

1. repository pins the exact released verification package;
2. item/template selects a verification adapter and definition;
3. CAD-CI synthesizes one shared verification-package producer;
4. the compatible runtime batch depends on that package once;
5. build + verification run in the same shared runtime/container;
6. public build and verify outputs are ordinary dependency-copy projections;
7. all current/cache/rebuild decisions remain SCons-owned.

Initial adapter: `mesh-geometry` on the `reference` runtime, delegated to
`lib.py.cad.verification v0.16.0`.

### #106 — extract reusable batched CAD builders from Forge

**Blocked on #110.**

After #110 is green, complete builder release/black-box qualification and
migrate Forge away from duplicated reference batch/package wiring.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #110 Compose generic CAD builders with reusable CAD verification | **now** | Implement package + manifest + same-runtime verification wiring. |
| #106 Extract reusable batched CAD builders from Forge | **blocked by #110** | Resume release/acceptance/migration after #110. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- compatible work is batched to amortize runtime startup;
- one compatible N-model build+verification batch means one CAD runtime start;
- the verification wheel is one shared dependency target, never per model;
- current/cache results avoid runtime startup entirely;
- no repeated repository planning/scanning is introduced;
- normal CI uses cheap graph/call-count tests; real Docker/released-stack
  acceptance stays in `tool.cad.ci.test`.

## Boundary

`lib.py.cad.ci` owns verification integration only.
`lib.py.cad.verification` owns verification semantics/adapters.
Consumers own model-specific verification data and presentation policy.
