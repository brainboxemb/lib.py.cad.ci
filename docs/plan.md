# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

The CAD-CI product release is `v0.6.0`.

Repository package CI currently consumes `tool.py.lib.ci 0.1.4`; released
0.1.5 is externally accepted but not yet adopted here.

## Current goal

Complete #40: add explicit UTC timestamps to CAD-CI-owned run and step evidence
so slow runs can be analysed from durable evidence without relying on GitHub UI
timestamps.

## Execution order

1. Define exact evidence fields and UTC format in requirements/design.
2. Add timestamps only where CAD-CI owns the event:
   - run start/end;
   - consumer action start/end when an action actually executes.
3. Keep CURRENT/CACHE_RESTORED action timestamps absent.
4. Preserve existing duration_seconds semantics.
5. Add deterministic evidence tests.
6. Release the library once after green CI.
7. Update the already-open tool.cad.ci maintenance branch to this exact library
   release before making one combined tool maintenance release.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #40 Add timestamps to CAD-CI run and step evidence | now | Current product-maintenance work; needed for later Forge runtime analysis. |
| #46 Avoid full library test run for documentation-only changes | blocked | PR path is proven; remaining main-push optimization is released in tool.py.lib.ci 0.1.5 and must be adopted after the product-maintenance release. |

## Boundary

Timestamps are evidence/observability only. They do not participate in SCons
signatures, cache decisions, selection or rebuild state.
