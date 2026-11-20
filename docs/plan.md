# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.7.1` is released at commit
`c031f5dce3a4b0b207d8ce24716b5e11cdd12df2`.

Repository package CI uses exact released `tool.py.lib.ci 0.1.5` commit
`d189d0718659ca3927f1dddbe373c1c788b11b6c`.

The execution engine already provides changed-item selection, SCons target
signatures/reuse and partial durable build updates. The missing piece exposed by
Forge is configuration composition: nested mini-projects currently have to
repeat repository-root paths and complete step definitions.

## Current goal

Complete #54: make nested CI items local and reusable without changing the
planner, SCons rebuild decisions or durable-build semantics.

The configuration loader will add:

1. item-root-relative path groups alongside the existing repository-relative
   list form;
2. repository-owned named item templates;
3. deterministic ancestor `children` defaults for nested items.

All composition is resolved once during configuration loading. The resulting
`Item` and `Step` objects keep repository-relative normalized paths, so the
existing planner/SCons engine does not gain a second selection or cache layer.

## Required proof

- existing schema-1 repository-relative list configuration remains valid;
- item-local watch/input patterns normalize to repository-relative paths;
- explicit repo-wide patterns remain possible in the same config;
- a named template can provide standard item/step configuration;
- ancestor `children` defaults merge from repository root toward the item,
  with the local item taking final precedence;
- nested sibling items remain independently selected;
- changing one sibling does not select the other without an explicit shared
  watch/dependency;
- existing planner, SCons and build-store tests remain green;
- configuration composition performs no source hashing and no rebuild/cache
  decision of its own.

## Execution order

1. #54 requirements/design and configuration syntax.
2. #54 loader/model tests.
3. Run the complete library test suite.
4. Release the library.
5. Update/release `tool.cad.ci` to the exact library revision.
6. Prove the exact stack in `tool.cad.ci.test`.
7. Migrate one Forge model plus isolated reference items.
8. Only after that proof, migrate the remaining active Forge models.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #54 Add item-root-relative paths and inherited CI templates | now | Required to make nested model/reference mini-projects maintainable while preserving the already-proven selection/SCons/publication behavior. |

No other open issues exist in this repository snapshot.
