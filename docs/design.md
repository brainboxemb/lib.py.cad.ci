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

## Item processing

Each item carries an explicit boolean `process` state that defaults to
`true`. Configuration validation rejects a processed item that depends on a
non-processed item, so the executable target graph cannot require an excluded
node.

Planning excludes non-processed items before changed-path selection,
dependency fan-out and full-run selection. Explicit execution of a
non-processed item is rejected. The SCons manifest contains targets only for
processed items.

This is repository-scope participation state, not rebuild state. It is not
part of SCons target signatures and does not add a second freshness engine.

## Rebuild ownership

SCons is the only generic rebuild/reuse engine. The library provides SCons with
files, prerequisite targets and stable execution-significant values. It does
not maintain a second fingerprint or cache-decision mechanism.

## Release path

A generic behavior change is completed here first, then released. Only an exact
released library revision is adopted by `tool.cad.ci`; that tool revision is
then exercised by `tool.cad.ci.test` before consumer repositories migrate.


## Evidence timestamps

Run timing is evidence only.

`run_scons()` records one UTC run start before invoking SCons. Report generation
records the UTC run finish after target classification and output
materialization. Those values are copied into publishable item and step
evidence.

The SCons driver records consumer-command `started_at` immediately before
`subprocess.run()` and `finished_at` immediately after the command returns or
raises. Preparation/materialization before the command is not assigned a step
start timestamp.

Existing monotonic `duration_seconds` semantics remain unchanged and are not
derived from wall-clock timestamps.


## Durable item-evidence schema compatibility

Build-store validation distinguishes two contexts:

- candidate validation: require the current item evidence schema exactly;
- stored durable-state validation: accept the explicitly supported readable
  schema set.

For library 0.7.x:

```text
current candidate schema: 2
readable stored schemas: 1, 2
```

This permits a gradual durable-build migration: unaffected items may remain on
legacy schema 1 while newly produced/replaced items use schema 2.

Build manifest schema remains unchanged.


## Hosted-runner incrementality

The default hosted-runner path assumes no persistent workspace and no restored
SCons cache.

The execution boundary is:

```text
exact Git base/head
  -> changed_files()
  -> affected_items()
  -> run_repository(selected)
  -> SCons graph for selected items only
```

This deliberately separates two concerns:

- Git/CAD-CI decides repository scope across workflow runs;
- SCons decides execution within the requested scope using only state/cache that
  is actually present on that runner.

A fresh runner therefore treats requested targets as cold. This is correct and
expected. Performance comes from not requesting unchanged sibling items.

An optional CacheDir transport may later improve selected-item step reuse, but
it is not required for correctness or for the primary performance contract and
must not be assumed by configuration, evidence or tests.


## Local nested item composition

Configuration composition is a loader concern only.

The public YAML may be concise, but the rest of the library continues to
consume the existing normalized model:

```text
root cad-ci.yml template
        +
local item ci.yml
        ↓
effective item mapping
        ↓
normalize item/repo path scopes
        ↓
existing Item / Step objects
        ↓
existing Git planner and SCons engine
```

### Scoped paths

Legacy list syntax is passed through as repository-relative source patterns.

For mapping syntax:

```yaml
inputs:
  item: [model.py]
  repo: [verification/reference_validation.py]
```

an item rooted at `examples/attach-angle/build123d` becomes internally:

```text
examples/attach-angle/build123d/model.py
verification/reference_validation.py
```

The planner and SCons engine never need to understand the public `item` /
`repo` distinction.

Item-scoped patterns are lexically normalized against the consuming item path.
Exact `..` segments pop one already-normalized path segment. Traversal fails
when there is no repository-relative segment left to pop. No filesystem
`resolve()`, symlink traversal or source lookup participates in this step.

Example:

```text
item root: examples/attach-angle/build123d
pattern:   ../verification/reference_geometry.json
result:    examples/attach-angle/verification/reference_geometry.json
```

Legacy list syntax and `repo:` patterns do not use this normalizer and continue
to reject `..` outright. After item normalization, the existing generated-root
safety rule is applied to the resulting repository-relative pattern.

### Template composition

Root `cad-ci.yml` owns one optional `templates` mapping.

Each template is a partial item mapping. One local item may name one template.
The loader deep-copies the template and recursively merges the local item over
it.

Only mappings merge recursively. Lists and scalar values are replaced. This
avoids field-specific append rules and makes the effective configuration easy
to inspect.

`id`, `template` and `templates` are composition-control fields and are
not valid inside a template.

Template `item` path groups are resolved against the consuming item root after
composition.

### Nested identity

If `id` is absent, the loader converts the repository-relative item path to a
stable ID by replacing path separators with hyphens.

The existing duplicate-ID validation remains authoritative, including possible
collisions between path-derived IDs.

### Performance boundary

Template expansion and scoped-path normalization are in-memory mapping/string
operations performed once by `load_repository()`.

They do not walk source contents beyond existing discovery, hash files, inspect
durable output or inspect SCons state. Therefore they do not add a second
incrementality mechanism.
