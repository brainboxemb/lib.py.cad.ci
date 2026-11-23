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
- `tool.cad.ci.test` #232 is currently qualifying that exact stack, including
  the 0.15.0 post-build Pages renderer through a real repository-owned builder.

## Current work

### #106 — built-in generic CAD builder catalog

**Design now; implementation after #232 acceptance.**

Consumer migrations show repeated engine/toolchain execution that is not
repository-specific. Initial built-in builders:

```text
build123d
cadquery
```

A built-in name is selected directly:

```yaml
builder: build123d
```

without a root `builders:` path entry. Repository-owned builders keep their
existing alias/path mechanism.

Required contract:

1. built-in names are reserved and cannot be shadowed by repository aliases;
2. built-in resolution produces the same normal `Step`/SCons execution model;
3. built-in builder semantic identity is part of the target signature so a
   builder behavior change cannot reuse stale output;
4. initial single-model contract uses item-local `model.py` and emits
   `model.stl`;
5. engine packages come from the immutable generic CAD runtime role, not Python
   dependencies added to this library;
6. runtime image selection remains explicit consumer configuration; do not pin
   a mutable/latest runtime inside library code;
7. design a batch variant/pattern using existing active-dependent context
   before Forge adopts dozens of per-item engine invocations, so migration does
   not regress runtime performance;
8. geometry acceptance, previews, Forge command compilation and
   consumer-specific batch projection remain outside these builders.

Execution order:

1. finish external v0.32 / library 0.15.0 acceptance in
   `tool.cad.ci.test` #232;
2. finalize requirements/design/SCons acceptance for #106;
3. implement built-in resolution + build123d/CadQuery runtime adapters and
   tests;
4. release the library;
5. update/release `tool.cad.ci`;
6. black-box qualify built-in builders in `tool.cad.ci.test` using the
   immutable `cad-reference` runtime;
7. only then resume Forge #740 and replace duplicated engine build behavior.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #106 Add built-in generic CAD builder catalog | **design now / blocked on #232 for implementation** | Define built-in resolution/runtime/batch contract, then implement after v0.32 acceptance. |
| #89 Align historical changelog | **later / docs-only** | Apply shared changelog presentation without runtime/API changes. |

## Boundary

Built-in builders are generic engine execution/export adapters, not generic
verification policy. SCons remains the only rebuild/reuse engine. Runtime
images remain owned/released by their runtime repository. Consumer repositories
own their model semantics, verification definitions and presentation.
