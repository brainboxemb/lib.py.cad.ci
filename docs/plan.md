# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #39: add an explicit required item-level `process: true|false`
selection flag.

This is needed before Forge continues its staged model qualification. The flag
must be generic CAD-CI behavior and must be released and black-box accepted
before Forge consumes it.

## Execution order

1. Define the `process` contract in requirements:
   - omitted `process` keeps normal existing item behavior;
   - explicit `process: false` excludes that item from planning/execution;
   - explicit `process: true` documents that the item participates normally;
   - an active item may not depend on an excluded item;
   - Forge will use this flag only on model-verification items, not to disable
     the Forge library build/test item.
2. Define exact planner/SCons semantics and acceptance sequences.
3. Implement configuration/model/planner/runner support.
4. Prove the behavior with library tests, including:
   - missing/invalid `process`;
   - full run exclusion;
   - Git-selection exclusion;
   - dependency fan-out exclusion;
   - explicit selection rejection;
   - active dependency validation;
   - unchanged fan-out among active items.
5. Release the new `lib.py.cad.ci` version after CI is green.
6. Update and release `tool.cad.ci` against that exact library release.
7. Update `tool.cad.ci.test` and pass the black-box staged-selection case.
8. Only then let Forge adopt the released `process` behavior.

## Forge consumer gate

After the released stack passes black-box acceptance, Forge will use
`process` for one vertical end-to-end proof:

1. the Forge tool/library build and test item remains active;
2. exactly five representative model-verification items are set to
   `process: true`;
3. every other model-verification item is set to `process: false`;
4. the five active model verifications are taken through the complete Forge
   chain;
5. once that complete chain is green and stable, remaining model-verification
   items are enabled one at a time;
6. a change to a shared thin verification wrapper may deliberately rerun all
   currently active model-verification items.

This repository does not implement Forge-specific selection or model logic.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #39 Add explicit process flag for CAD-CI items | now | Generic staged item selection required before Forge resumes qualification. |

No other unfinished product work is active in this repository.
