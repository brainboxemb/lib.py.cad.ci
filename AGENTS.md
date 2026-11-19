# AGENTS.md

## Purpose

`lib.py.cad.ci` is the reusable Python library behind `tool.cad.ci`.

## Boundaries

Keep this repository domain-neutral. Generic configuration, planning, runner,
timeouts, state/reuse, durable build output, Pages and publication mechanics
belong here. Forge stages, SolidCraft rules and CAD-domain checks do not.

## Development process

1. Define the generic requirement before implementation.
2. Implement generic behaviour here.
3. Unit-test it here, including the expected failure classes.
4. Release this library.
5. Update `tool.cad.ci` to consume the exact released library.
6. Release the tool after its CLI tests pass.
7. Prove the complete released stack in `tool.cad.ci.test` with multiple
   representative consumer cases.
8. Only then update Forge or CAD.

If a real consumer migration reveals a missing generic feature, stop that
migration and return the work to this library/tool stack. Do not develop the
generic behaviour inside Forge or CAD.

## Change quality

A real consumer migration should be configuration/domain wiring, not CI
development. The generic stack must already cover planning, execution, reuse,
timeouts, build output, Pages, publication, cleanup and defined error handling.

All Python modules and non-obvious logic need explanatory docstrings/comments.
Workflows are orchestration only.
