# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.3` is released. The nested-item build-store ownership and
live execution-output work are complete in that release.

A real Forge main update exposed one remaining durable-store lifecycle gap:

- a configured item was removed from the repository;
- its replacement nested items were selected, verified and published;
- `update_main` preserved the removed item's old durable manifest row and bytes
  because sparse replacement input alone does not identify repository deletion.

The current tool passes only affected replacement items to `update_main`.
The library therefore cannot distinguish an unselected current item from an item
that no longer exists in current processed configuration.

## Current goal

Complete the #65 release correction and publish 0.8.4. The implementation is merged; the first main release job correctly skipped because `VERSION` was not updated alongside `pyproject.toml`.

A partial main update must preserve unselected current items, replace selected
current items and remove durable state for items that are no longer part of the
current processed repository configuration.

Deletion must come from explicit current configuration, never from absence in a
sparse candidate.

## Required proof

- the update API receives both selected replacements and the current processed
  item set;
- a removed stored item loses its manifest row and owned durable bytes;
- a currently configured but unselected item remains byte-identical;
- nested parent/child removal deletes only the removed item's owned outputs and
  `.cad-ci` evidence;
- a still-configured nested neighbor survives unchanged;
- legacy rows without ownership metadata fail if deletion would be ambiguous in
  a nested layout rather than guessing whole-tree ownership;
- selected replacement behavior and existing build-store tests remain green.

## Execution order

1. Define removed-item durable-store behavior in requirements/design.
2. Add build-store tests for removed flat and nested items.
3. Implement explicit current-configuration cleanup in `update_main`.
4. Run the complete library suite.
5. Release 0.8.4 in the same issue PR.
6. Pin/expose 0.8.4 in `tool.cad.ci`.
7. Release the tool and pass `tool.cad.ci.test` black-box acceptance.
8. Retry the Forge main update and confirm the stale aggregate disappears
   before continuing Pages.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #65 Remove deleted configuration items from durable main updates | now | Required generic build-store lifecycle fix exposed by the real Forge reference-item migration. |
