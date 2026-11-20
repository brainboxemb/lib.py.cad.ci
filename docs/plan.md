# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.1` is released at exact commit
`ab701bf9ef46892040f4593a74b16805b7187bea`.

Exact released `tool.cad.ci 0.13.1` consumes that library and has passed the
complete black-box suite in `tool.cad.ci.test`.

The first real Forge nested-item pilot proved execution successfully:

- parent model item passed;
- four nested reference child items passed independently;
- the remaining aggregate reference item passed.

Durable PR publication then exposed one generic build-store assumption:
item source paths were treated as non-overlapping directory ownership.

## Current goal

Complete #61: make durable build ownership safe for nested item paths.

For:

```text
parent item: examples/attach-angle
child item:  examples/attach-angle/build123d
```

the parent owns only its declared outputs plus its `.cad-ci/` evidence.
It does not own the complete subtree below `examples/attach-angle`.

## Required behavior

- new manifest rows record declared item output paths;
- prepare-main and prepare-pr copy only item-owned outputs/evidence;
- update-main replaces only selected item-owned outputs/evidence;
- resolve/promote use stored ownership metadata and preserve nested siblings;
- legacy non-nested schema-1 rows without ownership metadata remain readable;
- ambiguous legacy nested replacement fails instead of deleting sibling data;
- configuration rejects a parent output path that overlaps a nested item root;
- SCons/planner behavior is unchanged.

## Execution order

1. Define ownership and compatibility semantics in requirements/design.
2. Add nested durable-store acceptance cases.
3. Implement exact owned-path copy/replace helpers.
4. Add repository config validation for output/item-root overlap.
5. Run the complete library suite.
6. Release the library patch.
7. Pin/release tool.cad.ci to the exact library patch.
8. Externally accept nested durable publication in tool.cad.ci.test.
9. Resume Forge PR #499 only after that exact stack is green.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #61 Make durable build store ownership-safe for nested item paths | now | Required generic publication fix exposed by the real Forge nested-item pilot. |

Forge PR #499 remains draft/blocked until this chain is complete.
