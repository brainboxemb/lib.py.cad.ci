# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Current owner fix

### #132 — restrict model-owned CadQuery export to cq.Assembly

**Now.**

Released baseline:

- `lib.py.cad.ci v0.18.1` @
  `6064a53b9ea1c340d49893ca0f8d1fa5e3e138ea`;
- v0.18.1 correctly enables real `cq.Assembly` export but external acceptance
  found that its callable-`.export` detection also captures normal
  `cq.Workplane` values.

External evidence from tool.cad.ci.test #248 / PR #249:

- root 019 real `cq.Assembly`: PASS;
- existing root 017 real `cq.Workplane`: FAIL with
  `TypeError: Workplane.export() got an unexpected keyword argument 'exportType'`.

Required correction:

1. select model-owned `export(..., exportType="STL")` only for actual
   `cadquery.Assembly` instances;
2. keep Workplane/Shape and other normal exporter-compatible values on
   `cadquery.exporters.export`;
3. retain one shared reference runtime/container and current SCons behavior;
4. add a regression proving a non-Assembly object with a callable `.export`
   still uses the normal exporters module;
5. after merge, publish a new patch release without moving v0.18.1.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #132 Restrict model-owned CadQuery export to cq.Assembly | **now** | Fix type discrimination, qualify, then publish a new patch release and repin the thin tool. |
| #89 Align historical changelog | later / docs-only | Keep separate from the active Forge migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- source inventory remains one enumeration per run;
- verification package remains one shared target;
- build123d/CadQuery compatible models remain one shared reference runtime;
- the fix changes only per-model CadQuery export dispatch inside that runtime.
