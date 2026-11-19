# CAD CI library design

This document describes the stable responsibility split of `lib.py.cad.ci`.
Detailed SCons execution semantics live in `docs/scons-engine.md`.

## Repository boundary

`lib.py.cad.ci` owns generic CAD-CI behavior:

- root and item configuration loading;
- changed-item selection;
- translation to one SCons target graph;
- consumer command environment and execution;
- output/evidence handling;
- durable build and Pages mechanics.

It does not know Forge, SolidCraft, model-specific verification or other
consumer-domain concepts.

`tool.cad.ci` is a thin CLI/workflow surface above this library. Consumer
repositories own their `cad-ci.yml`, item `ci.yml` files and domain commands.

## Configuration flow

The root `cad-ci.yml` contains repository-wide configuration such as item
discovery, defaults and repository variables. Item `ci.yml` files contain
item-specific dependencies, selection paths, ordered commands and outputs.

Configuration is validated once when the repository is loaded. The resulting
immutable item model carries all execution-significant repository settings
needed to construct the SCons graph.

## Repository variables

A root `variables` mapping provides non-secret string values that every
consumer command may read from its environment.

The library validates the mapping before execution:

- names use uppercase environment-variable syntax;
- `GITHUB_*`, `RUNNER_*`, `ACTIONS_*` and `CAD_CI_*` are reserved;
- values are strings.

Repository variables are execution inputs. Their complete sorted mapping is
included in every step target specification, so changing a value invalidates
the corresponding SCons target instead of reusing output produced with an old
value.

Command environment precedence is:

1. inherited runner/caller environment;
2. repository variables from `cad-ci.yml`;
3. CAD-CI-owned `CAD_CI_*` values.

This keeps workflow-provided general environment available while making the
repository's declared CI expectation authoritative and protecting CAD-CI's own
runtime context.

## Rebuild ownership

SCons is the only generic rebuild/reuse engine. The library provides SCons with
files, prerequisite targets and stable execution-significant values. It does
not maintain a second fingerprint or cache-decision mechanism.

## Release path

A generic behavior change is completed here first, then released. Only an exact
released library revision is adopted by `tool.cad.ci`; that tool revision is
then exercised by `tool.cad.ci.test` before consumer repositories migrate.
