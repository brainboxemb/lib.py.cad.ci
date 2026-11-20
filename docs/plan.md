# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.7.1` is released at commit
`c031f5dce3a4b0b207d8ce24716b5e11cdd12df2`.

Hosted-runner incrementality is now defined and externally accepted:

```text
Git diff
  -> affected processed items
  -> selected items execute cold on a fresh runner
  -> unselected items are not given to SCons
  -> durable publication replaces only selected item paths
```

The black-box released-stack acceptance in `tool.cad.ci.test` proves this on a
fresh clone with no `build/` and no `.cache/cad-ci/`.

## Current goal

Complete #54 with the smallest configuration feature set required for isolated
nested consumer items.

Add only:

1. item-root-relative path groups for item `watch` and step `inputs`;
2. repository-owned named item templates in root `cad-ci.yml`;
3. deterministic path-derived item IDs for nested items when `id` is omitted.

Do not add directory inheritance in this change.

## Required consumer shape

A nested consumer item should be able to use:

```yaml
template: reference-build123d
```

inside:

```text
examples/attach-angle/build123d/ci.yml
```

The template supplies standard steps and shared repository inputs. Item-local
paths resolve relative to that child directory. If `id` is omitted, the item
ID is derived from the repository path, for example
`examples-attach-angle-build123d`.

## Required proof

- existing list-form `watch` and `inputs` stay repository-relative;
- new scoped path mapping supports both item-local and repository-wide paths;
- item-local paths normalize once during configuration loading to the existing
  repository-relative internal representation;
- one root template can provide normal item fields and steps;
- local item fields override template fields deterministically;
- nested implicit IDs are valid and unique for different source paths;
- changing one nested sibling selects only that sibling through the existing
  Git-diff planner;
- the fresh hosted-runner execution contract from #56 remains unchanged;
- all existing planner, SCons and build-store tests remain green.

## Execution order

1. Update requirements/design with exact syntax and merge rules.
2. Implement loader/model support only.
3. Add config/planner acceptance for nested siblings.
4. Run the complete library suite.
5. Release the library.
6. Update/release `tool.cad.ci` to that exact library revision.
7. Prove the exact released stack in `tool.cad.ci.test`.
8. Only then introduce isolated reference items in Forge.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #54 Add item-root-relative paths and inherited CI templates | now | Narrowed to item-relative paths, root templates and path-derived nested IDs. Directory inheritance is deferred. |

No Forge consumer change is allowed before the released stack passes external
acceptance.
