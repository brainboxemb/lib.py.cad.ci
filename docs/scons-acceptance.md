# SCons acceptance matrix

This document defines the expected observable result before implementation is
considered complete.

The tests must use real SCons 4.11.1. Mocks may test helpers, but they do not
replace these sequences.

Vocabulary:
- `B` = BUILT
- `C` = CURRENT
- `R` = CACHE_RESTORED
- `E` = ERROR
- `U` = UNCHANGED materialization
- `M` = RESTORED materialization
- `P` = REPAIRED materialization

## Case 1 - simple two-step item

Repository:

~~~text
simple_case1/
  input.txt
  build.py
  verify.py
  ci.yml
~~~

Steps:

~~~text
build  -> output build.json
verify -> output verify.json
~~~

Inputs:
- build: `input.txt` + `build.py`
- verify: `verify.py`

Expected runs:

| Run | Change/request | build | verify | Complete item |
| --- | --- | --- | --- | --- |
| 1 | cold full run | B | B | pass |
| 2 | identical full run | C | C | pass |
| 3 | change input.txt | B | B | pass |
| 4 | identical after run 3 | C | C | pass |
| 5 | change verify.py only | C | B | pass |
| 6 | identical after run 5 | C | C | pass |

Run 5 is a critical requirement: a verify-only input change must not rebuild the
build step.

## Case 2 - step configuration invalidation

Start from Case 1 after a current run.

Expected runs:

| Change | build | verify |
| --- | --- | --- |
| verify timeout changes | C | B |
| verify command changes | C | B |
| verify output declaration changes | C | B |
| build command changes | B | B |
| build timeout changes | B | B |

Changing descriptive `kind` or Git-only `strategy.affected` must not invalidate
either target.

Changing `strategy.reuse` is execution-significant and invalidates the affected
item's target policy.

## Case 2A - repository variables

Root configuration contains:

~~~yaml
variables:
  MODEL_MODE: "first"
~~~

The build command writes `MODEL_MODE` to its declared output.

Expected sequence:

| Run | Change | build |
| --- | --- | --- |
| 1 | cold, inherited MODEL_MODE=caller | B, output is `first` |
| 2 | identical | C |
| 3 | root variable changes to `second` | B, output is `second` |
| 4 | identical | C |

This proves both required properties: repository configuration overrides an
inherited value, and the mapping participates in the SCons target signature.

Invalid variable names, reserved prefixes and non-string values fail during
configuration loading before SCons starts.


## Case 2B - built-in CAD builder resolution

Root configuration:

~~~yaml
runtimes:
  reference: ghcr.io/example/cad-reference:v1.2.3
