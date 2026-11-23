# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Released baseline

- `lib.py.cad.ci 0.13.0` @
  `8f0516a484e3eac11758b498ca181d5e39ed1efe`;
- `tool.cad.ci v0.29.0` consumes that exact release and external acceptance
  in `tool.cad.ci.test` #141 is green for the existing black-box suite;
- #141 exposed one remaining generic gap: the durable workflow cannot isolate
  generated output on alternate branch names while exercising the real
  publication lifecycle.

## Current work

### #98 — configurable durable generated output branches

**Now.** Preserve `build` and `gh-pages` as compatibility defaults, while
allowing the durable library adapter to read/publish equivalent output on
caller-selected generated branch names such as
`test-output/build` and `test-output/gh-pages`.

Execution order:

1. define the branch-selection behavior in requirements/design;
2. thread the selected build branch through state materialization and durable
   build publication;
3. thread the selected Pages branch through durable Pages publication;
4. add regression coverage for defaults and non-default branch names;
5. merge and release an exact library revision;
6. let `tool.cad.ci` #147 expose that released behavior;
7. finish live acceptance in `tool.cad.ci.test` #141 before Forge/CAD adopt it.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #98 Configurable durable generated output branch names | **now** | Define, implement, test, merge, then release. |
| #89 Align historical changelog with shared meta template and guidance | **later / docs-only** | Apply shared changelog presentation without changing released behavior. |

## Non-goals

- no second scheduler/freshness engine;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no tool-owned duplicate implementation of library state;
- no single filesystem-style `output_root` that merges build-store and Pages
  publication into one branch.
