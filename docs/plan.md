# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.7.1` is released at commit
`c031f5dce3a4b0b207d8ce24716b5e11cdd12df2`.

The released stack already has:
- exact Git revision comparison through `changed_files()`;
- affected-item selection through item `watch` configuration;
- one SCons graph invocation for the selected items;
- partial durable build updates that preserve unaffected item output.

The normal GitHub-hosted `tool.cad.ci` workflow does not restore or transport
`.cache/cad-ci/scons/cache`. A selected item therefore starts cold on a fresh
hosted runner.

## Current goal

Complete #56 before #54 or any further Forge migration.

Make the hosted-runner contract literal:

```text
Git diff
  -> affected processed items
  -> selected items execute cold on a fresh runner
  -> unselected items are not given to SCons
  -> durable publication replaces only selected item paths
```

Cross-run SCons cache reuse is not part of the required hosted-CI behavior.

## Required proof

The library acceptance must create two Git revisions and then execute from a
fresh clone with no `build/` and no `.cache/cad-ci/`.

When only item A changes:
- Git diff reports only A's changed path;
- affected selection returns A only;
- SCons receives/executes A only;
- A is BUILT;
- B has no target outcome and no build output.

Existing local SCons CURRENT and explicit CacheDir-restore tests remain valid
capability tests, but they must not be described as the default hosted-runner
path.

## Execution order

1. #56 update requirements/design/acceptance.
2. Add fresh-clone no-cache Git-diff execution acceptance in this library.
3. Keep the complete library suite green.
4. Prove the same released behavior black-box in `tool.cad.ci.test`.
5. Only then resume #54 configuration ergonomics.
6. Only after #54 is released and externally accepted may Forge reference items
   be migrated.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #56 Define hosted-runner incrementality without assuming persistent SCons cache | now | Architecture correction and fresh-runner acceptance required before consumer migration. |
| #54 Add item-root-relative paths and inherited CI templates | blocked | Useful configuration ergonomics, but blocked until #56 establishes and proves the execution model it must preserve. |

No Forge consumer change is allowed before this chain is externally accepted.
