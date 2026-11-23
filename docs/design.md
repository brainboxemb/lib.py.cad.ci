# CAD CI library design

This document describes the stable responsibility split of `lib.py.cad.ci`.
Detailed SCons execution semantics live in `docs/scons-engine.md`.

## Repository boundary

`lib.py.cad.ci` owns generic CAD-CI behavior:

- root, item, repository-owned builder and built-in CAD-builder configuration
  loading;
- changed-item selection;
- translation to one SCons target graph;
- consumer command environment and execution;
- output/evidence handling;
- durable build and Pages mechanics.

It may know generic CAD engine invocation/export adapters such as build123d
and CadQuery. It does not know Forge stages/API contracts, SolidCraft
verification definitions, model-specific acceptance or other consumer-domain
concepts.

`tool.cad.ci` is a thin CLI/workflow surface above this library. Consumer
repositories own their `cad-ci.yml`, declarative item `ci.yml` files and
domain builder implementation.

## Configuration flow

The root `cad-ci.yml` contains repository-wide configuration such as item
discovery, defaults, repository variables, immutable runtime roles and
optional repository-owned builder aliases.

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

## Built-in CAD builder resolution

Builder resolution has two explicit sources:

```text
item builder name
  -> built-in catalog?      -> library-owned normalized Step(s)
  -> repository alias?      -> <builder directory>/builder.yml
  -> otherwise              -> configuration error
```

Built-in names are reserved. Root `builders:` validation rejects an alias
whose name is owned by the built-in catalog, so precedence is never implicit.

The initial catalog metadata records:

```text
name       runtime role   contract revision   output
build123d  reference      1                   model.stl
cadquery   reference      1                   model.stl
```

The loader turns that metadata into the same immutable item/step objects used
for repository-owned builders. Built-in items carry no repository builder path,
so `CAD_CI_BUILDER_PATH` is empty and no consumer builder directory is added
to the watch/input set.

Root runtime configuration is separate from repository variables:

```yaml
runtimes:
  reference: ghcr.io/brainboxemb/cad-reference:v0.3.4
```

The loaded item records the required role and resolved exact image reference.
Both are serialized into every target specification. This makes an image change
dirty without pretending the image is an ordinary consumer command variable.

The normalized built-in command contains the built-in contract revision, for
example conceptually:

```text
python -m cad_ci.cad_builder build123d --contract 1
```

The existing SCons signature therefore changes when the built-in implementation
contract changes, even if consumer files and runtime image are unchanged.

At action time the library-owned command adapter:

1. validates the item-local `model.py`;
2. invokes the normal Docker CLI using the resolved immutable runtime image;
3. mounts the repository read-only at `/repo`;
4. mounts only the target-private `CAD_CI_OUTPUT` read/write at `/output`;
5. uses the item path as the container working directory;
6. disables container networking;
7. executes one engine-specific, domain-neutral model/export script;
8. leaves normal output validation/evidence to the existing SCons driver.

The runtime image owns build123d/CadQuery installations. This package does not
add those engines as Python dependencies.

The first release is single-item execution only. It intentionally does not
replace high-cardinality batch consumers without performance proof. Any future
batch adapter must use the existing active-graph context and remain in this
generic owner layer rather than moving engine code back into Forge.

## Durable publication configuration

Root configuration may carry one optional Pages publication.

Existing item-output mode:

```text
publication.pages
  item   -> processed item id
  output -> exact declared item output
```

Post-build renderer mode:

```text
publication.pages
  builder -> root builder alias
  output  -> exact output declared by the builder's command step
```

`item` and `builder` are mutually exclusive. The config loader validates
the reference after all items/builders have been normalized.

Item-output mode keeps executable site-generation logic in the referenced
item's normal repository-owned builder and therefore remains part of the one
SCons graph.

Post-build renderer mode resolves the same repository-owned builder alias but
requires exactly one command step. It deliberately does **not** lower that step
to SCons: the publication renderer has no rebuild/reuse decision and runs once
only after the durable build commit exists. It reuses the normalized command,
timeout, repository variables and safe output validation rules. It does not
support dependency-copy actions or multiple steps.

For compatibility, `load_repository(repo)` remains the item-only API used by
existing planner/runner callers. New code that needs root metadata uses:

```python
repository = load_repository_config(repo)
repository.items
repository.pages
```

The existing `cad_ci.durable` module remains the only high-level complete-scope
adapter. No second integration helper is introduced.

Generated branch names enter at this adapter boundary. State materialization and
build publication receive one selected build branch; Pages publication receives
one selected Pages branch. Defaults remain `build` and `gh-pages`.
Repository `cad-ci.yml` does not own these Git transport names.

```text
generated build branch absent
  -> first main/named scope = complete full run

generated build branch present
  -> resolve stored scope source commit
  -> existing scope: update selected replacements + current membership
  -> missing named scope: prepare complete named scope
  -> missing main scope: fail closed

published complete build scope
  -> item mode: resolve configured item output
  -> builder mode: run one repository-owned renderer with complete-scope +
     exact build-commit context into a temporary output root
  -> validate configured Pages directory
  -> add generic source/build/scope provenance
  -> publish stable root or named subtree
```

Stable Pages preserve names are derived from valid named complete scopes already
present in the materialized generated build tree. Lane names therefore are not
duplicated in root publication configuration or workflow inputs.

Git fetch/push remains delegated to `cad_ci.git_publish`; the durable adapter
passes the selected branch names to those existing primitives. GitHub workflow
orchestration stays outside the library API.

The publication renderer runs from the repository root. CAD-CI-owned
environment is populated after repository variables and contains:

```text
CAD_CI_REPO
CAD_CI_OUTPUT
CAD_CI_BUILDER
CAD_CI_BUILDER_PATH
CAD_CI_COMPLETE_SCOPE
CAD_CI_BUILD_SCOPE
CAD_CI_SOURCE_SHA
CAD_CI_SOURCE_REF
CAD_CI_BUILD_COMMIT
```

`CAD_CI_OUTPUT` is a fresh temporary root. The configured output is validated
with the same safe file/directory and symlink rules used for normal declared
outputs. The renderer receives no mutable generated-branch checkout and cannot
change the already-published remote build commit.

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
  inspect/materialize generated build branch
  -> branch absent: first main/named publication = full run
  -> branch present: resolve complete scope
       -> existing scope: stored source_commit = incremental base
       -> first named scope: full run
       -> missing main: fail closed

after run:
  load repository config
  -> select affected items from base..head, or all processed items for first run
  -> update/prepare main or named complete scope
  -> publish via existing generated-branch publisher
```

These are generic CAD-CI semantics, so they live in `cad_ci.durable`.
The module composes existing planner, build-store and Git publication APIs; it
does not introduce another storage format, selector or publication engine.

`tool.cad.ci` may expose this behavior through workflow helper arguments,
including selected generated build/Page branch names, and GitHub output files.
It must not read durable `build.json` directly or choose between
`prepare-main`, `update-main`, `prepare-named` and `update-named`
itself.

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

For the durable-lane lifecycle, stable publication derives its named keep set
from the valid named complete scopes already materialized from the generated
build branch. This makes the build store the single durable scope inventory and
avoids repeating lane names in consumer publication configuration.

The lower-level `publish_pages(... preserve_subtrees=...)` API remains
available for callers outside this durable-lane contract.

PR previews remain under `previews/pr-<number>` and are always preserved by
stable publication independently of the named keep set.
