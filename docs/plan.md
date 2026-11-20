# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.7.1` is released at commit
`c031f5dce3a4b0b207d8ce24716b5e11cdd12df2`.

Repository package CI uses exact released `tool.py.lib.ci 0.1.5` commit
`d189d0718659ca3927f1dddbe373c1c788b11b6c`.

The release job consumes the reusable `change_scope` output and must not run
for a documentation-only main push.

## Current goal

Complete #46 with one pure documentation-only acceptance change.

This branch deliberately changes only `docs/plan.md`. The CI runs themselves
are the proof.

## Required proof

On this pull request:

- change scope is `docs-only`;
- setup-python is skipped;
- wheel build/install/tests are skipped;
- the normal required test check succeeds.

After squash merge to main:

- push change scope is also `docs-only`;
- setup-python and package validation remain skipped;
- the repository `release` job is skipped via
  `needs.test.outputs.change_scope`;
- no release/publication work is performed.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #46 Avoid full library test run for documentation-only changes | now | Final real-consumer proof of both pull-request and post-merge main behavior using released tool.py.lib.ci 0.1.5. |

No other open issues exist in this repository snapshot.

## Released state

CAD-CI timing evidence and build-store schema compatibility are released in
v0.7.1. Released `tool.cad.ci 0.12.1` pins this exact library revision.

After #46 is proven and merged, this repository has no unfinished issue in the
current CI-acceleration chain.
