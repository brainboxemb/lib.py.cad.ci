# SCons execution engine design

This document is the normative technical design for the execution part of
`lib.py.cad.ci`.

`docs/requirements.md` defines observable product behaviour.
`docs/scons-acceptance.md` defines the exact expected run sequences that must
pass before the engine is released.

The design follows the proven architecture in `tool.scad-project`: a
tool-owned manifest, a small SCons driver, SCons as the single rebuild/cache
engine, and structured post-run evidence.

## 1. Scope

SCons owns only local execution/incrementality.

SCons owns:
- prerequisite graph;
- target signatures;
- dirty/current decisions;
- action/spec changes;
- persistent local state;
- CacheDir lookup/restore;
- execution ordering.

`lib.py.cad.ci` owns:
- YAML loading/validation;
- coarse Git changed-file selection;
- conversion from CI config to SCons manifest;
- consumer command wrapper;
- timeout handling;
- output packaging/materialization;
- structured evidence;
- durable build store;
- Pages;
- generated branch publication;
- source freshness;
- external-resource handling.

There is no second generic fingerprint/reuse engine beside SCons.

## 2. Public configuration model

### Root cad-ci.yml

Supported fields:

~~~yaml
schema: 1

defaults:
  timeout_seconds: 300

variables:
  SOLIDCRAFT_VERSION: "0.42.0"
  RUNTIME_IMAGE: "ghcr.io/example/runtime:runtime-abc123"

