# CI requirements

This document is the product contract for the generic CAD CI stack. It defines
observable behaviour. Implementation details belong in `docs/scons-engine.md`
and expected test sequences in `docs/scons-acceptance.md`.

A Forge or CAD consumer must not migrate until one exact released
`lib.py.cad.ci` + `tool.cad.ci` stack satisfies this contract and
`tool.cad.ci.test` proves it end to end.

## 1. Configuration ownership

The root `cad-ci.yml` owns repository-wide CI settings, item discovery and
optional aliases for repository-owned builders.

Each normal item `ci.yml` is declarative and owns:
- item ID and descriptive kind;
- optional explicit `process` participation;
- one builder reference;
- direct item dependencies;
- coarse Git-selection paths;
- affected-item strategy;
- cache/reuse policy.

A repository-owned builder directory owns the executable implementation in
`builder.yml`:
- ordered steps;
- exact step inputs where narrower inputs are useful;
- commands or engine-owned copy actions;
- declared outputs;
- execution timeout overrides.

The root maps a stable builder name to its directory, for example:

```yaml
schema: 1
items: [models/*]
builders:
  solidcraft-model: ci/builders/solidcraft-model
```

An item then selects the implementation without embedding it:

```yaml
id: simple-mft
kind: model
builder: solidcraft-model
watch:
  item: [model.py, model.yml]
```

Changing a builder directory is an execution-significant and selection-significant
change for every processed item that uses that builder.

Legacy item-local `steps` remain readable during migration, but an item may
configure exactly one of `builder` or `steps`. New consumers should use the
builder reference path.

Generic behaviour must not be hidden in GitHub Actions YAML or consumer helper
scripts. Generic code must not know Forge, SolidCraft, model, qualification,
integration, native or gate semantics. Domain-specific builders belong to the
consumer repository or a separately versioned domain tool, not this library.

### Repository variables

The root `cad-ci.yml` may define an optional `variables` mapping.

Repository variables:
- use uppercase environment-variable names;
- have string values;
- reject `GITHUB_*`, `RUNNER_*`, `ACTIONS_*` and `CAD_CI_*` names;
- are injected into every configured consumer command;
- override an inherited runner/caller variable with the same name;
- cannot override CAD-CI-owned runtime values;
- are included in every step's SCons target specification.

Changing a repository variable is therefore an execution-significant change:
an affected requested step must not remain `CURRENT` solely because its files
and command are unchanged.

Repositories without `variables` retain the existing behavior.

## 2. Two levels of selection

Git selection and build selection are deliberately different.

### Item processing

An item may explicitly declare:

```yaml
process: true
```

or:

```yaml
process: false
```

When omitted, `process` is `true` for backward compatibility.

- `process: true` means the item participates in normal CAD-CI selection and
  execution.
- `process: false` means the item is excluded from changed-path selection,
  dependency fan-out, full runs and explicit execution.
- A processed item may not depend on a `process: false` item; this is an
  invalid repository configuration.
- A non-processed item may depend on processed items because it is itself not
  executed.
- Changing a shared processed dependency still propagates normally to every
  processed dependant. `process` does not weaken dependency fan-out among
  active items.

`process` is repository-scope selection state. It does not participate in
SCons target signatures because a non-processed item has no requested target.

### Git selection

`watch` determines which processed top-level items are selected from a Git diff.

The supported affected strategies are:
- `changed`: own watched changes and selected dependency changes select the item;
- `direct`: only own watched changes select the item automatically;
- `always`: every changed-file plan selects the item.

This is coarse repository/PR selection only. Non-processed items are excluded
before these affected-strategy rules are applied.

### Build selection

Once top-level item targets are requested, SCons owns execution ordering and
local target state for those requested items.

On a fresh hosted runner with no restored SCons state or CacheDir, every
requested target is cold. SCons cannot infer validity from a previous workflow
run that is not available on the runner.

Therefore hosted-CI incrementality is primarily item-level:

```text
Git diff -> affected items -> request only those items
```

Unselected items are not evaluated by SCons and do not execute. Selected items
may reuse prior steps only when valid SCons state/targets or an explicitly
restored CacheDir are actually available.

CAD CI must not run a second fingerprint/reuse engine beside SCons.

## 3. Step inputs

A step may declare `inputs` as repository-relative file/glob patterns.

