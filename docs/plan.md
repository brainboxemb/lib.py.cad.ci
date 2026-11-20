# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.4` is released at exact commit
`4e033fd17e911b3feb92b1a34433b884ca788ab6`.

The release adds explicit current-configuration membership to partial durable
main updates so removed configured items can be deleted without confusing them
with sparse unselected items.

The library proof is complete:

- selected current items are replaced from validated candidate output;
- unselected current items remain unchanged;
- items absent from explicit current processed configuration are removed;
- nested ownership remains safe;
- ambiguous legacy nested deletion fails rather than guessing.

## Current goal

No active library implementation work.

The next step is outside this repository:

1. update `tool.cad.ci` to exact released library 0.8.4;
2. expose the complete current processed item set to `update_main`;
3. release the tool;
4. prove the behavior through `tool.cad.ci.test`;
5. only then retry the Forge durable-main update and continue Pages.

## Open issue assessment — 2026-11-20

No open implementation issues remain after #65.
