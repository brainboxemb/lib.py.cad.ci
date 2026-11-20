# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #42: release the merged `process` selection behavior as version 0.6.0.

The product behavior from #39 is already merged through PR #41. This release
change must contain no new CAD-CI behavior.

## Execution order

1. Confirm the merged #39 implementation is green on main.
2. Set VERSION and pyproject.toml to 0.6.0 and add the matching CHANGELOG entry.
3. Pass the release PR tests and merge the release commit.
4. Confirm the main release workflow publishes 0.6.0.
5. Update this plan after release, then continue the released-stack path through
   tool.cad.ci and tool.cad.ci.test before Forge consumes `process`.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #42 Release lib.py.cad.ci 0.6.0 with process selection | now | Release-only follow-up to merged #39; required before tool.cad.ci can pin the new behavior. |
| #40 Add timestamps to CAD-CI run and step evidence | later | Separate observability improvement; do not mix it into the process-selection release chain. |

## Boundary

The `process` contract, design and implementation are already complete on main.
This issue changes only release metadata and the current repository plan.