When `inputs` is omitted, the step inherits the item's effective `watch`
patterns so existing/simple consumers remain valid. For builder-backed items,
the effective watch set also includes the complete builder directory.

When a builder command declares explicit step inputs, the builder directory is
still added as an execution input. A builder implementation change therefore
cannot leave an otherwise selected target `CURRENT`.

The item's own `ci.yml` is not treated as an undifferentiated file input.
Relevant step configuration is represented in the step's SCons target
specification. Therefore a change to a setting that affects one step need not
invalidate unrelated earlier steps.

Adding/removing a file matched by a step input pattern must invalidate that
step even when the remaining file contents are unchanged.

## 4. Step ordering and item dependencies

Every configured step is one logical build target.

Within an item:
- step 1 has no previous-step prerequisite;
- step N depends on step N-1.

Between items:
- the first step depends on the final step of every item in `needs`.

SCons owns prerequisite ordering and decides which prerequisites actually need
execution.

Consumer commands still run from the item source folder and receive:
- `CAD_CI_REPO`;
- `CAD_CI_ITEM`;
- `CAD_CI_ITEM_PATH`;
- `CAD_CI_BUILDER` (empty for legacy inline-step items);
- `CAD_CI_BUILDER_PATH` (absolute resolved builder directory, or empty);
- `CAD_CI_OUTPUT`;
- validated direct-dependency output context.

## 5. Full and partial execution

A normal run requests the final target of every selected top-level item.

Partial execution is explicit. `--step`, `--until` and `--from` are
mutually exclusive.

- `--step <id>`: force that exact step action once; SCons first makes its
  prerequisites current. Later steps are not requested.
- `--until <id>`: request that step target without forcing it; SCons executes
  only dirty prerequisites/target work.
- `--from <id>`: request the item's final target and force the named step and
  every following step. Earlier prerequisites are only rebuilt when SCons
  considers them dirty.

A partial run that does not ensure the final item target must not leave evidence
claiming the complete item is current.

A failed step leaves no successful target artifact that can be reused.

## 6. Execution timeouts

The repository can define a default `timeout_seconds` in root `cad-ci.yml`.

A step can override that timeout.

Timeout values are positive integers. A timeout:
- terminates the command;
- is recorded distinctly from a normal non-zero exit;
- produces no successful step target;
- is never cacheable/reusable;
- is never interpreted as proof that an unrelated external resource is absent.

## 7. Step outputs

Every step declares the files/directories it owns below that item's
`build/<source-item-path>/` directory.

Output paths:
- are relative;
- cannot escape the item output directory;
- cannot use the reserved `.cad-ci/` evidence namespace;
- must not overlap output paths owned by another step of the same item.

Immediately before a step action runs, CAD CI removes only that step's own
declared output paths after all prerequisite output has been materialized. This
prevents stale files from a previous invocation becoming part of the new result.

A successful step must then recreate every declared output.

A complete directory output includes its nested files and empty directories.

Symlinks inside declared output are rejected because durable output must not
refer outside the owned output tree.

## 8. SCons target artifact and cache

The cacheable SCons target for one step is an internal deterministic bundle
representing the complete item output state after that step. It contains the
declared outputs of that step plus all outputs owned by earlier steps, together
with an output manifest.

The internal bundle:
- is not part of durable `build/` output;
- supports file and complete-directory outputs uniformly;
- is the object stored/restored through SCons `CacheDir`;
- contains stable output metadata/hashes;
- is invalidated by SCons input/action/spec signatures.

SCons local state/cache lives below `.cache/cad-ci/` and is never published.

The normal hosted-runner contract does not require that directory to survive
between workflow runs. Cross-run CacheDir transport is an optional future
optimization and must be explicit in workflow/tool design if introduced.

Because bundles are cumulative, an item's final bundle represents every
declared output of the complete item. After SCons makes a prerequisite bundle
current, CAD CI materializes that bundle before a dependent consumer command
uses it.

After the run, requested/active step bundles are materialized into
`build/<item>/` in step order. Materialization may repair missing/tampered
local output without changing SCons' build decision.

## 9. Build outcomes

Each active step has one structured outcome:

- `BUILT`: the consumer action executed successfully in this run.
- `CACHE_RESTORED`: the action did not execute; SCons restored a previously
  absent target bundle from CacheDir.
