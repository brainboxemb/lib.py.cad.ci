# AGENTS.md

## Purpose

`lib.py.cad.ci` is the reusable Python library behind `tool.cad.ci`.

## Boundaries

Keep this repository domain-neutral.

Generic configuration, Git selection, SCons translation, execution wrappers,
evidence, durable build output, **complete-scope state/resolution**, Pages,
publication mechanics and reusable CAD engine invocation/export builders belong
here.

Generic engine adapters such as build123d or CadQuery may be built-in when they
only define reusable execution/export behavior. Consumer semantics do not move
with them: Forge stages/API contracts, model-specific geometry expectations,
SolidCraft verification definitions, presentation policy and other CAD-domain
checks remain in their owning consumer/verification repositories.

SCons is the only generic rebuild/reuse engine. Do not add a parallel custom
fingerprint, dependency execution or reuse engine.

## Repository plan

Current unfinished repository work lives in `docs/plan.md`.

Rules:

- keep one general repository plan;
- treat `docs/plan.md` as the current work source of truth;
- before starting work, compare the plan with the complete open issue list;
- every open issue must have a point-in-time assessment in the plan;
- if an open issue is missing from the plan, update the plan before implementation;
- the current-work section contains only unfinished work;
- remove completed work after merge/release;
- permanent product behavior belongs in requirements/design documentation;
- issues provide detail and history, while the plan records current status and
  execution order.

## Own CI boundary

This repository is itself a Python library.

Its own package CI uses `tool.py.lib.ci` 0.1.5 at exact commit
`d189d0718659ca3927f1dddbe373c1c788b11b6c`, after that revision passed
`tool.py.lib.ci.test`.

Do not confuse that repository-CI dependency with the product architecture:
SCons and CAD-CI behavior remain valid responsibilities of `lib.py.cad.ci`.

## Development process

Before execution-engine code changes:
1. define observable behaviour in `docs/requirements.md`;
2. define exact technical semantics in `docs/scons-engine.md`;
3. define expected run results in `docs/scons-acceptance.md`.

Only then implement and test the change.

After library tests pass:
1. release the library;
2. update `tool.cad.ci` to the exact released library;
3. test and release the tool;
4. pin that exact tool in `tool.cad.ci.test`;
5. pass all relevant black-box cases;
6. only then update Forge or CAD.

If implementation or a consumer migration exposes an undefined generic
behaviour, stop and update the contract/design first.

## Change quality

Keep workflows orchestration-only. Put generic behaviour in this library.

All Python modules and non-obvious logic need concise explanatory
docstrings/comments. Keep one logical change in one branch/PR.

## Repository plan

`docs/plan.md` is the current source of truth for unfinished repository work.

Keep it as a current snapshot, not as historical documentation:

- state the current goal and execution order;
- include every open issue in an issue assessment snapshot;
- give each open issue an explicit status such as `now`, `later`, `blocked`, `probably obsolete`, or `effectively complete but still open`;
- explain briefly why that status applies;
- identify dependencies or blockers between issues;
- remove completed work from the active execution sections after merge/release, while keeping the issue assessment current.

Issues contain detail and history. README and design/requirements documents describe stable purpose and behavior. The plan tells an agent what work is actually current and what should happen next.

