# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.8.2` is released and is consumed by the current
`tool.cad.ci 0.13.2` Forge pilot stack.

The Git-selected cold-run architecture and nested-item configuration/publication
work are complete in the released stack.

A real Forge run exposed an observability defect in the SCons adapter:

- SCons stdout is captured until the complete run exits;
- GitHub therefore shows a long silent interval and then assigns nearly the same
  timestamp to output produced throughout the run;
- SCons prints the internal Python action representation
  `_execute_bundle(targets, sources, ...)`, including long source lists.

## Current goal

Complete #63 without changing execution semantics.

Required operator output:

```text
CAD CI run: <item>:<step>
<consumer command output, live>
...
SCons: targets=...
```

The internal `_execute_bundle(...)` representation and source-list dump must
not be printed.

## Required proof

- SCons subprocess output is inherited/streamed instead of captured and replayed;
- a slow consumer command can expose an early flushed line before it exits;
- executed targets use a concise logical action label;
- no `_execute_bundle(` action dump appears;
- all existing SCons and library tests remain green;
- no selection, target signature, cache, dependency or publication behavior
  changes.

## Execution order

1. Define logging behavior in requirements/design.
2. Add logging acceptance.
3. Stream SCons output and give the Python action a concise display label.
4. Run the complete library suite.
5. Release the patch.
6. Pin/release `tool.cad.ci` and run external acceptance.
7. Only then update the Forge consumer pin.

## Open issue assessment — 2026-11-20

| Issue | Status | Assessment |
| --- | --- | --- |
| #63 Stream CAD-CI execution output and suppress internal SCons action dumps | now | Real Forge logs are temporally misleading and expose internal SCons implementation details. |
