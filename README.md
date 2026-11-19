# lib.py.cad.ci

Reusable Python implementation for BrainboxEmb CAD CI.

This repository owns generic CI mechanics. It intentionally contains no Forge,
SolidCraft or CAD-domain behaviour.

## Responsibilities

The library owns:
- configuration loading and validation;
- coarse Git changed-item selection;
- translation of item/step configuration to SCons targets;
- timeout/output handling around consumer commands;
- structured execution evidence;
- durable build output;
- Pages handling;
- safe generated-branch publication.

SCons owns local dependency ordering, signatures, incremental decisions,
persistent build state and CacheDir reuse. The library must not maintain a
second generic fingerprint/reuse engine beside SCons.

`tool.cad.ci` is the thin CLI above this library. Real consumers own only
their domain commands/checks and declarative `cad-ci.yml` / `ci.yml` files.

## Design before implementation

The generic contract is defined in:
- `docs/requirements.md` — observable product behaviour;
- `docs/scons-engine.md` — exact execution-engine design;
- `docs/scons-acceptance.md` — expected result sequences before implementation.

If implementation reveals an undefined semantic choice, the design is updated
first. Forge or CAD is never used to discover generic CI behaviour.

## Verification order

Generic behaviour is unit/conformance-tested here, then released, exposed by a
released `tool.cad.ci`, and finally verified end to end in
`tool.cad.ci.test` against multiple representative consumer layouts.

Only after that exact released stack is green may Forge or CAD migrate.

## Affected-item strategies

- `changed`: own watched changes or selected dependency changes select item.
- `direct`: only own watched/config changes select item automatically.
- `always`: every changed-path plan selects item.

These strategies choose top-level repository scope only. SCons separately
decides which requested/prerequisite step targets actually execute.
