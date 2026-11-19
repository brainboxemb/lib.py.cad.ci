# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current goal

Complete #35: allow root `cad-ci.yml` to define validated repository variables
that are injected into every configured consumer command and participate in
SCons rebuild decisions.

## Execution order

1. Define the variable contract in requirements/design and the SCons documents.
2. Implement root variable loading, validation, command injection and target
   signature participation.
3. Prove the behavior with configuration tests and real-SCons execution tests.
4. Release 0.5.0 after repository CI is green.
5. Then update `tool.cad.ci` through its own #47 and prove the exact released
   stack in `tool.cad.ci.test` before Forge uses it.

## Open issue assessment — 2026-11-19

| Issue | Status | Assessment |
| --- | --- | --- |
| #35 Inject repository variables from cad-ci.yml into every CAD-CI command | now | Active 0.5.0 change. Complete contract, implementation, tests and release before closing. |

No other open repository issues exist at this point in time.
