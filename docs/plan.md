# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, reusable CAD engine
builders, verification integration, durable build-store and publication semantics.

## Accepted baseline

- #108 library-foundation work is merged and green;
- #110 generic builder + reusable verification integration is merged at
  `28ce15be88f30c750d19423a54921a433759b479` and green on main;
- `lib.py.cad.verification v0.16.0` is immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- `tool.cad.ci v0.32.0` remains the last externally accepted released tool
  stack.

## Current work

### #112 — publish immutable 0.17.0

**Now.**

Promote the tested #110 owner-layer implementation as immutable
`lib.py.cad.ci v0.17.0`.

Release gate:

1. VERSION, pyproject.toml and CHANGELOG.md declare 0.17.0;
2. release PR installed-wheel/SCons CI is green;
3. merge the release PR;
4. verify the main workflow publishes `v0.17.0`;
5. verify the release target equals the exact tested release commit.

### #106 — extract reusable batched CAD builders from Forge

**Next after #112.**

The generic build123d/CadQuery shared batch and reusable verification integration
now live in their correct owner repositories. After 0.17.0 is immutable:

1. repin/release `tool.cad.ci` to the exact 0.17.0 library;
2. qualify that exact released stack in `tool.cad.ci.test`;
3. migrate Forge away from its duplicated reference batch,
   `cad-verification-package` item and generic verification wiring;
4. keep only Forge model sources and model-specific verification/presentation
   data in Forge.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #112 Publish immutable 0.17.0 verification integration release | **now** | Finish immutable release gate. |
| #106 Extract reusable batched CAD builders from Forge | **next after #112** | Repin/release tool, external acceptance, then Forge migration. |
| #89 Align historical changelog | later / docs-only | Apply shared changelog presentation only. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- one compatible N-model build+verification batch means one CAD runtime start;
- the verification wheel is one shared dependency target, never per model;
- current/cache results avoid runtime startup entirely;
- no second repository planner/cache/runtime scheduler is introduced;
- normal CI uses cheap graph/call-count tests; real Docker/released-stack
  acceptance stays in `tool.cad.ci.test`.

## Boundary

`lib.py.cad.ci` owns verification integration only.
`lib.py.cad.verification` owns verification semantics/adapters.
Consumers own model-specific verification and presentation policy.
