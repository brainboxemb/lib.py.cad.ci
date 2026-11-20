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