- `CURRENT`: the action did not execute; the existing target bundle was
  already current.
- `ERROR`: the SCons target itself has no valid result because the command,
  timeout, declared output or target bundle failed.

Materialization is a separate observation and never rewrites a successful SCons
decision. A step is usable only when its SCons outcome is not `ERROR` and its
materialization is not `ERROR`.

Materialization has a separate observation:
- `UNCHANGED`: durable local output already matched the bundle;
- `RESTORED`: output was absent and was materialized;
- `REPAIRED`: output existed but did not match and was replaced;
- `ERROR`: materialization failed.

Console wording must never be parsed to infer either result.

## 10. Evidence, not rebuild state

Successful/failed run evidence is written below the reserved item namespace:

```text
build/<item>/.cad-ci/item.json
build/<item>/.cad-ci/steps/<step>.json
```

Evidence records what happened and is publishable. It must not participate in
SCons rebuild decisions.

Step evidence records at least:
- schema version;
- item and step IDs;
- engine and engine schema;
- SCons outcome;
- materialization result;
- overall status (`pass`, `fail`, `timeout`, `output_error` or
  `materialization_error`);
- action-executed flag;
- timeout/exit/duration where applicable;
- `started_at` and `finished_at` for a consumer action that actually executed;
- run-level `run_started_at` and `run_finished_at`;
- target-spec digest;
- target bundle digest;
- declared output manifest.

Timestamps use UTC ISO-8601 with a literal `Z` suffix and millisecond precision,
for example `2026-11-20T08:30:12.345Z`.

For `CURRENT` and `CACHE_RESTORED`, `started_at` and `finished_at` are
`null`: CAD-CI must not invent action times when the consumer command did not
execute.

Complete item evidence also records `run_started_at` and `run_finished_at`
for the run that produced or confirmed the complete item.

Complete item evidence exists only when the final target was ensured
successfully. It records at least:
- schema version;
- item ID;
- status;
- final step ID;
- final target-spec digest;
- final target bundle digest.

Any run that stops before the final item target removes stale complete-item
evidence for that item.

## 11. Dependency output context

A consumer may read only outputs declared by its direct `needs` items.

SCons makes the dependency's final target current first. CAD CI then
materializes and validates the dependency bundle before running the consumer
command.

The runtime context exposes:
- dependency item ID;
- materialized output root;
- declared output names;
- final bundle digest.

Runtime context validates integrity against the dependency bundle. It does not
decide whether a dependency should rebuild.

## 12. Durable build store

Local candidate output mirrors source item paths.

The durable generated `build` branch contains:
- `main/`: complete accepted baseline;
- optional caller-named complete scopes such as `dev/`;
- `pr/<number>/`: sparse overlay containing only selected PR item paths.

Named complete scopes use the same validated item membership, replacement and
deletion-reconciliation semantics as `main`. A named scope is one safe
generated-branch path segment and may not be `main`, `pr`, absolute or
traversing.

Publication validates successful complete-item evidence from
`.cad-ci/item.json`.

A durable item manifest row records source provenance and evidence digests; it
does not copy SCons' internal dependency database.

Updating one complete scope replaces only selected item paths inside that scope
and preserves every sibling scope. Resolving a PR view starts from main and
overlays the sparse PR paths. Removing one PR changes only that PR namespace.

### Durable complete-scope runtime state

Long-lived complete scopes (`main` and safe caller-named scopes) expose one
generic library state contract for hosted CI adapters.

Given a materialized generated build branch, a complete scope name and the
current exact source commit, the library must:

- validate the scope with the **same** complete-scope rules used by build-store
  installation; `pr`, traversing paths and unsafe names are never valid
  complete scopes;
- load and validate an existing complete-scope manifest through the normal
  build-store manifest reader rather than parsing `build.json` in a tool;
- use the stored exact `source_commit` as the incremental base;
- require a full run for the first publication of a caller-named complete
  scope;
- fail if stable `main` has no durable baseline instead of silently treating
  stable integration as a first run;
- prepare selected/current item membership through the existing planner and
  build-store complete-scope functions;
- publish through the existing generated-branch publication API with source
  freshness checking.

A CLI/workflow adapter may supply paths, refs and GitHub outputs, but it must
not implement a second durable-scope validator, manifest parser, selection
policy or publication state machine.

