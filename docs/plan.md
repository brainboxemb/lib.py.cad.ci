# Repository plan

This file contains only current unfinished work for `lib.py.cad.ci`.

Product requirements live in `docs/requirements.md`. Execution-engine design
lives in `docs/scons-engine.md` and `docs/scons-acceptance.md`. Issues
contain detailed discussion/history. This file is the single current execution
plan.

Completed sections are removed after their PR/release is finished.

## 1. Migrate this library's own CI to tool.py.lib.ci — #27

`lib.py.cad.ci` is a Python library. Its own package build/test workflow
should use the generic Python-library CI stack, not maintain a separate
hand-written package workflow.

Prerequisite:

1. release `tool.py.lib.ci` 0.1.0;
2. pin that exact release in `tool.py.lib.ci.test`;
3. pass black-box acceptance there.

Only after that accepted release exists:

- replace this repository's local package-test job with the released reusable
  `tool.py.lib.ci` workflow;
- pin the exact accepted tool commit;
- build exactly one `lib.py.cad.ci` wheel;
- install that wheel and its dependencies in a clean environment;
- run the complete library test suite against the installed wheel;
- keep release publication gated on green main CI;
- remove duplicate package build/test setup now owned by `tool.py.lib.ci`.

Important boundary:

- this migration changes only this repository's **own CI**;
- SCons remains part of the `lib.py.cad.ci` product;
- CAD-CI planning, execution, reuse, evidence, durable build and publication
  remain in this library;
- `tool.cad.ci` remains the thin CAD-CI tool above this library.

Remove this section and close #27 after the accepted `tool.py.lib.ci` release
is in use here and the installed-wheel CI is green.

If no other repository work is planned at that point, `docs/plan.md` may be
removed.
