# lib.py.cad.ci

Reusable Python implementation for BrainboxEmb CAD CI.

This repository owns generic CI mechanics. It intentionally contains no
Forge, SolidCraft or CAD-domain behaviour.

## Responsibilities

The library owns configuration loading, changed-path selection, dependency
planning, step execution, timeouts, state/reuse validation, durable build
output, Pages handling and safe Git publication.

`tool.cad.ci` is the thin CLI above this library. Real consumers own only
their domain-specific commands, checks and declarative `ci.yml` files.

## Development rule

Generic CI behaviour is developed and unit-tested here first. It is then
released, exposed by a released `tool.cad.ci`, and verified end to end in
`tool.cad.ci.test` against multiple representative consumer layouts. Only
after that may Forge or CAD migrate to the exact released stack.

A consumer migration must not be used to discover or design generic CI
behaviour.

See `docs/requirements.md` for the complete CI contract.

## Affected-item strategies

- `changed`: own inputs or dependency changes select the item.
- `direct`: only own input changes select the item automatically; explicit
  selection still expands and validates dependencies.
- `always`: every changed-path plan selects the item.

`direct` supports fan-in summary items without widening ordinary incremental
runs.