## 13. Pages

Stable Pages content lives at the root of `gh-pages`. PR previews live under
`previews/pr-<number>/`. Consumers may additionally publish complete sites to
safe named top-level subtrees.

Updating one named subtree replaces only that subtree and preserves stable
content, PR previews and every sibling named subtree. Updating stable Pages
preserves PR previews and the explicit set of named subtrees supplied by the
caller; everything else in the stable root is reconciled from the new site so
obsolete stable files cannot survive accidentally.

Named subtree values are one safe path segment and may not be `.git` or
`previews`.

Generic code owns branch/directory mechanics. The consumer owns site content,
styling, the chosen named-subtree keep set and domain text.

## 14. Generated branch publication

Generated branches are never force-pushed.

Publication checks that the source ref still points to the expected source
commit before preparation and immediately before publishing.

Only a real generated-branch race is retried. Authentication, network, invalid
source or other failures stop clearly and must not silently trigger fallback.

## 15. External resources

For packages, images or other external resources, lookup distinguishes:
1. present;
2. explicitly absent;
3. lookup failed.

Only explicit absence may trigger creation/build.

Authentication errors, network errors, timeouts and other lookup failures stop
the run. A full artifact download must not be used merely as an existence test
when metadata/manifest inspection is available.

## 16. Workflow boundary

GitHub Actions YAML may own only:
- event triggers;
- permissions;
- checkout;
- runner/language setup;
- credential/login setup;
- cache transport required by GitHub Actions;
- invocation of a released `tool.cad.ci`;
- GitHub-required artifact upload/download.

Workflow YAML must not own:
- changed-path logic;
- item/step loops;
- dependency ordering;
- consumer commands;
- rebuild/reuse decisions;
- generic retry policy;
- CAD-CI execution timeout policy;
- error-to-fallback reinterpretation.

## 17. Naming

Operator-facing names describe the literal action using normal engineering
terms such as `build`, `test`, `verify`, `publish`, `cleanup` and
`remove_stale_pr_output`.

Do not introduce an abstract CI-theory term when a literal action name exists.

## 18. Error model

The implementation distinguishes at least:
- invalid configuration;
- unknown item/step;
- command exit failure;
- timeout;
- missing declared output;
- unsafe/invalid output;
- bundle/materialization failure;
- external resource absent;
- external lookup/auth/network failure;
- stale source ref;
- generated-branch push race.

Fallback behaviour is explicit per class. A broad non-zero result must never be
translated into an unrelated state.

## 19. Verification layers

`lib.py.cad.ci`:
- unit tests for config, publication and error handling;
- deterministic real-SCons conformance for execution semantics.

`tool.cad.ci`:
- thin CLI exposure tests only.

`tool.cad.ci.test`:
- black-box end-to-end acceptance against one exact released tool/library stack;
- multiple representative top-level consumer cases.

Forge/CAD:
- consumers only after the released generic stack passes all required cases.

## 20. Implementation gate

No further execution-engine implementation is considered complete until the
expected sequences in `docs/scons-acceptance.md` are written first.

If implementation requires behaviour not described in this requirements file,
stop implementation and change/review the contract before continuing.

A prepared Forge or CAD migration should need one implementation run and at
most one consumer-specific correction/confirmation run.


## 21. Durable item-evidence schema migration

Build-store preparation validates freshly generated candidate output against the
current complete-item evidence schema.

For the 0.7.x line the current candidate schema is 2.

Previously published durable build state may still contain complete-item
evidence schema 1. Build-store read/resolve/update operations must continue to
accept stored schema 1 while also accepting stored schema 2.

Unknown item evidence schemas remain invalid.

This compatibility applies only to stored durable state. A newly prepared
candidate from the current library must not silently accept an obsolete schema.


## 22. Local nested item configuration

Nested items must not need to repeat their complete repository path in every
`watch` and step `inputs` field.

### Scoped source paths

The existing list form remains repository-relative for backward compatibility:

```yaml
watch:
  - examples/attach-angle/scpf/**
  - scripts/model_verify.py
```

A mapping form may express item-local and repository-wide patterns explicitly:

```yaml
watch:
  item:
    - scpf/**
    - verification/**
  repo:
    - scripts/model_verify.py
```

The same two forms apply to step `inputs`.

Rules:

