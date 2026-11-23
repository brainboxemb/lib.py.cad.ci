# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, reusable CAD engine
builders, durable build-store and complete-scope state, Pages and generated
branch publication semantics. Tool/workflow repositories adapt these APIs; they
do not reimplement them.

## Released baseline

- `lib.py.cad.ci 0.15.0` @
  `24c3abb267feea9ae91f24f8fdb435cba68f089a`;
- `tool.cad.ci v0.32.0` @
  `19e894567ac534ce90428dc61c6afa126c1d3318` pins that exact library;
- `tool.cad.ci.test` #232 completed external acceptance of that exact stack;
  the v0.32.0 blocker for the next owner-layer change is cleared.

## Current work


### #106 — extract reusable batched CAD builders from Forge

**Implementation in progress.**

Forge already proves the required execution shape: one normal CAD-CI/SCons
graph, one shared producer, signature-safe active dependent context, one runtime
batch, then normal `copy: dependency` projection back to each model. #106 moves
that generic mechanism to its correct owner instead of inventing another one.

Initial built-in builders:

```text
build123d
cadquery
```

A model selects only the builder:

```yaml
id: reference-build123d
builder: build123d
```

It does not declare the shared producer, runtime command, batch collection or
copy plumbing. Built-in lowering creates that existing graph internally.

Required contract:

1. built-in names are reserved and cannot be shadowed by repository aliases;
2. compatible builders are grouped by runtime role; build123d and CadQuery
   initially share one `reference` runtime batch;
3. the batch receives the exact active direct dependents through the mechanism
   already released by #83;
4. SCons remains the only dependency/freshness/cache engine;
5. the shared producer writes per-model results and each model receives its own
   normal dependency-copy projection;
6. item-local `model.py` exposes global `model`; canonical initial output is
   `model.stl`;
7. runtime image selection remains explicit consumer configuration through
   immutable/non-latest runtime-role mappings;
8. geometry acceptance, previews, Forge command compilation and presentation
   remain outside these generic builders.

Execution order:

1. finish library implementation and focused conformance tests;
2. open one PR and run normal repository CI;
3. release the library;
4. repin/release `tool.cad.ci`;
5. black-box qualify the exact released stack in `tool.cad.ci.test` using the
   immutable `cad-reference` runtime;
6. only then resume Forge #740 and remove the duplicated generic builder/batch
   mechanics there.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #106 Extract reusable batched CAD builders from Forge | **implementation in progress** | Finish tests/PR, release owner stack, then migrate Forge #740. |
| #89 Align historical changelog | **later / docs-only** | Apply shared changelog presentation without runtime/API changes. |

## Boundary

Built-in builders are generic engine execution/export adapters, not generic
verification policy. SCons remains the only rebuild/reuse engine. Runtime
images remain owned/released by their runtime repository. Consumer repositories
own their model semantics, verification definitions and presentation.
