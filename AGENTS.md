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