- `item` patterns are relative to the directory containing the consumer
  item's `ci.yml`;
- `repo` patterns are relative to the repository root;
- both groups may be present in one mapping;
- after configuration loading, both groups are normalized to the existing
  repository-relative internal representation;
- legacy list syntax and explicit `repo:` patterns reject every `..` segment;
- explicit `item:` patterns may use `..` parent traversal when lexical
  normalization against the consuming item root remains inside the repository;
- item-relative traversal that would escape above the repository root is
  invalid;
- all normalized source patterns reject generated roots `.git/`, `.cache/`
  and `build/`;
- output paths keep their existing item-output-relative semantics.

For a template, `item` paths are resolved relative to the consuming item, not
relative to root `cad-ci.yml`.

For example, from `examples/attach-angle/build123d/ci.yml`:

```yaml
watch:
  item:
    - ../verification/reference_geometry.json
```

normalizes to:

```text
examples/attach-angle/verification/reference_geometry.json
```

This is path normalization only; it does not make the parent directory another
CI dependency/item.

### Root item templates

Root `cad-ci.yml` may define repository-owned named item templates:

```yaml
templates:
  reference-build123d:
    kind: reference
    watch:
      item:
        - "**"
      repo:
        - verification/reference_validation.py
    strategy:
      reuse: true
    steps:
      - id: verify
        inputs:
          item:
            - model.py
          repo:
            - verification/reference_validation.py
        run: [python, ../../../verification/reference_validation.py]
        outputs:
          - reference
```

A consumer item may select at most one template:

```yaml
template: reference-build123d
```

Template names and contents are consumer-owned. Generic CAD-CI assigns no
meaning to template names or to model/reference tool names.

The selected template is the base item mapping. The local `ci.yml` is merged
over it.

Merge rules are intentionally small:

- mapping + mapping: merge recursively;
- local scalar/list/null replaces the template value;
- local item configuration always wins;
- templates do not inherit other templates;
- templates may not define `id`, `template` or `templates`.

Template expansion happens only during configuration loading and does not add
source hashing, freshness checks or rebuild/cache decisions.

### Nested implicit IDs

An explicit `id` remains supported and unchanged.

When `id` is omitted, the default item ID is derived from the
repository-relative item source path by replacing `/` with `-`.

Examples:

```text
examples/simple-box                 -> examples-simple-box
examples/attach-angle/build123d    -> examples-attach-angle-build123d
```

Existing flat paths without `/` keep their previous implicit ID.

If two source paths normalize to the same ID, configuration loading fails with
a duplicate-ID error; CAD-CI does not silently rename either item.

### Hosted-runner behavior

These configuration features do not change selection/execution ownership.

After loading, planner and SCons receive the same normalized Item/Step model as
before. On a fresh hosted runner, Git changed-file selection still decides which
items are requested and selected items are cold unless real SCons state/cache is
present.


## 23. Nested durable item ownership

Durable build storage must support configured item source paths that are
ancestors/descendants of each other.

An item owns only:

- every output path declared by its configured steps;
- its reserved `.cad-ci/` evidence directory.

An item does not own arbitrary sibling or descendant paths under its source-path
directory.

Example:

```text
item A path: examples/attach-angle
A outputs:   solidcraft.json, model_verify

item B path: examples/attach-angle/build123d
B outputs:   references
```

Updating or publishing A must not copy, replace or remove B's
`build123d/references` or `build123d/.cad-ci` content.

### Durable manifest ownership metadata

New item manifest rows keep build manifest schema 1 and additionally record:

```json
"outputs": ["model_verify", "solidcraft.json"]
```

The list is the sorted unique set of consumer output paths declared by all
steps of that item. The reserved `.cad-ci` path is implicit and is not listed.

Stored schema-1 rows created by older releases may omit `outputs`.
They remain readable for backward compatibility.

A stored row without ownership metadata may use the historical whole-tree
behavior only when that item path has no ancestor/descendant relationship with
another item involved in the durable view. If a legacy row is ambiguous in a
nested layout, the operation must fail clearly instead of guessing ownership.

### Copy and replace semantics

Prepare operations copy only declared output paths plus `.cad-ci/`.

Update, resolve and promote operations replace only the owned paths for the
selected/overlay item. Unselected nested parent/child item bytes remain
unchanged.

