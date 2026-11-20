# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #47: adopt exact released `tool.py.lib.ci 0.1.4` for this
repository's own Python-library CI.

This is repository-maintenance work only. The CAD-CI product remains released
as v0.6.0 and its `process` behavior is already adopted downstream by
`tool.cad.ci`, `tool.cad.ci.test` and Forge.

## Execution order

1. Pin exact `tool.py.lib.ci 0.1.4` commit
   `81461fa4b61c90b91b0427ce3e99a493c2dc2e78`.
2. Run the normal full package CI because the workflow configuration changes.
3. Merge #47 only after green CI.
4. Then use #46 for a separate docs-only PR and verify:
   - classification selects the docs-only path;
   - setup-python is skipped;
   - package build/install/test is skipped;
   - the required check still succeeds;
   - the explicit skip reason is visible.
5. Leave #40 separate.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #47 Adopt tool.py.lib.ci 0.1.4 for repository CI | now | Required consumer adoption before the real docs-only proof. |
| #46 Avoid full library test run for documentation-only changes | next | Generic implementation is released and externally accepted; prove the actual cheap path after #47 merges. |
| #40 Add timestamps to CAD-CI run and step evidence | later | Separate CAD-CI observability work; do not mix it with repository-CI maintenance. |

## Released state

`lib.py.cad.ci 0.6.0` is published from commit
`dac8c5b5e1147a401730fda31f9bf9de2278c4ee`.

The process-selection stack is already adopted downstream. Current maintenance
does not change that released product contract.
