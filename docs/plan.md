# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current released state

`lib.py.cad.ci 0.9.3` is released at exact commit
`74486c441f1f2b170ff3dc06e0edcaf662fbec6b`.

The currently accepted consumer chain is:

- `tool.cad.ci 0.17.0` with explicit bounded `jobs` support;
- Forge v0.11.0 and post-release main/dev lanes on jobs=2;
- the external `tool.cad.ci.test` released-stack acceptance used for each
  owner-first promotion.

Closed #71 delivered active-closure-first selective startup. Bounded parallel
execution is also released. Those optimizations remain the baseline and must not
be bypassed by a second scheduler or freshness engine.

## Current work

### #79 — dependency-output copy without consumer copy processes

The implementation and library conformance suite are green. The branch now
prepares **lib.py.cad.ci 0.10.0**; merge is gated on the final release-prepared
PR run, after which the repository's normal main release job must publish
`v0.10.0` from that exact tested main commit.

Consumer: `lib.py.solidcraft.forge` #261.

Forge full-run evidence on the accepted jobs=2 stack shows that the two heavy
shared verification batches finish in roughly 60-81 seconds, while SCons still
has a 107-176 second tail before all 227 targets complete.

The current consumer shape explains a plausible generic cause:

1. one shared dependency item produces a complete batch result;
2. many child items depend on that batch;
3. every child step receives a target-private snapshot of the dependency's
   **complete final bundle**;
4. a tiny consumer Python command copies only one child subtree into its own
   output;
5. CAD-CI then bundles that copied child output again.

For Forge references this pattern repeats across roughly four reference items
per model. Repeated full dependency-snapshot materialization is therefore a
stronger candidate bottleneck than Python interpreter startup alone.

#79 is the only active generic implementation.

Required owner-first sequence:

1. define a literal declarative dependency-output `copy` step in requirements;
2. define safe source-path/token rules and direct-bundle projection semantics in
   the SCons design;
3. add acceptance sequences before engine implementation;
4. implement the library without materializing the complete dependency output
   for a copy step;
5. prove cold/current/invalidation/cache/parallel/error behavior;
6. release the library;
7. repin/release the thin tool;
8. prove the exact released pair in `tool.cad.ci.test`;
9. only then let Forge replace projection-only materializer commands and
   remeasure #261.

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

After #79 is released and externally accepted, this repository returns to
demand-driven mode. New generic work must again start from consumer evidence and
a new issue.

If #79 does not materially reduce the measured Forge tail, return to the
remaining timing evidence rather than layering more execution mechanisms on top.
