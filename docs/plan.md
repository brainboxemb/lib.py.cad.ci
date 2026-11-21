# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.9.2` is released at exact commit
`3f688243f4ee65b1fa42f82adde5344fe5101775`.

The released 0.9.2 stack is externally accepted through:
- `tool.cad.ci 0.16.1` @
  `4c6bb8b35009ef5008bd99134cf84b59fddc0b8a`;
- completed `tool.cad.ci.test` #60 named-scope black-box acceptance.

The previous #74 engine-schema blocker is complete and is not active work.

## Current goal

Complete #71: reduce fixed selective-run startup overhead before the first SCons
target begins.

Observed Forge evidence showed roughly 16 seconds between entering the generic
CAD-CI run step and the first real SCons target, while the selected lightweight
work itself completed in under one second.

The optimization belongs here. Do not add a Forge workaround and do not add a
second execution/reuse engine.

## Required proof

Before implementation, define the observable timing contract in:
- `docs/requirements.md`;
- `docs/scons-engine.md`;
- `docs/scons-acceptance.md`.

Then:
- measure distinct generic pre-target phases;
- identify the dominant fixed cost;
- remove repeated/unnecessary work without changing selection or SCons
  signatures;
- keep SCons as the sole execution/rebuild/cache engine;
- retain deterministic evidence and failure behavior;
- add a regression/performance proof at the library boundary.

## Execution order

1. [#71, now] Instrument and contract the pre-target phases.
2. [#71] Identify and remove the dominant fixed overhead.
3. [#71] Run complete library tests plus focused timing acceptance.
4. Release only from the exact green main revision if behavior changed.
5. Repin `tool.cad.ci` only if a new library release is required.
6. Prove the released stack externally before Forge adopts it.

## Open issue assessment — 2026-11-21

| Issue | Status | Assessment |
| --- | --- | --- |
| #71 Reduce fixed selective-run startup overhead before first SCons target | **now** | Directly explains slow small/selective consumer runs; generic library-owned measurement and optimization. |

Immediate chain:

`#71 measure -> contract -> optimize -> library proof -> released-stack acceptance`.