All selected candidates are validated before the output scope is exposed.

### Configuration collision safety

A repository configuration is invalid when a parent item's declared output path
physically overlaps a nested item's source root.

For parent item `a` and child item `a/child`, parent output paths such as
`child`, `child/result` or an ancestor of `child` are invalid.

This validation is configuration-only. It does not add file hashing, Git
selection or another rebuild engine.


## 24. Operator execution output

Execution logging must remain useful on a long-running hosted CI job.

- stdout/stderr produced while SCons and consumer commands run must be forwarded
  to the caller as the work happens; CAD-CI must not buffer the complete SCons
  process and replay it only after exit;
- before an executed CAD-CI target action, SCons displays a short logical label
  containing the item/step key;
- internal Python action names, target bundle paths and complete resolved source
  lists are implementation detail and must not be used as the normal action
  display line;
- consumer command output remains visible;
- the final structured CAD-CI summary remains the authoritative concise result;
- changing logging must not alter target signatures, dependency ordering,
  selection, CacheDir behavior, output bundles or evidence.


## 25. Durable cleanup for removed configuration items

A partial main update has two independent inputs:

- the selected current items whose candidate output replaces durable state;
- the complete current processed item set from repository configuration.

The sparse candidate alone never implies deletion.

For every previous durable main row:

- if the item is still in the current processed item set and is unselected,
  preserve its manifest row and owned bytes unchanged;
- if the item is selected, replace its owned bytes and row with the validated
  candidate result;
- if the item is absent from the current processed item set, remove its durable
  row and owned bytes.

The resulting main manifest must contain exactly the current processed item
paths. If a currently processed item is neither present in the previous main
baseline nor supplied as a selected replacement, the update is incomplete and
must fail instead of publishing a partial baseline.

Removed-item cleanup uses the same ownership rules as nested durable
replacement:

- rows with current `outputs` ownership metadata remove only those declared
  outputs plus the reserved `.cad-ci/` evidence directory;
- still-configured ancestor/descendant item bytes are preserved;
- an old row without ownership metadata may be removed as a whole tree only
  when it is not nested with another durable/current item;
- ambiguous legacy nested ownership fails clearly instead of guessing.

The source commit of the resulting main manifest is the current update source
commit even when some surviving item rows intentionally keep older item-level
source provenance.

This behavior belongs to the library. CLI/workflow layers may provide the
selected and current item sets, but they must not decide which durable paths to
delete.


## 26. Bounded parallel execution

CAD-CI supports an explicit positive SCons job count.

- the library execution API defaults to `jobs=1` for backward compatibility;
- a supplied job count must be an integer greater than zero and booleans are
  invalid;
- the job count controls only SCons scheduling and never target signatures,
  Git selection, cache keys or publication semantics;
- dependency ordering remains the configured SCons graph;
- independent targets may overlap only when the caller explicitly requests
  `jobs > 1`.

### Direct dependency snapshots

A consumer command must never rely on a mutable shared dependency output root
when parallel execution is enabled.

Before each consumer command:

- every direct dependency final bundle is already current by normal SCons
  dependency ordering;
- CAD-CI materializes that final bundle into a target-private runtime snapshot;
- `current_context().dependency(id).output_root` points to that private
  snapshot for the duration of that consumer command;
- two consumer steps never share the same runtime snapshot directory;
- the snapshot contains exactly the dependency's declared cumulative outputs;
- dependency bundle digest/provenance remains the same value exposed today.

Target-private dependency snapshots live only below the private CAD-CI run
directory. They are not public build output and are never published.

A consumer must treat dependency context as input. Mutating its private snapshot
cannot affect another consumer or public dependency output.

### Previous-step materialization

Ordered steps within one item keep their existing semantics.

The previous step bundle is materialized into that item's normal
`build/<item>/` output root before the next step executes. The SCons step
dependency prevents those steps from overlapping.

### Public output

After SCons completes, active target bundles are materialized into public
`build/<item>/` output exactly as before. Parallel execution therefore does
not change durable build-store or Pages/publication input.

Changing only the requested job count must not invalidate otherwise current
SCons targets.


## 27. Selective-run startup cost

A non-empty selective run must prepare only the SCons target closure that can
actually execute.

- resolve requested target keys and their prerequisite closure from configuration
  metadata before resolving source files;