items:
  - tool
  - examples/*

builders:
  python-model: ci/builders/python-model
~~~

`defaults.timeout_seconds` is optional.

`variables` is an optional repository-wide string mapping. Names use
`^[A-Z_][A-Z0-9_]*$`. Names beginning with `GITHUB_`, `RUNNER_`,
`ACTIONS_` or `CAD_CI_` are reserved and invalid.

The validated mapping is sorted by name in the loaded model so its serialized
form is deterministic.

### Item ci.yml

The preferred item file is declarative:

~~~yaml
id: simple-case
kind: example
process: true
builder: python-model

needs:
  - tool

watch:
  item:
    - model.py
    - input/**
  repo:
    - shared/**

strategy:
  affected: changed
  reuse: true
~~~

The root builder alias resolves to a repository directory. That directory owns
one `builder.yml`:

~~~yaml
schema: 1
description: Shared Python model build

steps:
  - id: build
    inputs:
      item:
        - model.py
        - input/**
    run: [python, "$CAD_CI_BUILDER_PATH/build.py"]
    outputs:
      - generated

  - id: verify
    run: [python, "$CAD_CI_BUILDER_PATH/verify.py"]
    outputs:
      - verify.json
    timeout_seconds: 600
~~~

A shell command may expand `CAD_CI_BUILDER_PATH`; argv-style commands receive
the same environment but do not perform shell expansion themselves.

Rules:
- `kind` is descriptive only;
- `process` is optional and defaults to `true` for compatibility;
- `process: false` removes the item from automatic, full and explicit
  execution;
- an active item may not depend on a non-processed item;
- `process` is selection state and is not part of a step target signature;
- `watch` is for Git-level item selection;
- `inputs` is for SCons rebuild dependencies;
- a builder-backed item automatically watches its complete builder directory;
- explicit command-step inputs automatically include that builder directory;
- omitted step `inputs` inherits the effective item `watch`;
- builder name/path are represented in step-spec Values;
- `strategy.reuse: false` means explicitly execute every active step and do not
  restore/store its target from CacheDir.

For migration only, an existing item may still define inline `steps` instead
of `builder`. An item must define exactly one of them.

### Builder lowering

Builder indirection is resolved by configuration loading before the SCons
manifest is written:

~~~text
cad-ci.yml builder alias
  -> repository-relative builder directory
  -> builder.yml
  -> validated ordered Step objects
  -> existing Item / Step target graph
~~~

SCons never parses builder YAML and does not know SolidCraft, OpenSCAD, Forge or
other domain types.

The resolved builder alias and path are included in each target signature.
Commands receive:

~~~text
CAD_CI_BUILDER
CAD_CI_BUILDER_PATH
~~~

Both are empty for a legacy inline-step item. Commands continue to run with the
item directory as their working directory.

## 3. Internal target model

Every configured step maps to exactly one logical SCons target.

Stable logical key:

~~~text
<item-id>:<step-id>
~~~

Example:

~~~text
tool:build
tool:test
simple-case:build
simple-case:verify
~~~

The physical SCons target is one private output bundle per step:

~~~text
.cache/cad-ci/scons/targets/<item-path>/<step-id>.tar
~~~

The bundle target is internal state and never appears on the generated `build`
branch.

## 4. Dependency graph

Within one item:

~~~text
step-1 -> step-2 -> step-3
~~~

Step 2 depends on step 1; step 3 depends on step 2.

Between items:

~~~text
dependency-item:last-step -> consumer-item:first-step
~~~

For a consumer with `needs: [library]` and steps `build, verify`:

~~~text
library:last
      |
      v
consumer:build -> consumer:verify
~~~

SCons owns traversal and ordering. CAD CI does not independently topologically
execute items.

## 5. Step target signature

Each step target receives three classes of SCons dependency.

### File sources

The resolved regular files matching that step's effective `inputs`.

The exact sorted relative-path list is also included in the step-spec Value.
Adding/removing a matched file therefore changes the target even when remaining
file contents are unchanged.

### Previous/dependency target

- previous step target for step N > 1;
- final target of every direct `needs` item for step 1.

### Step-spec Value

Stable JSON containing only settings that affect that step:

~~~json
{
  "schema": 1,
  "item_id": "simple-case",
  "step_id": "verify",
  "run": ["python", "verify.py"],
  "outputs": ["verify.json"],
  "timeout_seconds": 600,
  "reuse": true,
  "variables": {
    "RUNTIME_IMAGE": "ghcr.io/example/runtime:runtime-abc123",
    "SOLIDCRAFT_VERSION": "0.42.0"
  },
  "resolved_inputs": [
    "examples/simple_case/verify.py"
  ],
  "engine_schema": 1
}
~~~

Not included:
- descriptive `kind`;
- Git-selection strategy;
- unrelated step configuration;
- absolute workspace paths;
- source commit SHA.

Therefore changing verify command/timeout/outputs invalidates verify without
invalidating an unrelated build target.

Repository variables are included in every step-spec Value because every
consumer command receives them. Changing one repository variable therefore
invalidates every active step that was produced under the previous mapping.

A stable engine-schema Value participates in every target signature. Changing
execution or bundle semantics deliberately invalidates old target entries.

Do not hash the complete CAD-CI Python source tree into each target signature.

## 6. Source path rules

After configuration loading, step `inputs` and item `watch` always use normalized repository-relative patterns. Legacy YAML list syntax is repository-relative directly; scoped YAML mapping syntax may also contain item-root-relative patterns which the loader prefixes with the consuming item path.

They may not:
- be absolute;
- contain `..`;
- resolve into `.git/`, `.cache/` or `build/`.

Input discovery:
- returns regular files only;
- rejects symlink inputs until a future schema explicitly supports them;
- sorts relative paths lexically;
- passes actual file nodes to SCons.

The item's source `ci.yml` is excluded from inherited watch-based step inputs.
Its effective settings are represented by the step-spec Value.

## 7. Output ownership

Each step owns declared output paths below:

~~~text
build/<item-source-path>/
~~~

The namespace:

~~~text
build/<item-source-path>/.cad-ci/
~~~

is reserved for generic evidence and cannot be consumer output.

Within one item, output ownership must be unambiguous. Duplicate paths and
parent/child overlap between different steps are invalid.

A later step may read output from an earlier step, but it must not mutate an
output owned by another step.

## 8. Bundle format

The internal SCons target is a deterministic uncompressed tar bundle.

This is chosen because:
- CacheDir reliably handles one regular target file;
- one step may own files and complete directories;
- directory membership and empty directories must survive fresh-runner restore;
- one target gives one cacheable result per step.

Each step bundle represents the complete item state after that step.

Bundle contents:
- every output owned by the current step;
- every output owned by earlier steps of the same item;
- reserved internal manifest `.cad-ci/__bundle__.json`.

For steps `prepare -> build -> verify`, the prepare bundle contains prepare
outputs, the build bundle contains prepare + build outputs, and the verify
bundle contains prepare + build + verify outputs. Therefore the final bundle is
a complete item result and any earlier-step output change also changes the final
dependency target.

Bundle manifest schema 1:

~~~json
{
  "schema": 1,
  "outputs": {
    "generated": {
      "kind": "directory",
      "sha256": "...",
      "mode": 493
    },
    "result.json": {
      "kind": "file",
      "sha256": "...",
      "mode": 420
    }
  }
}
~~~

Directory digest includes relative directory entries, including empty
directories, relative file paths and file content hashes.

Archive normalization fixes uid/gid/user/group and mtime, uses lexical member
order, preserves file/directory modes and rejects symlinks.

A successful action exists only after its complete bundle has been written.

## 9. Materialization model

Materialization is not a rebuild decision.

Before a consumer step action executes:
1. SCons has made prerequisite bundle targets current;
2. the CAD-CI action wrapper materializes required predecessor bundles in graph
   order;
3. direct dependency item bundles are materialized;
4. the wrapper removes only the current step's declared output paths;
5. the consumer command runs and must recreate its declared outputs.

Cleaning only the current step's owned paths prevents stale nested files from a
previous run while preserving outputs owned by prerequisite steps.

For a same-item later step, the immediately preceding cumulative bundle is
enough to restore every earlier output.

For an item dependency, its final cumulative bundle restores the complete item
output tree.

After SCons finishes successfully, CAD CI materializes the active/requested item
bundles in step order once more.

Materialization result is separate from SCons outcome:
- `UNCHANGED`: output already matched;
- `RESTORED`: output was absent;
- `REPAIRED`: output existed but differed;
- `ERROR`: materialization failed.

Materialization never changes BUILT/CACHE_RESTORED/CURRENT into a different
SCons build decision.

## 10. Command execution

Consumer commands run with:

~~~text
cwd = <repo>/<item-path>
~~~

Environment:

~~~text
<repository variables from root cad-ci.yml>
CAD_CI_REPO
CAD_CI_ITEM
CAD_CI_ITEM_PATH
CAD_CI_OUTPUT
CAD_CI_DEPENDENCIES_JSON
~~~

Environment precedence is inherited runner/caller values, then repository
variables, then CAD-CI-owned `CAD_CI_*` values. Root variable validation
prevents a repository from declaring a CAD-CI-owned name.

List commands execute directly without a shell. String commands use
`shell=True` because the consumer explicitly requested shell syntax.

Timeout wraps the consumer command only.

Successful action requires exit 0 and every declared output to be valid.
Non-zero exit, timeout, missing output or unsafe output is an error.

A failed action leaves no successful new bundle target.

## 11. Dependency context

`CAD_CI_DEPENDENCIES_JSON` describes direct item dependencies only:

~~~json
{
  "tool": {
    "output_root": "/workspace/build/tool",
    "outputs": ["dist", "metadata.json"],
    "final_bundle": "/workspace/.cache/cad-ci/scons/targets/tool/test.tar",
    "final_bundle_sha256": "..."
  }
}
~~~

`cad_ci.context.current_context()`:
- loads the current item config;
- confirms the dependency is declared in `needs`;
- confirms the requested output is declared;
- confirms the final bundle exists;
- confirms materialized output matches bundle metadata;
- exposes the path.

It never asks whether the dependency should rebuild.

## 12. Local directories

Exact private layout:

~~~text
.cache/
  cad-ci/
    scons/
      cache/
      state/
        .sconsign.dblite
      targets/
        <item-path>/
          <step>.tar
      run/
        manifest.json
        result.json
        actions/
          <item-path>/
            <step>.json
~~~

Only `scons/cache/` is intended for cross-runner cache transport.

Correctness must not depend on `scons/state/` surviving. Acceptance explicitly
deletes state while keeping CacheDir.

Nothing below `.cache/` is durable publication output.

## 13. Structured SCons outcomes

For every active target:

### BUILT

The consumer action executed successfully and a valid target bundle exists.

### CACHE_RESTORED

The action did not execute, the target bundle was absent before SCons, and a
valid bundle exists afterward.

### CURRENT

The action did not execute, the target bundle existed before SCons, and remains
valid afterward.

### ERROR

No valid SCons target result exists because of action failure, timeout, invalid
declared output or bundle failure.

Materialization is reported independently. If materialization fails after a
BUILT/CACHE_RESTORED/CURRENT decision, the SCons outcome is preserved and the
step's overall status becomes `materialization_error`.

Detection uses explicit action records plus pre/post target state. Console text
is never parsed.

## 14. Public evidence

After each run, CAD CI writes evidence below the item output root.

Step evidence:

~~~text
build/<item>/.cad-ci/steps/<step>.json
~~~

Schema 1 contains:
- `schema`;
- `engine: scons`;
- `engine_schema`;
- item/step IDs;
- overall status;
- SCons outcome;
- materialization result;
- action-executed flag;
- duration/exit/timeout where applicable;
- target-spec digest;
- bundle SHA-256;
- declared output manifest.

Complete item evidence:

~~~text
build/<item>/.cad-ci/item.json
~~~

Schema 1 contains:
- schema/engine/engine schema;
- item ID;
- `status: pass`;
- final step ID;
- final target-spec digest;
- final bundle SHA-256.

Evidence never participates in SCons rebuild decisions.

Any run that does not ensure the final item target removes stale complete-item
evidence for that item.

## 15. Partial command semantics

`--step`, `--until` and `--from` are mutually exclusive. Combining them is
a configuration/CLI error before SCons starts.

### Normal run

Request final step targets for selected items. SCons naturally traverses dirty
prerequisites.

### --until STEP

Request STEP as top-level target. Nothing is forced.

If STEP and prerequisites are current, no consumer action runs. If an earlier
prerequisite is dirty, SCons rebuilds it and evaluates STEP.

If STEP is not final, complete-item evidence is removed.

### --step STEP

Request STEP and mark only that target AlwaysBuild for this invocation.

SCons makes prerequisites current first. Later steps are not requested.

If STEP is not final, complete-item evidence is removed.

### --from STEP

Request the final item target.

Mark STEP and every following step AlwaysBuild for this invocation. Earlier
prerequisites use normal SCons decisions.

This is the explicit operator command for "rerun from here".

## 16. strategy.reuse

`strategy.reuse: true` is default.

Normal SCons signature and CacheDir behaviour applies.

`strategy.reuse: false`:
- every active step of that item is AlwaysBuild;
- those step targets use NoCache;
- dependency items retain their own policy.

## 17. Git selection and process state

`affected_items()` remains because Git selection decides repository scope, not
build freshness.

Only items with effective `process: true` participate.

Given changed paths:
- root `cad-ci.yml` change selects all processed items;
- item `ci.yml` change selects that item;
- `watch` matches select that item;
- selected dependency changes propagate to processed dependants unless the
  dependant is `affected: direct`;
- `affected: always` applies only to processed items;
- a `process: false` item is never selected by its own config/watch changes,
  dependency fan-out or a full run;
- explicit `--item` execution of a `process: false` item fails clearly.

Configuration loading rejects a processed item that directly depends on a
`process: false` item. This keeps dependency closure deterministic before
SCons starts.

Runtime does not use the old custom topological execution plan. SCons receives
selected final targets and owns dependency ordering.

`cad-ci plan` may explain selected items and dependency closure, but must not
claim SCons dirty/current status without invoking SCons.

## 18. Durable build store

Generated `build` branch layout:

~~~text
main/<item-source-path>/...
pr/<number>/<item-source-path>/...
build.json
~~~

Item source path remains the storage key. Item ID is metadata.

Candidate validation requires:

~~~text
<item>/.cad-ci/item.json
~~~

with supported schema, `status: pass`, expected item ID, current final step and
non-empty final bundle digest.

Build manifest item row schema 1:

~~~json
{
  "source_commit": "...",
  "item_id": "simple-case",
  "engine": "scons",
  "engine_schema": 1,
  "final_step": "verify",
  "final_target_spec_digest": "...",
  "final_bundle_sha256": "..."
}
~~~

SConsign, private target bundles and CacheDir are never published.

## 19. Publication boundary

SCons knows nothing about:
- `build/main`;
- PR overlays;
- Pages;
- Git branches;
- GitHub;
- GHCR.

Publication consumes completed candidate output only.

## 20. Implementation order

Implementation starts only after this design and
`docs/scons-acceptance.md` agree with `docs/requirements.md`.

Then:
1. adjust config model for inputs/output ownership/reserved namespace;
2. make manifest/driver match this exact target model;
3. make materialization match this exact design;
4. write public evidence;
5. switch dependency context to bundle-backed context;
6. switch library execution API;
7. delete obsolete custom rebuild/fingerprint code;
8. release library;
9. update and release tool;
10. prove exact release in `tool.cad.ci.test`;
11. only then migrate Forge/CAD.

If implementation reveals an undefined semantic choice, stop and update the
design before coding further.


## Timing evidence

Timing fields never participate in target signatures or cache keys.

Run scope:

- capture `run_started_at` before the SCons invocation;
- capture `run_finished_at` after target classification and output
  materialization;
- write both to the private run report;
- copy both to every public step evidence file and complete item evidence file
  written for that run.

Action scope:

- capture `started_at` immediately before the consumer command is invoked;
- capture `finished_at` immediately after it returns or raises;
- store both in the private action observation;
- propagate both to the report row and public step evidence;
- leave both values null for CURRENT and CACHE_RESTORED targets and for failures
  before consumer-command execution.

Format: UTC ISO-8601, millisecond precision, literal `Z`.

`duration_seconds` keeps its current monotonic-clock definition. Timestamp
fields are observability only.


## 21. Bounded parallel SCons execution

The engine receives one explicit `jobs` value from the public execution API
and invokes:

```text
scons -Q -j <jobs> -f <driver> CAD_CI_MANIFEST=...
```

`jobs` is execution policy, not target identity. It is recorded in the private
run manifest/report for observability but excluded from target signatures.

The default is one job.

Because parallel consumers can share one direct dependency, consumer commands
must no longer materialize direct dependencies into the shared public
`build/<dependency>` tree.

### Target-private dependency snapshot

For consumer target:

```text
<consumer item>:<step>
```

and direct dependency:

```text
<dependency item>:<final step>
```

the driver materializes the immutable dependency final bundle under:

```text
.cache/cad-ci/scons/run/dependencies/
  <consumer item path>/
    <consumer step>/
      <dependency item path>/
```

The run dependency root is cleared before each SCons invocation.

The dependency context passed to the consumer contains this private
`output_root`, the configured output list, final bundle path and bundle
SHA-256.

No other target writes that private root.

### Own step predecessors

`materialize_before` continues to include the previous step target for an
item. The driver materializes non-direct-dependency predecessors into the
item's normal output root before the current action.

Direct dependency final keys are excluded from this shared materialization path
and instead use the private snapshot flow above.

### Post-run public materialization

`write_report()` keeps the existing `_materialize_active()` phase. It
restores/repairs public active item output from final target bundles after SCons
has completed. Durable/publication consumers therefore see the same
`build/<item>` layout.

### Schema boundary

Increment `ENGINE_SCHEMA` because action-time dependency materialization and
runtime context paths change. Existing target signatures include
`engine_schema`, so the first run with the new engine rebuilds the affected
targets deliberately.

Increment the structured report schema when the explicit `jobs` observation is
added.

### Failure boundary

A dependency-snapshot materialization failure is still a setup/materialization
error before consumer-command execution. Action start/finish timestamps remain
null for that failure.

SCons owns parallel scheduling and dependency ordering. CAD-CI does not add a
thread/process pool beside SCons.


## 22. Active-closure-first manifest preparation

Manifest preparation has two phases.

### Phase 1 — lightweight target graph

Build the logical target-key/dependency graph from already loaded `Item` and
`Step` configuration only. This phase does not walk repository source files.

Resolve the requested keys to their complete prerequisite closure while
preserving repository/config order.

### Phase 2 — active target specifications

Create one source inventory for the repository source tree, excluding the
existing generated roots. The inventory retains matched symlinks so active
source validation can reject them without following them.

Generate full target specifications only for keys in the active closure.
For each active step:
- filter the shared source inventory with that step's effective input patterns;
- preserve the existing target signature fields and resolved source ordering;
- preserve cumulative outputs, direct dependency descriptors and
  `materialize_before` semantics.

The SCons manifest contains only active target specifications. Requested keys
remain the public top-level targets; active keys remain their prerequisite
closure. SCons therefore receives the same executable graph without paying
source-discovery/signature-preparation cost for unrelated targets.

A full run naturally makes every processed target active and therefore retains
the previous whole-graph behavior.

No persistent source index is added. The inventory is per invocation and never
participates in rebuild decisions outside the normal active target signatures.

## 23. Dependency-output copy target

### Configuration model

`Step` has two mutually exclusive action forms:

- `run: str | tuple[str, ...]` for the existing external command action;
- `copy: DependencyCopy` for an engine-owned dependency-output copy action.

`DependencyCopy` contains:

```text
dependency: direct item id
source: normalized source-root template
```

The source template accepts only the literal `{item_path}` token. Expansion
happens during repository configuration normalization, when the owning
repository-relative item path is already known. Target specs therefore contain
the normalized expanded source root. Unknown braces/tokens are configuration
errors.

For a copy step, repository source inputs are empty. Its SCons signature
contains:

- engine schema;
- item/step identity;
- action type `copy`;
- expanded dependency id/source root;
- declared/cumulative outputs;
- direct `needs`;
- reuse policy and repository variables only where they remain execution
  significant.

The dependency final target is still the SCons prerequisite, so dependency
bundle changes invalidate the copy target naturally.

### Bundle projection

A copy action does **not** call the normal command-step
`_dependency_context()`, because that would materialize the dependency's
complete final bundle into a target-private snapshot.

Instead:

1. resolve the configured direct dependency's final target bundle;
2. validate its bundle manifest;
3. validate the expanded source root against the dependency's declared output
   ownership;
4. for each consumer output, select only archive members at
   `<source>/<output>` and descendants;
5. remap those members to consumer-relative `<output>`;
6. write one deterministic consumer target bundle with a normal bundle manifest;
7. leave public `build/<consumer>/` materialization to the existing post-run
   materialization phase.

The implementation may use a target-private temporary directory for the
selected members before `write_bundle()`; it must never extract the complete
dependency output for a copy action.

Files/directories, empty directories, modes, link rejection and deterministic
bundle metadata use the existing bundle rules. Missing selected output,
unexpected links, path traversal, source outside declared dependency output or
bundle/manifest mismatch fail the target as an output/materialization error.

### Parallelism

Multiple copy targets may read the same immutable dependency bundle
concurrently. They never share a writable dependency snapshot. Their consumer
target bundles and temporary selected-member roots are target-private.

Normal command targets continue using the existing target-private dependency
snapshot design. #79 does not weaken that jobs>1 isolation contract.

### Evidence/schema

Increment `ENGINE_SCHEMA`: copy target execution and signatures are new engine
semantics, so old target/cache entries must not be reused.

Increment the private report schema and public step-evidence schema to add
`action_type`:

```text
command
copy
```

For an executed copy action:

- outcome is `BUILT`;
- `action_executed=true`;
- `action_type=copy`;
- start/finish/duration describe the engine-owned projection action;
- `exit_code=null`;
- `timeout_seconds=null`.

For CURRENT/CACHE_RESTORED rows the action timestamps remain null while
`action_type` still describes the configured target.

Complete-item evidence remains schema-compatible because its fields do not
change.

### Operator wording

Console output is literal:

```text
CAD CI copy: <item>:<step>
```

Command targets keep:

```text
CAD CI run: <item>:<step>
```

Console text remains diagnostic only.


## 24. Active direct-dependent context in SCons targets

### Configuration model

`Step` gains:

```text
selection_context: "none" | "direct_dependents"
```

The default is `none`. Config validation rejects the field on `copy:`
steps.

### Derivation

The engine already computes the exact active target closure:

```text
requested keys
  -> _active_keys(target dependency graph)
  -> active target-key set
```

For each command step with `selection_context=direct_dependents`, derive the
context without re-running Git selection:

1. find configured items whose `needs` contains the current item id;
2. retain a dependent when any configured target key of that dependent is in
   the active target-key set;
3. preserve repository item order;
4. store only the dependent item ids.

This is intentionally **direct** dependents, not an arbitrary reverse transitive
closure. Shared producers have an explicit `needs` relationship to their
consumer items, which keeps the contract inspectable and avoids unrelated
downstream activation leaking into the signature.

### Target specification and freshness

The derived list is written into:

- target spec field `active_dependents`;
- target signature field `active_dependents`;
- command environment as compact sorted JSON;
- private/public step evidence.

Because SCons depends on the target signature Value node, changing
`["item-a"]` to `["item-b"]` or to the full list invalidates the target even
when source files are identical.

Bump `ENGINE_SCHEMA`, private report schema and public step-evidence schema
because target signatures and evidence change.

### Command environment

`scons_driver._command_environment()` sets:

```text
CAD_CI_ACTIVE_DEPENDENTS_JSON
```

from the target spec after repository variables have been applied, just like
the other reserved CAD-CI environment values.

For non-opted-in command steps the value is the empty JSON list `[]`. This
keeps consumer code simple while only opted-in targets include selection
context in their signature.

### Full/no-op behavior

Full run naturally activates every processed target, therefore every processed
direct dependent is present.

A no-target run returns the existing empty report before manifest/SCons
execution; no selection-aware target runs.

### Cache and parallelism

The active-dependent list is immutable manifest data. Parallel targets only read
their own spec, so no mutable global selection state is shared.

CacheDir keys remain correct because the target signature contains the exact
list. A cache entry built for one dependent subset cannot satisfy another
subset signature.
