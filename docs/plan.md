# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #44 by bringing this plan in sync with the published 0.6.0 release.

The item-level `process` behavior from #39 is complete and released as
`v0.6.0`. No product, requirement, design or implementation change is part of
this work.

## Execution order

1. Record the actual post-0.6.0 repository state.
2. Confirm the complete open issue list.
3. Merge this plan-only correction and close #44.
4. Leave #40 deferred while the released 0.6.0 stack is adopted by
   `tool.cad.ci`, `tool.cad.ci.test` and Forge.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #44 Update repository plan after 0.6.0 release | now | Plan-only correction required after the successful v0.6.0 release. |
| #40 Add timestamps to CAD-CI run and step evidence | later | Separate observability improvement; keep it outside the current process-selection adoption chain. |
| #46 Avoid full library test run for documentation-only changes | blocked | Concrete consumer need is recorded here, but the generic solution belongs in tool.py.lib.ci #11. Adopt only after that tool behavior is released and externally tested. |

## Released state

`lib.py.cad.ci 0.6.0` is published from commit
`dac8c5b5e1147a401730fda31f9bf9de2278c4ee`.

The next work for the released `process` behavior is outside this repository:
`tool.cad.ci` must pin this exact released library revision, then
`tool.cad.ci.test` must prove the released stack before Forge consumes it.
