# CI requirements

This document is the contract for the generic CAD CI stack. A real consumer
must not be migrated until the released library and tool satisfy this contract
and `tool.cad.ci.test` proves the complete stack end to end.

## 1. Configuration

The root `cad-ci.yml` owns repository-wide CI settings and lists item folders.
Each item `ci.yml` owns its dependencies, watched inputs, ordered steps,
outputs and step-specific overrides.

Generic behaviour must not be hidden in GitHub Actions YAML or consumer helper
scripts. The generic library must not know Forge, SolidCraft or CAD-domain
semantics.

## 2. Step execution

Steps run in declared order from the item folder. The runner supports complete
runs, one exact step, `--from` and `--until`.

A partial run may use only current prerequisite state. It must never claim that
the complete item was rebuilt when the final required step did not run.

Each item writes only below its own mirrored build path.

## 3. Timeouts

The repository can define a default step timeout in `cad-ci.yml`. A step may
override that value in its own `ci.yml`.

Timeout values are validated. A timed-out process is reported as a timeout,
not as an ordinary command exit failure, and its result is never reusable.

A timeout must never be interpreted as proof that an external resource does
not exist.

## 4. Reuse

Reuse depends on:
- watched inputs;
- item configuration;
- dependency results;
- step configuration;
- previous step result;
- declared output hashes.

A changed timeout or other step setting changes the step fingerprint. Failed,
timed-out, partial or incomplete output is never reusable.

## 5. Planning

Changed files select affected items deterministically. Dependency changes
select dependants. Explicit item selection expands dependencies before the
selected item.

A direct-only fan-in item must not widen an ordinary changed-file plan.

The complete plan can be printed without executing any item command.

## 6. Durable build output

Local build output mirrors item source paths.

`build/main` is the complete accepted baseline.
`build/pr/<number>` is a sparse overlay containing only rebuilt PR items.

Updating main replaces only selected item paths. Resolving a PR view starts
from main and overlays the PR paths. Removing one PR changes only that PR
namespace.

Durable item state contains enough source and fingerprint information to prove
which result it represents.

## 7. Pages

Stable Pages content lives at the root of `gh-pages`. PR previews live under
`previews/pr-<number>/`.

Updating stable Pages preserves previews. Updating or deleting one preview
preserves stable content and all other previews.

Generic code owns branch and directory mechanics. The consumer owns site
content, styling and domain text.

## 8. Generated branch writes

Generated branches are never force-pushed.

Publication checks that the source ref still points to the expected source
commit before preparing and immediately before publishing.

Only an actual generated-branch race is retried. Authentication, network,
invalid source or other errors fail clearly and must not silently trigger
fallback behaviour.

## 9. External resources

When CI depends on an external package, image or other resource, its lookup
must distinguish three states:

1. present;
2. explicitly absent;
3. lookup failed.

Only state 2 may trigger creation or build. Authentication errors, network
errors, timeouts and other lookup failures must stop the run.

An existence check should not download a complete large artifact when registry
metadata can answer the question.

## 10. Workflow boundary

GitHub Actions YAML may own:
- triggers;
- permissions;
- source checkout;
- runner/language setup;
- credentials and login;
- invocation of released `tool.cad.ci`;
- artifact upload/download required by GitHub Actions.

Workflow YAML must not own:
- changed-path selection;
- dependency ordering;
- item loops;
- item commands;
- reuse decisions;
- generic retry logic;
- execution timeouts that belong to CI config;
- fallback rules that reinterpret an error as missing state.

## 11. Names

Operator-facing names describe the actual action using normal engineering
words such as `build`, `test`, `verify`, `publish`, `cleanup` and
`remove_stale_pr_output`.

Do not introduce abstract CI-theory names when a literal action name exists.

## 12. Error model

The implementation must distinguish at least:
- invalid configuration;
- stale or missing prerequisite;
- command exit failure;
- timeout;
- missing declared output;
- external resource absent;
- external lookup/auth/network error;
- stale source ref;
- generated-branch push race.

Fallback behaviour is defined per error class. A broad non-zero result must not
be translated into an unrelated state.

## 13. Verification layers

`lib.py.cad.ci` unit tests prove individual generic functions and error
classes.

`tool.cad.ci` tests prove CLI exposure only.

`tool.cad.ci.test` proves the complete released stack using multiple
representative top-level cases, for example:

```text
simple_case1/
more_complex_case2/
dependency_case/
partial_rerun_case/
publish_case/
timeout_case/
external_error_case/
```

Each case proves one coherent contract and should fail in a way that makes the
broken contract obvious.

## 14. Migration rule

Before a Forge or CAD migration starts, the released stack must already prove:
- full run;
- changed-item run;
- reuse;
- exact partial rerun;
- timeout and ordinary command failure;
- main build update;
- sparse PR overlay and resolution;
- PR cleanup;
- stable and preview Pages;
- stale source refusal;
- generated-branch race retry;
- clear external-resource present/absent/error handling.

A consumer migration may contain only consumer-owned configuration and domain
adapters. Discovering a missing generic feature stops the migration and returns
work to the library/tool stack.

The target is that a prepared consumer migration needs one implementation run
and, at most, one consumer-specific correction/confirmation run.
