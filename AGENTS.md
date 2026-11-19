# AGENTS.md

## Purpose

`lib.py.cad.ci` is the reusable Python library behind `tool.cad.ci`.

## Boundaries

Keep this repository domain-neutral. Generic configuration, planning, runner,
state/reuse, build, Pages and publication mechanics belong here. Forge stages,
SolidCraft rules, model validation and qualification semantics do not.

## Development process

1. Implement generic behaviour here.
2. Unit-test it here.
3. Update `tool.cad.ci` to consume the released/pinned library.
4. Prove the complete contract in `exp.2026-014.cad-ci-consumer`.
5. Only then update real consumers.

All Python modules and non-obvious logic need explanatory docstrings/comments.
Workflows are orchestration only.
