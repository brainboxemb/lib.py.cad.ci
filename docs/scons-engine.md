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
~~~

`defaults.timeout_seconds` is optional.

`variables` is an optional repository-wide string mapping. Names use
`^[A-Z_][A-Z0-9_]*$`. Names beginning with `GITHUB_`, `RUNNER_`,
`ACTIONS_` or `CAD_CI_` are reserved and invalid.

The validated mapping is sorted by name in the loaded model so its serialized
form is deterministic.

### Item ci.yml

Supported fields:

~~~yaml
id: simple-case
kind: example
process: true

needs:
  - tool

watch:
  - examples/simple_case/**
  - shared/**

strategy:
  affected: changed
  reuse: true

steps:
  - id: build
    inputs:
      - examples/simple_case/build.py
      - examples/simple_case/input/**
      - shared/**
    run: [python, build.py]
    outputs:
      - generated

  - id: verify
    inputs:
      - examples/simple_case/verify.py
    run: [python, verify.py]
    outputs:
      - verify.json
    timeout_seconds: 600
~~~

Rules:
- `kind` is descriptive only;
- `process` is optional and defaults to `true` for compatibility;
- `process: false` removes the item from automatic, full and explicit
  execution;
- an active item may not depend on a non-processed item;
- `process` is selection state and is not part of a step target signature;
- `watch` is for Git-level item selection;
- `inputs` is for SCons rebuild dependencies;
- omitted step `inputs` inherits the item's `watch`;
- item `ci.yml` is represented by step-spec Values, not as a broad file
  dependency;
- `strategy.reuse: false` means explicitly execute every active step and do not
  restore/store its target from CacheDir.

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

After configuration loading, step `inputs` and item `watch` always use normalized repository-relative patterns. Legacy YAML list syntax is repository-relative directly; the configuration mapping form may also contain item-root-relative patterns which the loader prefixes with the owning item path before SCons translation.

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
