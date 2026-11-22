# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current released state

`lib.py.cad.ci 0.10.0` is released at exact commit
`397fb04005b46de8d433cb18c091b1e73714b877`.

Release evidence:

- main test/release run `45006286548` — success;
- Git tag/GitHub Release `v0.10.0` resolve to the exact released commit.

The previously accepted consumer chain still uses:

- `tool.cad.ci 0.17.0` / lib 0.9.3;
- Forge v0.11.0 and post-release lanes on that accepted stack.

The 0.10.0 capability is intentionally **not consumer-accepted yet**. Tool issue
#91 is repinning the released library, after which `tool.cad.ci.test` must
prove the exact released pair before Forge #261 may adopt `copy:`.

Closed #71 delivered active-closure-first selective startup. Bounded parallel
execution is also released. Those optimizations remain the baseline and must not
be bypassed by a second scheduler or freshness engine.

## Current work

### #79 — effectively complete, downstream acceptance pending

The generic library implementation is complete and released as 0.10.0.

#79 remains open only as the owner-chain tracking point until:

1. tool.cad.ci #91 pins/releases the exact library commit;
2. tool.cad.ci.test accepts the exact released tool/library stack;
3. Forge #261 records that accepted dependency before consumer migration.

No additional library implementation is currently justified. If external
acceptance exposes a generic defect, reopen active implementation here and
update requirements/design/acceptance before code.

## Intended behavioral boundary for #79

A normal command step remains unchanged.

A copy step is a SCons-owned target action that:

- declares exactly one direct dependency and a safe source root below that
  dependency's declared output;
- may use the current item's normalized source path as a fixed substitution in
  that source root so repository templates can serve nested items;
- maps each declared consumer output from
  `<dependency source root>/<consumer output>` to the same relative path in
  the consumer item output;
- constructs the consumer target bundle directly from only those selected
  dependency-bundle members;
- does **not** create a target-private snapshot of the dependency's complete
  output and does not launch a consumer subprocess;
- remains a normal SCons target whose signature includes dependency target,
  copy specification, outputs and engine schema;
- preserves normal current/cache/evidence/durable-publication behavior.

The exact YAML and evidence details belong in requirements/design/acceptance
before implementation.

## Non-goals

- no Forge/model/reference vocabulary in this library;
- no GitHub artifact transport;
- no special-case path registry for one consumer;
- no second cache/fingerprint engine;
- no jobs increase as a substitute for removing repeated work;
- no removal of real consumer commands such as Forge model contract tests;
- no change to ordinary command-step dependency snapshots.

## Next demand-driven priorities

The library is in downstream-acceptance mode. After #79 is externally accepted,
this repository returns to demand-driven mode. New generic work must again start from consumer evidence and
a new issue.

If #79 does not materially reduce the measured Forge tail, return to the
remaining timing evidence rather than layering more execution mechanisms on top.