items:
  - models/*
~~~

Items:

~~~yaml
# models/a/ci.yml
id: a
builder: build123d

# models/b/ci.yml
id: b
builder: cadquery
~~~

Expected:

1. both items load without root `builders:` aliases;
2. both retain their public builder names and have no repository builder path;
3. both receive one normal copy step owning `model.stl`;
4. both depend on the same internal `reference` producer;
5. that producer is one ordinary Item with one command step and
   `selection_context: direct_dependents`;
6. a request for only `a` gives the producer active dependents `["a"]`;
7. a request for `a` and `b` gives it `["a","b"]` and still only one
   producer target;
8. runtime role/image and active-dependent set participate in producer target
   identity;
9. changing the runtime image or built-in batch contract invalidates the
   producer normally;
10. the model files contain no producer id, copy action or runtime command.

Invalid configuration fails before SCons when:
- root `builders:` attempts to define `build123d` or `cadquery`;
- the required `reference` runtime role is missing;
- the runtime image is untagged or uses `latest`;
- item-local `model.py` is missing.

## Case 2C - built-in shared runtime batch

Use a fake Docker process for focused library tests and the real immutable
`cad-reference` image in external acceptance.

With one active build123d model and one active CadQuery model:

1. the producer writes one manifest containing both model ids, item paths,
   builder names and output paths;
2. exactly one `docker run` starts the compatible `reference` runtime;
3. repository source is mounted read-only and the producer output root is
   writable;
4. both model sources execute in that same runtime process;
5. build123d and CadQuery each write their own canonical `model.stl`;
6. the producer writes per-model pass/error rows plus aggregate status;
7. failure of one case does not prevent a later case from being attempted;
8. any case failure fails the producer target overall;
9. normal dependency-copy validation projects only the requested model's
   declared output.

## Case 2D - batch selection/cache safety

Use the existing Case 32 active-direct-dependent semantics.

Sequence:

1. select only model A -> producer receives `["A"]`, runs once, A copies;
2. repeat identical selection -> producer may be CURRENT/CACHE_RESTORED;
3. select only model B -> producer signature differs and cannot reuse A's
   partial batch as current;
4. select A + B -> one producer run receives both ids;
5. full run -> producer receives every processed built-in model using that
   runtime role;
6. no selected built-in model -> producer does not start.

No per-model runtime/container-start path is accepted.

## Case 3 - resolved input membership

Build step input pattern:

~~~text
simple_case1/input/**
~~~

Sequence:
1. cold full run -> build B, verify B;
2. identical -> build C, verify C;
3. clear CacheDir, then add a new matched file -> build B, verify B;
4. identical -> build C, verify C;
5. clear CacheDir, then remove the matched file -> build B, verify B.

CacheDir is deliberately cleared before the membership transitions because this
case proves invalidation/action execution. Without clearing it, returning to an
earlier exact signature may legitimately produce CACHE_RESTORED instead of
BUILT; that behaviour is tested separately by the cache-restore cases.

This proves glob membership is part of the target signature, not only contents
of files that happened to exist during the previous run.

## Case 4 - shared dependency item

Repository:

~~~text
dependency_case/
  library/
    ci.yml
  app/
    ci.yml
~~~

`app needs [library]`.

Expected runs:

| Run | Change | library | app build | app verify |
| --- | --- | --- | --- | --- |
| 1 | cold | B | B | B |
| 2 | none | C | C | C |
| 3 | app private input | C | B | B |
| 4 | library input | B | B | B |

Before app build executes, the library output must already be materialized and
available through `current_context().dependency("library")`.

## Case 4A - earlier dependency output propagates through final bundle

Dependency has two steps:

~~~text
prepare -> finish
~~~

Consumer reads the prepare output. The finish step writes a constant file that
does not depend on prepare output.

Sequence:
1. cold -> dependency prepare B, finish B, consumer B;
2. none -> all C;
3. change only prepare input -> dependency prepare B, finish B, consumer B.

The finish step's own declared output may remain byte-identical, but its
cumulative final bundle must change because it also contains the changed
prepare output. This proves the final dependency bundle represents the complete
item state.

## Case 5 - two independent consumers of one dependency

Graph:

~~~text
       library
       /     \
      a       b
~~~

Sequence:
1. cold -> library B, a B, b B;
2. none -> all C;
3. change a-only input -> library C, a B, b C;
4. change library input -> library B, a B, b B.

This proves SCons owns dependency fan-out and selective rebuild.

## Case 6 - exact step

Three-step item:

~~~text
prepare -> build -> verify
~~~

After one current full run:

~~~text
cad-ci run --item item --step build
~~~

Expected:
- prepare C;
- build B because exact step is explicitly forced;
- verify is not requested and has no run outcome;
- complete item evidence is removed because the final target was not ensured.

A second full run afterward:
- prepare C;
- build C if forced build produced the same deterministic bundle/signature;
- verify is evaluated against build and becomes B if its prerequisite target
  signature/result changed, otherwise C according to SCons content decision;
- complete item evidence is restored after success.

The implementation test must use deterministic bundle contents so the expected
downstream result is stable and documented.

## Case 7 - until step

Three-step item, initially current:

~~~text
cad-ci run --item item --until build
~~~

Expected:
- prepare C;
- build C;
- verify not requested;
- no consumer action executes;
- complete item evidence is removed because the requested target is not final.

Then change prepare input and run the same command:
- prepare B;
- build B;
- verify not requested;
- complete item evidence remains absent.

## Case 8 - from step

Three-step item, initially current:

~~~text
cad-ci run --item item --from build
~~~

Expected:
- prepare C;
- build B (forced);
- verify B (forced);
- complete item evidence pass.

This command is the deterministic operator control for "rerun from build".

## Case 9 - failed step recovery

Two-step item:
- build succeeds;
- verify exits 3.

First run:
- build B;
- verify E with status `fail` and exit code 3;
- no successful verify bundle exists;
- no complete item evidence exists.

After fixing verify.py only:
- build C;
- verify B;
- complete item evidence pass.

No manual removal of custom state files is required.

## Case 10 - timeout recovery

Step timeout: 1 second.
Command sleeps 5 seconds.

First run:
- target E;
- status `timeout`;
- exit code null;
- timeout_seconds 1;
- no successful target bundle;
- no complete item evidence.

Change command to complete normally:
- target B;
- complete item evidence pass.

Changing timeout from 1 to 2 on a successful current step later invalidates only
that step and its downstream dependants.

## Case 11 - missing declared output

Command exits 0 but does not create its declared output.

Expected:
- target E;
- status `output_error`;
- error names the missing output;
- no successful bundle;
- no complete item evidence.

After correcting the command:
- target B.

## Case 12 - output ownership validation

Configuration loading must reject:
- consumer output under `.cad-ci/`;
- duplicate output path in two steps;
- parent/child overlap between two step outputs;
- absolute output path;
- output path containing `..`.

These are configuration errors and SCons must not start.

## Case 13 - directory output

One step declares:

~~~text
outputs:
  - generated
~~~

Action creates:
- `generated/a.txt`;
- `generated/nested/b.txt`;
- empty directory `generated/empty/`.

Expected:
1. cold -> B, materialization U (the successful action already wrote the output);
2. identical -> C, materialization U;
3. delete local `generated/` but keep target/state -> C, materialization M;
4. tamper nested file -> C, materialization P;
5. add undeclared file inside generated -> C, materialization P and extra file
   removed;
6. delete internal target + SCons state, keep CacheDir, delete build -> R,
   materialization M.

The final output tree after runs 3-6 must match bundle metadata exactly,
including empty directories.

## Case 14 - explicit CacheDir restore capability

This case proves optional SCons CacheDir capability. It does not represent the
default hosted-runner path.

Two independent targets A and B.

After cold run, deliberately preserve only:
- repository sources;
- `.cache/cad-ci/scons/cache/`.

Delete:
- `build/`;
- SCons state;
- private target bundles;
- run evidence.

Next full run:
- A R;
- B R;
- no consumer action executes;
- outputs are materialized;
- complete item evidence is recreated.

Then change only A source and repeat with a fresh local state:
- A B;
- B R.

## Case 15 - cache namespace compatibility

Changing engine schema must prevent use of target entries created under the old
engine schema.

Changing only source checkout absolute path must not invalidate otherwise
identical target signatures/cache entries.

## Case 16 - reuse false

Item has:

~~~yaml
strategy:
  reuse: false
~~~

Expected:
1. cold -> B;
2. identical -> B again;
3. private CacheDir contains no reusable target for this item's active steps.

A dependency item with normal reuse policy remains C/R as appropriate.

## Case 17 - dependency context restrictions

Consumer directly needs `library`.

Allowed:
- `context.dependency("library")`;
- declared `output("dist")`.

Rejected:
- undeclared dependency ID;
- undeclared output name;
- missing final dependency bundle;
- materialized dependency output that does not match bundle metadata.

Context validation must not trigger builds.

## Case 18 - evidence namespace

After a successful full two-step run:

~~~text
build/item/
  <consumer outputs>
  .cad-ci/
    item.json
    steps/
      build.json
      verify.json
~~~

Assertions:
- evidence schema matches the design;
- step outcome matches actual B/C/R result;
- bundle digest matches the internal target;
- complete item evidence names the configured final step;
- no `.cache` content appears under `build/item`.

After a non-final partial run, `.cad-ci/item.json` is absent.

## Case 19 - Git selection versus SCons selection

Two items A and B, no dependency.

Git diff changes only A watched path.

`cad-ci plan`:
- top-level selected item: A;
- B not selected.

`cad-ci run --base ... --head ...`:
- requests A final target only;
- B is not evaluated by SCons.

With B depending on A:
- Git selection propagates according to `affected` strategy;
- SCons then owns runtime dependency traversal.


## Case 19A - fresh hosted runner without cache

Repository has two independent items A and B with disjoint watched paths.

Create two exact Git revisions:
1. base revision contains both items;
2. head revision changes only a source watched by A.

Clone the head revision into a fresh workspace. The clone must contain neither
`build/` nor `.cache/cad-ci/`.

Expected sequence:

1. `changed_files(base, head)` returns A's changed path;
2. `affected_items()` returns only A;
3. execute that selection through `run_repository()`;
4. A's requested step is `BUILT`;
5. B has no SCons outcome, no consumer action and no `build/B` output.

This is the canonical hosted-runner incremental behavior. It must pass without
restoring any SCons cache or target state.

## Case 20 - direct fan-in selection

Graph:

~~~text
a ---\
b ----> summary   (summary affected: direct)
c ---/
~~~

Change only a.

Expected Git selection:
- a selected;
- summary not automatically selected;
- b/c not pulled in merely because summary exists.

Explicitly request summary:
- SCons requests summary final target;
- required a/b/c prerequisites are made current;
- current siblings do not execute.

## Case 20A - explicit process selection

Repository:

~~~text
library
model-a
model-b
~~~

Configuration:
- library: process omitted (effective true);
- model-a: `process: true`, needs library;
- model-b: `process: false`, needs library.

Expected behavior:

| Request/change | library | model-a | model-b |
| --- | --- | --- | --- |
| full run | requested as needed/current | requested | absent |
| model-a watched change | dependency | selected | absent |
| model-b watched change | absent | absent | absent |
| library watched change | selected | selected by dependency fan-out | absent |
| explicit model-b request | error before SCons | error | error |

Additional configuration assertions:
- omitted `process` is effective true;
- non-boolean `process` is invalid;
- processed item depending on `process: false` is invalid;
- a non-processed item may depend on a processed item;
- changing only `process: false -> true` in that item's `ci.yml` makes the
  newly active item eligible and selects it from that config change;
- changing `process: true -> false` excludes it immediately;
- existing `affected: changed/direct/always` semantics remain unchanged among
  processed items.

This case is selection/configuration behavior. It must not add `process` to
SCons target signatures.

## Case 21 - durable main build

Given complete successful candidate items A and B:

Prepare main:
- copies A and B consumer output plus `.cad-ci` evidence;
- creates `build.json` with source SHA and final evidence fields;
- publishes no `.cache` data.

A candidate without valid complete item evidence is rejected.

## Case 22 - sparse PR overlay

Main baseline contains A and B.

PR selected item = A.

Expected overlay:
- contains A only;
- contains one PR manifest row for A;
- does not copy B.

Resolved PR view:
- B comes byte-for-byte from main;
- A comes from PR overlay.

## Case 23 - main update

Main baseline A1/B1.
Candidate A2 only.

Expected new main:
- A = A2;
- B = byte-identical B1;
- manifest row for A updated;
- B manifest row preserved.

All replacement candidates are validated before any output tree is exposed.

## Case 24 - Pages isolation

Stable site exists plus previews PR 1 and PR 2.

Expected:
- stable update preserves both previews;
- PR 1 update preserves stable and PR 2;
- PR 1 cleanup preserves stable and PR 2.

## Case 24A - post-build Pages renderer

Root configuration maps `pages-site` to one repository-owned builder and
configures:

```yaml
publication:
  pages:
    builder: pages-site
    output: site
```

The builder contains exactly one command step declaring `site`.

Expected:

1. the normal selected CAD-CI graph runs once and finishes before publication;
2. the complete durable scope is prepared and published before the renderer
   starts;
3. the renderer receives the materialized complete scope, logical scope,
   source SHA/ref and the exact generated build commit;
4. it receives one fresh temporary `CAD_CI_OUTPUT` and runs from the
   repository root;
5. successful `site` output is validated with the normal safe output rules,
   then generic `provenance.json` is written and existing stable/named Pages
   preservation semantics apply;
6. the renderer is not a SCons target and creates no second CAD-CI graph,
   target bundle or cache record;
7. non-zero exit, timeout, missing output or symlink/unsafe output fails Pages
   publication after build publication and does not rewrite the generated build
   commit;
8. item/output Pages mode retains its existing behavior.

Invalid configuration is rejected when:
- both `item` and `builder` are configured;
- neither is configured;
- the builder alias is unknown;
- the publication builder contains multiple steps;
- its step is a copy action rather than a command;
- the configured output is not declared by the command step.

## Case 25 - source freshness and publication race

Publication uses expected source SHA.

Expected:
- moved source ref -> fail before publish;
- real generated-branch non-fast-forward race -> retry from new generated head;
- auth failure -> fail, no retry-as-missing;
- network failure -> fail, no retry-as-missing.

## Case 26 - external resource states

Generic external lookup returns one of:
- PRESENT;
- ABSENT;
- ERROR.

Expected:
- PRESENT -> use resource;
- ABSENT -> creation/build may run;
- auth/network/timeout -> ERROR and stop.

A timed-out download/pull is never translated to ABSENT.

## Case 27 - tool.cad.ci.test black-box mapping

The permanent acceptance repository must contain independent top-level cases
that cover this matrix without domain-specific Forge/CAD behaviour.

Minimum mapping:

~~~text
simple_case1/          -> cases 1-3, 6-8
more_complex_case2/    -> cases 4-5, 15-16
dependency_case/       -> cases 4-5, 17, 20
partial_rerun_case/    -> cases 6-10
directory_output_case/ -> cases 11-14
publish_case/          -> cases 18-25
external_error_case/   -> case 26
~~~

The test repository consumes one exact released `tool.cad.ci` revision. It does
not develop generic behaviour locally.

## Release gate

The SCons engine may be released only when:
1. this matrix exists before the final implementation;
2. every applicable library conformance test is green;
3. obsolete custom rebuild/fingerprint tests/code are removed;
4. main CI is green;
5. release is published only after that exact main commit passes CI;
6. the released tool pins the released library;
7. `tool.cad.ci.test` passes against that exact tool revision.

Only after all seven conditions are true may Forge or CAD migration resume.


## Timing evidence acceptance

For a cold successful run:

- report has non-null `started_at` and `finished_at`;
- each BUILT row has non-null action `started_at` and `finished_at`;
- each public step evidence file has the same action timestamps plus run-level
  `run_started_at` / `run_finished_at`;
- complete item evidence has the same run-level timestamps;
- every timestamp matches the documented UTC `...Z` format;
- `duration_seconds` remains present.

For a second unchanged run:

- CURRENT rows have `started_at: null` and `finished_at: null`;
- public step evidence also has null action timestamps;
- run-level timestamps are still present and describe the new run.

For a fresh CacheDir restore:

- CACHE_RESTORED rows and public step evidence have null action timestamps;
- run-level timestamps are present.

For timeout or command failure after consumer-command execution:

- action start and finish timestamps are present.

For a materialization/setup failure before consumer-command execution:

- action start and finish timestamps are null.


## Case 23A - nested durable item ownership

Repository items:

```text
parent path: cases/model
  outputs: model.json

child path: cases/model/reference
  outputs: reference.json
```

Candidate tree contains both complete item results.

Required sequences:

1. prepare main with parent + child:
   - succeeds;
   - parent evidence/output exists;
   - child evidence/output exists;
   - manifest has both rows with `outputs` metadata.

2. prepare PR overlay with parent + child:
   - succeeds without directory collision;
   - both items validate independently.

3. prepare PR overlay with child only:
   - contains child output/evidence only;
   - no parent output/evidence is imported merely because the child path is
     nested below it.

4. update existing main with parent only:
   - parent output/evidence changes;
   - child output/evidence bytes are unchanged.

5. update existing main with child only:
   - child output/evidence changes;
   - parent output/evidence bytes are unchanged.

6. resolve/promote a new-format parent overlay:
   - replaces parent ownership only;
   - nested child remains intact.

7. candidate parent directory contains descendant child output:
   - preparing parent alone does not import child output.

8. legacy schema-1 non-nested row without `outputs`:
   - remains readable.

9. legacy row without `outputs` that would replace a nested item:
   - fails with an explicit ambiguous-ownership error.

10. configuration where parent output overlaps child item root:
   - fails during repository configuration loading.


## Case 27 - bounded parallel consumers with one shared dependency

Repository:

```text
library
  step: build -> lib.txt

consumer-a
  needs: library
  step: test -> a.txt

consumer-b
  needs: library
  step: test -> b.txt
```

The two consumer commands deliberately overlap (for example by recording
start/finish times around a short sleep) and read `lib.txt` from dependency
context both before and after the overlap.

Run with `jobs=2`.

Required:

1. library executes once;
2. both consumers execute;
3. consumer action intervals overlap;
4. each consumer receives a different target-private dependency output root;
5. both snapshots contain the exact library bytes for the entire command;
6. public `build/library/lib.txt` is valid after the run;
7. both consumer outputs/evidence are valid;
8. run report records `jobs: 2`.

Run the same repository with default jobs omitted.

Required:

- report records `jobs: 1`;
- consumers do not overlap.

## Case 28 - parallel restore from missing public dependency output

Use Case 27 after one successful run.

Delete public `build/library/lib.txt` while preserving SCons target bundles and
state. Keep the two consumer inputs dirty so both consumer actions execute.

Run with `jobs=2`.

Required:

- library target itself may remain CURRENT;
- both consumers still receive valid private snapshots from the immutable final
  dependency bundle;
- no consumer writes/restores the shared public library path while its command
  runs;
- both consumers pass;
- post-run active materialization restores public
  `build/library/lib.txt`;
- no bundle, snapshot or public output corruption occurs.

## Case 29 - parallel ordering and failure

Repository has:

- one two-step item where step B depends on step A;
- one independent item;
- `jobs=2`.

Required:

- A and B never overlap;
- the independent item may overlap A or B;
- B sees A output through normal previous-step item materialization;
- a failing independent action produces normal structured ERROR evidence;
- successful target evidence remains complete;
- SCons return/failure semantics remain the documented authority.

## Parallel release gate addition

Before release of bounded parallel execution:

- Cases 27-29 are covered by library conformance tests;
- the permanent external acceptance repository contains at least one
  `jobs > 1` shared-dependency black-box case;
- the released tool exposes jobs without implementing its own target loop.


## Case 30 - selective startup resolves only the active closure

Repository contains:
- one selected item with two steps;
- one direct dependency;
- many unrelated processed items with their own input patterns;
- one unrelated item whose input pattern matches a symlink.

Run only the selected item.

Required:

1. requested keys resolve to the selected final step;
2. active keys contain only the selected item's prerequisite steps plus its
   direct dependency closure;
3. repository source candidates are enumerated once for the invocation;
4. full target specifications are emitted only for active keys;
5. input patterns for unrelated items are never resolved;
6. the unrelated matched symlink does not block this selective run;
7. selected/dependency target signatures and normal SCons outcomes match the
   pre-optimization semantics.

Then request the unrelated symlink-owning item.

Required:

- its active input resolution rejects the matched symlink exactly as before.

Run a complete graph.

Required:

- every processed target is active;
- the repository source inventory is still enumerated once;
- normal full-run output/evidence semantics are unchanged.

The regression proof must assert structural work reduction (one inventory and
active-only specs) rather than a fragile wall-clock threshold.

## Case 31 - dependency-output copy without complete dependency snapshot

Repository:

```text
batch/
  final output:
    items/
      consumer-a/
        result.txt
        generated/a.txt
      consumer-b/
        result.txt
        generated/b.txt

consumer-a/
consumer-b/
```

Both consumers directly need `batch` and use:

```yaml
steps:
  - id: materialize
    copy:
      dependency: batch
      source: "items/{item_path}"
    outputs:
      - result.txt
      - generated
```

Use item paths `consumer-a` and `consumer-b`.

Required sequences:

1. cold run with jobs=2:
   - batch BUILT once;
   - both copy targets BUILT;
   - both consumer outputs exactly match their selected dependency subtrees;
   - copy target action intervals may overlap;
   - no consumer subprocess/script is required;
   - no complete batch output is materialized below either copy target's
     target-private dependency snapshot root;
   - public batch output and both consumer outputs are valid after post-run
     materialization.

2. identical run:
   - batch CURRENT;
   - both copy targets CURRENT;
   - no copy action timestamps are present.

3. change only bytes below `items/consumer-a` in the batch input/result:
   - batch BUILT;
   - consumer-a copy BUILT;
   - consumer-b may be BUILT because its direct dependency target changed under
     the current item-level dependency signature model; correctness requires its
     output remain byte-identical.
   - no stale output survives.

4. remove public consumer outputs while preserving valid target/state:
   - copy target may remain CURRENT;
   - post-run materialization restores the consumer outputs from its own target
     bundle.

5. fresh CacheDir restore:
   - copy target restores normally with no copy action execution;
   - output materializes correctly.

6. configuration errors before SCons:
   - copy dependency is not in direct `needs`;
   - both `run` and `copy` are present;
   - neither `run` nor `copy` is present;
   - copy step has no outputs;
   - copy step declares `inputs`;
   - unsafe/absolute/traversing source;
   - unknown source substitution token.

7. execution errors:
   - selected source/output is absent from the dependency final bundle;
   - source root is not contained by a dependency-declared output;
   - dependency bundle contains a link or unsafe selected member.

8. nested consumer path:
   - item path `examples/model-a/build123d`;
   - `source: "items/{item_path}"` resolves exactly to
     `items/examples/model-a/build123d`;
   - only that subtree is projected.

Evidence assertions:

- report/public step evidence identify `action_type=copy`;
- successful BUILT copy has timestamps/duration, null exit/timeout;
- CURRENT/CACHE_RESTORED copy has null action timestamps;
- target/bundle digests and output manifest follow normal evidence semantics;
- complete item evidence remains valid.

## Dependency-copy release gate addition

Before releasing #79:

- Case 31 exists in library conformance tests;
- existing command-step Cases 4, 17, 27-29 remain green unchanged;
- engine schema invalidation is proven;
- the thin tool consumes the released library without implementing copy logic;
- the permanent external acceptance repository proves at least one copy target
  using the exact released tool/library pair;
- only then may Forge replace projection-only materializer commands and remeasure
  its full-run tail.


## Case 32 - active direct-dependent batch context

Repository:

```text
batch/
consumer-a/ -> needs: [batch]
consumer-b/ -> needs: [batch]
unrelated/
```

The batch command has
`selection_context: direct_dependents` and writes the received JSON list into
its declared output.

Required sequences:

1. select only consumer-a:
   - active closure contains batch + consumer-a path;
   - batch command receives exactly `["consumer-a"]`;
   - batch target is BUILT;
   - consumer-b is not active.

2. repeat identical consumer-a selection:
   - batch is CURRENT (or CACHE_RESTORED in a fresh equivalent workspace);
   - stored evidence reports the same active-dependent list.

3. select only consumer-b with unchanged repository source:
   - batch must rebuild because its target signature changes;
   - command receives exactly `["consumer-b"]`;
   - it must not reuse the consumer-a partial batch result as CURRENT.

4. select consumer-a and consumer-b together with jobs=2:
   - batch runs once;
   - command receives both ids in repository order;
   - both consumers run after the batch;
   - no race/shared mutable selection file exists.

5. explicit full run:
   - batch receives both processed direct dependents;
   - unrelated item is absent unless it directly needs batch.

6. no-target/no-op run:
   - target count remains zero;
   - batch command does not start.

7. configuration:
   - omitted selection_context keeps existing behavior;
   - unknown values fail before SCons;
   - `copy:` + selection_context fails before SCons.

8. effective direct-dependent configuration changes with the same selected IDs:
   - the batch target signature changes;
   - the batch must not remain CURRENT solely because the ID list is unchanged;
   - this includes behavior inherited through root item templates;
   - unrelated root configuration does not become a coarse batch input.

9. evidence/cache:
   - public step evidence contains `active_dependents`;
   - engine/report/evidence schema versions reflect the new contract;
   - fresh CacheDir cannot restore a batch built for a different dependent set.

## Release gate addition for #83

Before release:

- Case 32 exists in library conformance tests;
- existing selective-startup, dependency-copy, jobs>1 and cache cases remain
  green;
- thin tool changes contain no selection implementation;
- external acceptance proves the exact released stack;
- Forge #661 remains blocked until that acceptance is complete.


## Shared builder configuration

Given a root builder alias `shared: ci/builders/shared`, two independent items
that each contain `builder: shared`, and one
`ci/builders/shared/builder.yml`:

1. repository loading resolves both items to the same builder directory without
   requiring an inline `run` command in either item `ci.yml`;
2. a Git change below `ci/builders/shared/**` selects both processed items;
3. the builder directory appears in command-step source dependencies even when a
   builder step declares narrower explicit item inputs;
4. changing builder implementation makes a requested target dirty under SCons;
5. a running builder command receives the item source directory through
   `CAD_CI_ITEM_PATH` and the shared implementation directory through
   `CAD_CI_BUILDER_PATH`;
6. item configuration containing both `builder` and `steps`, or neither, is
   invalid;
7. legacy schema-1 item-local steps retain their prior execution semantics.

Repository-owned builder acceptance remains unchanged. Built-in generic engine
builders additionally use Cases 2B-2D; they lower to the same normal Step,
dependency-copy and SCons mechanisms rather than defining a second scheduler.

## Case 33 - recursive wildcard prefix path matching

Given repository-relative paths:

```text
models/components/hub75_panel/detailed/scpf/model.py
examples/simple-box/scpf/model.py
folder/file.txt
```

Required:

1. `models/*/*/*/scpf/**` matches the nested HUB75 source;
2. `*/scpf/**` matches the example source tree;
3. literal `folder/**` matches both `folder` and its descendants;
4. unrelated sibling paths do not match;
5. Windows separators are normalized before matching;
6. the fix uses the existing source inventory and changes no planner/SCons
   execution semantics.
