# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.0` is released at exact commit
`e2056c0d5ac361f0d021e58e55025e02c5688acf`.

Exact released `tool.cad.ci 0.13.0` consumes that library and its complete
black-box suite is green in `tool.cad.ci.test`.

The released stack now proves:
- Git-selected cold hosted-runner execution;
- item-root-relative watch/input paths;
- root item templates;
- path-derived nested item IDs;
- nested sibling selection isolation.

Preparing the first real nested Forge reference consumer exposed one remaining
generic path requirement before any Forge file is changed.

## Current goal

Complete #59: allow safe parent-relative paths only inside explicit `item:`
source scopes.

A nested child such as:

```text
examples/attach-angle/build123d/
```

must be able to declare:

```yaml
watch:
  item:
    - ../verification/reference_geometry.json
```

which normalizes to:

```text
examples/attach-angle/verification/reference_geometry.json
```

## Safety contract

- legacy list/repository paths continue to reject `..`;
- explicit `repo:` paths continue to reject `..`;
- `item:` paths may use parent traversal only while lexical normalization
  stays within the repository;
- normalized paths may not enter `.git/`, `.cache/` or `build/`;
- planner/SCons continue to receive normalized repository-relative paths only;
- no filesystem/hash/cache behavior is added.

## Required proof

- one-level parent path normalization;
- multi-level safe parent normalization;
- repository escape rejection;
- repo/legacy `..` rejection remains unchanged;
- existing nested sibling selection remains isolated;
- full library suite stays green.

## Execution order

1. Update requirements/design with exact normalization semantics.
2. Implement one lexical item-path normalizer in the config loader.
3. Add focused config/planner tests.
4. Run the complete library suite.
5. Release a patch version.
6. Update/release `tool.cad.ci` to the exact library patch.
7. Externally accept the exact stack in `tool.cad.ci.test`.
8. Only then start the first Forge nested-reference pilot.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #59 Allow safe parent-relative item-scoped source paths | now | Small generic gap found by the first real nested consumer; must be solved without Forge hardcoded paths. |

No Forge consumer file is changed before this exact released stack is externally
accepted.
