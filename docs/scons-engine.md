# SCons execution engine

`lib.py.cad.ci` uses SCons for dependency, signature, incremental-build and
cache decisions. The public CAD CI configuration stays `cad-ci.yml` plus one
`ci.yml` per item.

This follows the proven pattern already used by `tool.scad-project`: the tool
owns the target model and writes a small manifest; a small SCons driver turns
that manifest into SCons targets; SCons decides whether each target must run.

## Responsibilities

### Keep in lib.py.cad.ci

- load and validate `cad-ci.yml` and item `ci.yml`;
- translate item/step configuration to a SCons manifest;
- coarse Git changed-file selection used for PR scope and publication;
- expose dependency output paths to consumer commands;
- collect structured target outcomes;
- prepare and resolve `build/main` and `build/pr/<number>`;
- install stable and preview Pages output;
- publish generated branches safely;
- Git source-freshness checks and generated-branch retry.

### SCons owns

- dependency ordering for execution;
- target signatures;
- action/config signature changes;
- deciding whether a target is current;
- rebuilding dirty prerequisites;
- persistent build state;
- CacheDir lookup and restore;
- target-level incremental execution.

The library must not maintain a second competing fingerprint/reuse engine.

### Remove from the custom runner

The current implementation in `runner.py` and `state.py` contains behaviour
that SCons already owns:

- recursive current-result validation;
- custom input fingerprints;
- custom step fingerprints;
- custom dependency-result fingerprints;
- custom reusable-step decisions;
- manual topological execution ordering;
- manual "stale earlier step" handling.

These mechanisms are transitional and should disappear when the SCons adapter
replaces them.

## Configuration translation

The consumer-facing format remains simple.

Example:

```yaml
# cad-ci.yml
schema: 1

defaults:
  timeout_seconds: 300

items:
  - tool
  - examples/*
```

```yaml
# examples/simple_case/ci.yml
id: simple-case
needs:
  - tool
watch:
  - examples/simple_case/**
steps:
  - id: build
    run: [python, build.py]
    outputs: [built.json]
  - id: verify
    run: [python, verify.py]
    outputs: [verified.json]
```

The adapter creates one SCons target per step. A later step depends on the
previous step target. The first step of an item also depends on the final target
of every item named in `needs`.

The step specification itself is included as a SCons `Value` dependency. A
change to command, outputs, timeout or other execution settings therefore
invalidates the target without a separate CAD-CI fingerprint implementation.

Watched source files are supplied as SCons source dependencies. The resolved
source list must also participate in the target specification so adding or
removing a file matched by a glob invalidates the affected target.

## Output paths

Item output continues to mirror the source item path below the local
`build/` candidate root. This keeps the existing durable build-store contract
unchanged.

The SCons adapter may add internal state below a dedicated cache/state path,
for example:

```text
.cache/cad-ci/scons/
.cache/cad-ci/state/
```

That internal state is not durable build output and is never published to the
`build` branch.

## Structured outcomes

Do not infer SCons decisions from console wording.

Follow the `tool.scad-project` result model and produce structured outcomes per
step target:

- `BUILT`
- `CACHE_RESTORED`
- `CURRENT`
- `ERROR`

A timeout is an execution error with an explicit timeout reason in the action
result. The configured timeout still belongs to CAD-CI config; SCons owns the
target decision, while the CAD-CI action wrapper owns process execution and the
timeout.

The report should include at least:

- item id;
- step id;
- target output(s);
- outcome;
- whether the action executed;
- duration when executed;
- timeout setting;
- source dependencies;
- stable digest of the step specification.

## Partial execution

Partial reruns map to normal SCons target selection.

Requesting one step target asks SCons for that target. SCons evaluates its
prerequisites and rebuilds only prerequisites that are actually dirty. Current
prerequisites remain untouched.

This replaces the custom rule that a partial rerun must fail merely because an
earlier custom state file is missing or stale.

The CLI can keep convenient selectors such as an item or a specific step, but
they resolve to SCons target names rather than to a second execution engine.

## Coarse changed-file selection

Git changed-file selection and SCons incrementality have different purposes.

CAD-CI may use changed paths to choose a small set of top-level item targets for
a PR. Once those targets are selected, SCons alone decides which dependencies
and steps actually execute.

This is the same coarse-selection / fine-incrementality split already proven in
`tool.scad-project`.

## Dependency outputs

Consumer commands may continue to request outputs from declared direct
dependencies. The runtime context must resolve those paths from the generated
SCons/item manifest and the configured output layout.

It must not revalidate dependencies through the old custom runner state.

If SCons successfully made the selected target, its prerequisite targets are
the execution proof. Durable publication may additionally require a generated
result manifest, but that manifest records evidence; it does not make rebuild
decisions.

## Durable build publication

SCons local state is separate from durable consumer build output.

After SCons completes:

- a main run prepares or updates `build/main`;
- a PR run prepares a sparse `build/pr/<number>` overlay;
- overlay resolution, cleanup and Pages publication continue to use the generic
  build-store/publication modules.

Durable build manifests should record source provenance and the selected SCons
result evidence. They should not recreate SCons' internal dependency/signature
database.

## Directory outputs

Directory outputs need an explicit conformance decision before implementation.

The current CAD-CI runner hashes a complete directory tree. Do not assume that a
SCons directory node provides equivalent content semantics.

The real-SCons test suite must prove one supported representation, such as a
generated manifest/stamp target that describes the directory contents. The
chosen representation must detect:

- missing directory output;
- changed nested file;
- added nested file;
- removed nested file;
- CacheDir restore on a fresh workspace.

No consumer migration starts until this behaviour is proven.

## Conformance tests

Use real SCons, following the existing `tool.scad-project` conformance suite.

Required scenarios:

1. cold state/cache -> requested targets `BUILT`;
2. identical second run -> targets `CURRENT`;
3. one private input change -> only dependent target rebuilds;
4. shared dependency change -> all dependent targets rebuild;
5. command/config/timeout change -> affected target rebuilds;
6. missing output with matching CacheDir -> `CACHE_RESTORED`;
7. fresh workspace/state with populated CacheDir -> restore without builder;
8. one requested later step -> only dirty prerequisites plus that step run;
9. command failure -> `ERROR`;
10. timeout -> `ERROR` with timeout reason;
11. directory-output representation behaves as specified;
12. separate cache/state locations do not leak into durable build output.

After these library tests pass, `tool.cad.ci.test` proves the same released
stack from the outside using its representative top-level cases.

## Migration

Do not migrate Forge or CAD while this engine change is incomplete.

The order is:

1. real-SCons conformance tests in `lib.py.cad.ci`;
2. implement the SCons manifest/driver;
3. remove the duplicate custom rebuild/reuse logic;
4. release the library;
5. pin and release `tool.cad.ci`;
6. pin that exact release in `tool.cad.ci.test` and pass all cases;
7. only then migrate Forge and CAD.
