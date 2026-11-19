# AGENTS.md

## Purpose

`lib.py.cad.ci` is the reusable Python library behind `tool.cad.ci`.

## Boundaries

Keep this repository domain-neutral.

Generic configuration, Git selection, SCons translation, execution wrappers,
evidence, durable build output, Pages and publication mechanics belong here.
Forge stages, SolidCraft rules and CAD-domain checks do not.

SCons is the only generic rebuild/reuse engine. Do not add a parallel custom
fingerprint, dependency execution or reuse engine.

## Repository plan

Current unfinished repository work lives in `docs/plan.md`.

Rules:

- keep one general repository plan;
- the plan contains only unfinished work;
- remove completed sections after merge/release;
- permanent product behavior belongs in requirements/design documentation;
- issues provide detail/history, but current execution order must be readable
  from `docs/plan.md`.

## Own CI boundary

This repository is itself a Python library.

Its own package CI uses `tool.py.lib.ci` 0.1.1 at exact commit
`414db795c757af5c4f9eaff7f6fd65f27870d7d1`, after that revision passed
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
