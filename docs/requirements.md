# CI requirements

This document is the product contract for the generic CAD CI stack. It defines
observable behaviour. Implementation details belong in `docs/scons-engine.md`
and expected test sequences in `docs/scons-acceptance.md`.

A Forge or CAD consumer must not migrate until one exact released
`lib.py.cad.ci` + `tool.cad.ci` stack satisfies this contract and
`tool.cad.ci.test` proves it end to end.

## 1. Configuration ownership

The root `cad-ci.yml` owns repository-wide CI settings and item discovery.

Each item `ci.yml` owns:
- item ID and descriptive kind;
- optional explicit `process` participation;
- direct item dependencies;
- coarse Git-selection paths;
- affected-item strategy;
- ordered steps;
- exact step inputs where narrower inputs are useful;
- commands;
- declared outputs;
- execution timeout;
- cache/reuse policy.

Generic behaviour must not be hidden in GitHub Actions YAML or consumer helper
scripts. Generic code must not know Forge, SolidCraft, model, qualification,
integration, native or gate semantics.

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

When `inputs` is omitted, the step inherits the item's `watch` patterns so
existing/simple consumers remain valid.

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
- `pr/<number>/`: sparse overlay containing only selected PR item paths.

Publication validates successful complete-item evidence from
`.cad-ci/item.json`.

A durable item manifest row records source provenance and evidence digests; it
does not copy SCons' internal dependency database.

Updating main replaces only selected item paths. Resolving a PR view starts from
main and overlays the sparse PR paths. Removing one PR changes only that PR
namespace.

## 13. Pages

Stable Pages content lives at the root of `gh-pages`. PR previews live under
`previews/pr-<number>/`.

Updating stable Pages preserves previews. Updating or deleting one preview
preserves stable content and all other previews.

Generic code owns branch/directory mechanics. The consumer owns site content,
styling and domain text.

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
- absolute paths, `..` escapes and generated-root paths remain invalid;
- output paths keep their existing item-output-relative semantics.

For a template, `item` paths are resolved relative to the consuming item, not
relative to root `cad-ci.yml`.

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
