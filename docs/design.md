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


## Item-root configuration composition

The loader converts concise consumer YAML into the same immutable `Item` and
`Step` model consumed by the existing planner and SCons engine.

### Path normalization boundary

Legacy list fields remain repository-relative:

```yaml
watch: [examples/a/**, shared/**]
```

New mapping fields make scope explicit:

```yaml
watch:
  item: [scpf/**, tests/**]
  repo: [scripts/shared_check.py]
```

For an item at `examples/a/ci.yml`, the loader normalizes the latter to:

```text
examples/a/scpf/**
examples/a/tests/**
scripts/shared_check.py
```

The planner and SCons engine therefore continue to receive only normalized
repository-relative patterns. They do not need to understand templates,
ancestors or item-relative syntax.

### Template table

The root `cad-ci.yml` owns an optional `templates` mapping. Each value is a
partial item configuration. Template validation is generic and rejects
composition-control fields that would make expansion recursive or ambiguous.

One effective template name is selected after ancestor/local composition.
Templates do not inherit other templates.

### Ancestor defaults

For a discovered item at `a/b/c/ci.yml`, the loader checks existing ancestor
files in this order:

```text
a/ci.yml
a/b/ci.yml
```

Only their `children` mapping participates. Their own item fields do not leak
into descendants.

Composition uses a small recursive mapping merge:

- mapping + mapping: recursively merge keys;
- scalar/list/null in the later layer: replace the earlier value;
- local item is always the final layer.

This keeps override behavior deterministic and inspectable without inventing
field-specific merge rules.

### Identity

The source path remains the durable storage key.

If an item omits `id`, its default ID is the repository-relative item path
with separators replaced by dashes. Flat item defaults therefore remain
unchanged; previously-invalid nested implicit IDs become usable.

### Performance and rebuild boundary

Template/ancestor expansion happens once in `load_repository()` and is only
mapping/path work. It does not resolve source file contents or inspect SCons
state.

After expansion:

```text
concise YAML
  -> effective mapping
  -> normalized Item/Step
  -> existing Git planner
  -> existing SCons target graph
```

No new fingerprint, cache or changed-file engine is introduced.
