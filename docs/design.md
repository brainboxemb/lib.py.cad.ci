# CAD CI library design

This document describes the stable responsibility split of `lib.py.cad.ci`.
Detailed SCons execution semantics live in `docs/scons-engine.md`.

## Repository boundary

`lib.py.cad.ci` owns generic CAD-CI behavior:

- root, item and repository-owned builder configuration loading;
- changed-item selection;
- translation to one SCons target graph;
- consumer command environment and execution;
- output/evidence handling;
- durable build and Pages mechanics.

It does not know Forge, SolidCraft, model-specific verification or other
consumer-domain concepts.

`tool.cad.ci` is a thin CLI/workflow surface above this library. Consumer
repositories own their `cad-ci.yml`, declarative item `ci.yml` files and
domain builder implementation.

## Configuration flow

The root `cad-ci.yml` contains repository-wide configuration such as item
discovery, defaults, repository variables and optional builder aliases.

The preferred public boundary is:

```text
root cad-ci.yml
  builder alias -> repository directory
        +
item ci.yml
  identity / dependencies / selection / builder name
        +
<builder directory>/builder.yml
  executable ordered steps / outputs / timeouts
        ↓
normalized Item / Step objects
        ↓
existing planner and SCons engine
```

The builder indirection is a configuration-loader concern only. SCons still
receives the same normalized ordered step graph and remains the only generic
execution/incrementality engine.

Builder directories are repository-owned source. The loader adds the complete
builder directory to every using item's coarse watch set. For command steps
with explicit inputs, it also adds that builder directory to the step input set.
Consequently one shared builder edit selects its users and participates in the
target signature without consumer-local wrapper commands.

Legacy item-local `steps` remain accepted as a migration path. Configuration
rejects an item that has both `builder` and `steps`, or neither.

During command execution CAD-CI exposes the resolved builder identity as
`CAD_CI_BUILDER` and the absolute directory as `CAD_CI_BUILDER_PATH`.
The library does not interpret the contents of domain builder scripts.

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


## Builder resolution

Root builder aliases are safe repository-relative directory paths. Absolute
paths, traversal and generated roots are rejected. Each selected directory must
contain `builder.yml` with builder schema 1.

A builder file owns executable step implementation only. Item identity,
dependencies, processing state and top-level selection strategy remain in the
item's `ci.yml`.

Builder names and paths are included in the SCons target specification. This
makes moving an item to another implementation an explicit execution-significant
change even when the resulting command text happens to be identical.

No built-in SolidCraft/OpenSCAD/Forge builder is introduced here. A later
domain tool may ship a versioned builder directory, but generic CAD-CI only
loads the repository path selected by configuration.

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


## Durable ownership for nested items

The source item path remains the durable storage location; no new encoded item
directory is introduced.

The build store instead treats an item directory as a container for several
independent ownership sets.

For one `Item`, the owned set is:

```text
<item path>/<declared output 1>
<item path>/<declared output 2>
...
<item path>/.cad-ci/
```

Everything else below `<item path>/` is outside that item's ownership.

### Owned-path helpers

Build-store preparation uses one helper that copies exactly the owned set from
a candidate root to a scope root.

Replacement uses one helper that:

1. removes only the target item's declared output paths and `.cad-ci`;
2. copies those exact paths from the source scope;
3. leaves all other files/directories below the item path untouched;
4. prunes only directories that become empty as a result of owned-path removal.

Whole-tree `copytree` / rename replacement remains valid only for complete
scope installation, never for replacing one item inside a scope.

### Manifest rows

New rows add `outputs`, a sorted list of declared consumer output paths.
Build manifest schema remains 1 so existing generated branches are readable.

Operations with current `Item` objects use configuration ownership directly.
Operations that only receive stored scopes use row `outputs`.

Rows without `outputs` are legacy. Before applying historical whole-tree
replacement, the build store compares manifest item paths. If the legacy item
is nested with another item in the resulting view, replacement is rejected as
ambiguous.

### Candidate isolation

A local candidate tree may physically contain descendant item directories
inside a parent item directory. Preparing a parent item must therefore never
copy the complete candidate parent directory. Only its declared outputs and
evidence are copied.

### Configuration validation

