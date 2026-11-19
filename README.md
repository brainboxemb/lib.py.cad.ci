# lib.py.cad.ci

Reusable Python implementation for BrainboxEmb CAD CI.

This repository owns generic CI mechanics. It intentionally contains no Forge,
SolidCraft, model-library or qualification semantics.

## Responsibilities

The library owns configuration/model loading, changed-path selection, dependency
planning, step execution, state/reuse validation, generic build/Pages handling
and generic Git publication primitives.

`tool.cad.ci` is the thin CLI above this library. Real consumers own only
domain-specific checks and declarative `ci.yml`.

## Development rule

Generic CI behaviour is developed and unit-tested here first, integrated into
`tool.cad.ci`, proven in `exp.2026-014.cad-ci-consumer`, released/pinned,
and only then used by Forge/CAD.

## Affected-item strategies

- `changed`: own inputs or dependency changes select the item.
- `direct`: only own input changes select the item automatically; explicit
  selection still expands/validates all dependencies.
- `always`: every changed-path plan selects the item.

`direct` supports fan-in summary items without widening ordinary incremental
runs.
