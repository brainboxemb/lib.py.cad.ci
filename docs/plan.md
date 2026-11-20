# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

Repository package CI now uses exact released `tool.py.lib.ci 0.1.4` commit
`81461fa4b61c90b91b0427ce3e99a493c2dc2e78`.

The documentation-only path has been proven in this repository:

- a PR changing only `docs/plan.md` completed the normal required check;
- setup-python was skipped;
- wheel build/install/library tests were skipped;
- the job completed in about 6 seconds versus about 21 seconds for the
  immediately preceding full consumer run.

The CAD-CI product remains released as `v0.6.0`. Its `process` behavior is
already adopted by `tool.cad.ci`, `tool.cad.ci.test` and Forge.

## Current goal

No CAD-CI library implementation is active while CI-maintenance work continues
in the surrounding tool/test repositories.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #40 Add timestamps to CAD-CI run and step evidence | later | Useful observability work, but keep it separate while higher-level CI maintenance/performance work is being completed. |

## Released state

`lib.py.cad.ci 0.6.0` is published from commit
`dac8c5b5e1147a401730fda31f9bf9de2278c4ee`.

The next active work is outside this repository: reduce unnecessary CI runs and
then revisit Forge model-verification runtime/dependency structure.
