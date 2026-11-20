# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #46 by proving the released `tool.py.lib.ci 0.1.4` documentation-only
CI path in this repository.

The exact 0.1.4 tool revision is already adopted on main. This PR deliberately
changes only this file under `docs/`; the CI result itself is the acceptance
evidence.

## Required proof in this PR

The Python-library CI job must:

1. check out this branch and exact released tool revision;
2. classify the change as documentation-only;
3. print the explicit documentation-only skip reason;
4. skip `actions/setup-python`;
5. skip wheel build, clean installation and library tests;
6. still complete the normal required `test` check successfully.

No product code, workflow file, package metadata or non-doc path may change in
this PR.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #46 Avoid full library test run for documentation-only changes | now | This docs-only PR is the real consumer proof of released tool.py.lib.ci 0.1.4. |
| #40 Add timestamps to CAD-CI run and step evidence | later | Separate CAD-CI observability work; keep it outside repository-CI maintenance. |

## Released state

`lib.py.cad.ci 0.6.0` remains the current product release.

Repository package CI uses exact released `tool.py.lib.ci 0.1.4` commit
`81461fa4b61c90b91b0427ce3e99a493c2dc2e78`.

After #46 is proven and merged, the documentation-only maintenance path is
complete and #40 remains the only unfinished CAD-CI library issue.