After all items are loaded, the configuration layer compares nested item source
paths with parent declared outputs. A parent output and descendant item root may
not overlap in either direction.

This check uses normalized repository-relative paths only and does not inspect
the filesystem.


## Execution log boundary

The SCons child process inherits the CAD-CI process stdout/stderr. The library
does not capture the complete SCons output into memory before printing it.

The SCons driver wraps the Python target function in an action with a custom
display function. The display function uses only the logical manifest key:

```text
CAD CI run: <item-id>:<step-id>
```

The display function is presentation only. It does not participate in the
target signature and does not replace the structured action observation or
post-run report.

Consumer subprocesses continue to inherit the SCons process streams, so their
flushed stdout/stderr remains live. The final report/summary is still generated
after SCons exits.


## Removed-item cleanup during partial main updates

`update_main()` receives two item collections with different meanings:

```text
selected items
  -> validated candidate replacements

current processed items
  -> authoritative membership of the next complete main baseline
```

The library computes:

```text
previous rows - current paths = removed rows
current paths - (previous current rows + selected replacements) = missing rows
```

A non-empty missing-row set is an error. A removed-row set is cleanup work.

Before copying/mutating the output scope, the library validates:

1. every selected replacement candidate;
2. that every selected item is part of current processed configuration;
3. that the resulting row set can be complete;
4. that every removed legacy row has unambiguous ownership.

After validation it copies the previous main scope, removes each removed item's
owned paths, replaces each selected item's owned paths and writes a manifest
whose item keys exactly equal current processed item paths.

### Removed rows with ownership metadata

For a stored row with `outputs`, removal deletes:

```text
<item>/<declared output>...
<item>/.cad-ci/
```

It then prunes only empty directories up to the durable scope root. Nested
current child/parent content therefore keeps the containing directory alive.

### Legacy removed rows

A stored row without `outputs` has historical whole-tree ownership only when
its item path is not nested with another previous or current durable item path.
In that non-nested case the complete item directory may be removed.

If the legacy row is nested with another item path, removal fails before output
mutation. The library never guesses which bytes inside an ambiguous legacy
nested tree belong to the removed item.

### CLI boundary

The thin CLI already loads current repository configuration to compute affected
items. For main updates it passes both:

- the affected current items as replacements;
- all currently processed items as baseline membership.

Deletion semantics remain entirely in `lib.py.cad.ci`.


## Durable complete-scope adapter API

Hosted workflow adapters need two operations around the SCons run:

```text
before run:
  materialize generated build branch
  -> resolve complete scope
       -> existing scope: stored source_commit = incremental base
       -> first named scope: full run
       -> missing main: error

after run:
  load repository config
  -> select affected items from base..head, or all processed items for first run
  -> update/prepare main or named complete scope
  -> publish via existing generated-branch publisher
```

These are generic CAD-CI semantics, so they live in `cad_ci.durable`.
The module composes existing planner, build-store and Git publication APIs; it
does not introduce another storage format, selector or publication engine.

`tool.cad.ci` may expose this behavior through workflow helper arguments and
GitHub output files, but must not read durable `build.json` directly or
choose between `update-main`, `update-named` and `prepare-named` itself.

## Named complete publication scopes

Long-lived integration lanes use the existing generated branches rather than
creating one generated branch per lane.

### Build store

`main` remains the stable complete scope and `pr/<number>` remains a sparse
overlay. A named complete scope is represented explicitly in its manifest and
is installed at one validated top-level directory in the generated build
branch.

The complete-scope preparation/update implementation is shared with `main`:
selection, current-membership reconciliation, owned-output replacement and
evidence validation do not fork by lane name. Main-specific public functions
remain compatibility wrappers around that generic complete-scope primitive.

Generated-branch publication still clones the latest remote head, mutates one
scope and retries only a push race. Therefore two lane publications close
together preserve each other's sibling directories.

### Pages

A named Pages publication replaces exactly one validated top-level subtree.
Stable-root publication cannot infer which arbitrary top-level directories are
development previews because normal stable sites also own top-level
directories. The caller therefore supplies the exact named-subtree keep set
when replacing the stable root.

PR previews remain under `previews/pr-<number>` and are always preserved by
stable publication independently of the named keep set.

This keeps publication mechanics generic while leaving lane naming and site
layout policy with the consumer.
