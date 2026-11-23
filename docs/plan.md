# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Release candidate

### #134 — publish 0.18.2 with CadQuery Workplane compatibility

**Now.**

Released baseline:

- `lib.py.cad.ci v0.18.1` @
  `6064a53b9ea1c340d49893ca0f8d1fa5e3e138ea`;
- v0.18.1 added real `cq.Assembly` export;
- external tool.cad.ci.test #248 proved that Assembly succeeds but normal
  `cq.Workplane` regressed because callable `.export` was used as the
  discriminator;
- #132 corrected that dispatch and merged as
  `4aa9a68e51d7c281886688c287c54786f2e71e51`.

0.18.2 must publish that compatible behavior:

- actual `cadquery.Assembly` -> model-owned
  `export(..., exportType="STL")`;
- Workplane/Shape/other normal values -> `cadquery.exporters.export`;
- one shared reference runtime/container, current SCons semantics unchanged.

Release requirements:

1. VERSION and pyproject declare exactly 0.18.2;
2. CHANGELOG records the #132 compatibility correction;
3. installed-wheel/SCons CI is green on the exact release PR;
4. merge the tested release PR;
5. verify `v0.18.2` targets the exact tested merge commit;
6. repin/release the thin tool;
7. rerun external #248 acceptance before Forge #740 resumes.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #134 Publish lib.py.cad.ci 0.18.2 | **now** | Qualify, merge and verify release; then repin the thin tool. |
| #89 Align historical changelog | later / docs-only | Keep separate from the active Forge migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- source inventory remains one enumeration per run;
- verification package remains one shared target;
- build123d/CadQuery compatible models remain one shared reference runtime;
- the correction changes only CadQuery export dispatch inside that runtime.
