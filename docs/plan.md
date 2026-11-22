# Repository plan

This file is the current source of truth for unfinished work in `lib.py.cad.ci`.

The repository owns generic CAD-CI planning/execution semantics. Consumer- or
domain-specific behavior belongs in consumer repositories.

## Current released and accepted state

`lib.py.cad.ci 0.10.0` is released at exact commit
`397fb04005b46de8d433cb18c091b1e73714b877`.

Accepted public behavior includes:

- selective active-closure startup;
- bounded SCons jobs;
- deterministic target-private command dependency snapshots;
- durable build/Page support through the thin tool;
- engine-owned dependency-output `copy:` actions;
- safe `{item_path}` projection from one direct dependency;
- no complete dependency snapshot materialization for copy actions;
- structured `action_type=command|copy` evidence.

External released-stack acceptance is complete:

- `tool.cad.ci 0.17.1` @
  `1012e6a539a2fddd8194124844fe208bf16cf4e4`;
- `tool.cad.ci.test` #70 / PR #71;
- complete acceptance run `45006989548` — success.

Issue #79 is complete and closed.

## Current work

No library implementation is active.

A new issue is required before changing generic execution semantics. Consumer
migration or performance tuning that needs no generic behavior change belongs in
the consumer repository.

## Next trigger

Return here only when:

- an externally observed generic correctness defect is reproduced;
- a consumer requires a reusable capability that does not belong locally;
- measured engine behavior justifies a generic optimization;
- a public evidence/configuration contract needs deliberate revision.

Requirements/design/acceptance must be updated before implementation for any
new generic behavior.