- do not resolve step input globs for unselected items or for steps outside the
  requested dependency closure;
- enumerate repository source candidates at most once for one SCons invocation
  and reuse that inventory for every active step;
- an empty run performs no source-tree inventory;
- a full run may resolve every processed target because every processed item is
  active;
- active target signatures, dependency ordering, output bundles, evidence and
  SCons dirty/current decisions must remain identical for the same repository
  content and configuration.

Runtime source-safety validation applies to active targets. For example, a
matched symlink in an unselected item's inputs does not block an unrelated
selective run, but selecting that item (or running the complete graph) must
still reject the matched symlink.

This is startup optimization only. It must not introduce a second selection,
fingerprint, cache or execution engine.

## 23. Dependency-output copy steps

A consumer item may need to publish a subset of output that a direct dependency
has already produced. Requiring a consumer subprocess merely to copy that
subset is not useful work and can multiply dependency materialization cost.

A step therefore defines exactly one action form:

```yaml
steps:
  - id: build
    run: [python, build.py]
    outputs: [result.json]
```

or:

```yaml
steps:
  - id: materialize
    copy:
      dependency: shared-batch
      source: "items/{item_path}"
    outputs:
      - result.json
      - generated
```

Requirements for `copy`:

- `dependency` names one item in the consumer item's direct `needs`;
- `source` is a safe relative path below the dependency output namespace;
- the only supported substitution is `{item_path}`, expanded to the current
  consumer item's normalized repository-relative source path;
- after substitution, `source` may not be absolute, contain `..`, enter a
  reserved `.cad-ci` namespace or escape the dependency outputs;
- every declared consumer output `O` is copied from
  `<dependency>/<source>/O` to consumer output path `O`;
- every selected source must exist in the dependency's final bundle and must be
  contained by one of that dependency's declared outputs;
- a copy step must declare at least one output;
- a copy step does not accept `inputs` because its content dependency is the
  direct dependency target plus the copy specification;
- a copy step does not launch a shell or consumer process and has no command
  timeout;
- normal SCons target freshness, `strategy.reuse`, forcing, CacheDir, evidence,
  cumulative step bundles and durable publication still apply.

A copy step must not materialize the dependency's complete output merely to
select a small subtree. The SCons action reads the immutable final dependency
bundle and constructs the consumer target bundle from only the selected source
members.

Ordinary `run` steps retain the target-private complete dependency snapshot
contract required for consumer commands.

Structured evidence distinguishes command and copy actions. Executed copy
targets have action timestamps/duration but no consumer process exit/timeout
semantics. Current/cache-restored copy targets have null action timestamps just
like current/cache-restored command targets.

This capability is generic output ownership. It must not know consumer domain
concepts such as models, references, CAD engines or qualification cases.


## 24. Active direct-dependent command context

A command step may opt in to the already-computed CAD-CI active graph:

```yaml
steps:
  - id: shared-batch
    selection_context: direct_dependents
    run: [python, batch.py]
    outputs: [items]
```

`selection_context` is optional. Supported values are:

- omitted / `none`: existing behavior;
- `direct_dependents`: expose the active direct dependent item ids.

For `direct_dependents`:

- CAD-CI computes the set from the same selected SCons target closure already
  used for execution; no Git diff is re-evaluated;
- a dependent item is included when that item has this item's id in `needs`
  and at least one of the dependent item's configured step targets is active;
- ids are sorted in repository configuration order and unique;
- the command receives
  `CAD_CI_ACTIVE_DEPENDENTS_JSON='["item-a","item-b"]'`;
- the exact ordered list is part of the command target signature and public
  step evidence;
- changing only the active-dependent set makes the target non-current even when
  repository source inputs are otherwise unchanged;
- an explicit full run exposes every processed direct dependent that belongs to
  the active full graph;
- a no-target/no-op run still executes no target and no command;
- the context is read-only execution metadata; CAD-CI does not interpret how a
  consumer command maps ids to domain work;
- `copy:` steps do not accept `selection_context` because they launch no
  consumer command and their source is already explicit;
- environment ownership remains authoritative: caller/repository variables may
  not override `CAD_CI_ACTIVE_DEPENDENTS_JSON`.

The capability must preserve jobs>1 isolation, CacheDir correctness, CURRENT
classification, deterministic evidence and normal dependency ordering.
