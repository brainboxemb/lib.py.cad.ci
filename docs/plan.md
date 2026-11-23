# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Release candidate

### #130 — publish 0.18.1 with CadQuery Assembly export fix

**Now.**

Released baseline:

- `lib.py.cad.ci v0.18.0` is published at
  `eb291abd6bb34b585d04019d154e7756d36436f9`;
- v0.18.0 contains #121 wildcard-prefix matching and #123 the public
  repository-builder verification-package capability;
- #128 merged afterward on `main` as
  `23e1bf7175a68565edf7ca063f68cd9db1b4b083`;
- therefore v0.18.0 must not be moved or rewritten.

0.18.1 contains only the compatible built-in CadQuery export correction from
#128:

- final geometry exposed as `cq.Assembly` uses its supported model-owned
  `export(..., exportType="STL")` path;
- ordinary exporter-compatible CadQuery models retain
  `cadquery.exporters.export`;
- build123d/CadQuery keep the existing one shared reference runtime/container
  and no consumer-owned exporter is reintroduced.

Release requirements:

1. VERSION and pyproject declare exactly 0.18.1;
2. CHANGELOG records the #128 behavior correction;
3. installed-wheel/SCons CI is green on the exact release PR;
4. merge the tested release PR;
5. verify `v0.18.1` targets the exact tested merge commit;
6. repin the thin `tool.cad.ci` from v0.34.0/lib 0.18.0 to the exact 0.18.1
   commit in a new tool release;
7. black-box accept the exact tool/library pair before Forge #740 resumes.

## Accepted baseline before this release

- `lib.py.cad.ci v0.18.0` @
  `eb291abd6bb34b585d04019d154e7756d36436f9`;
- `tool.cad.ci v0.34.0` consumes that exact library release;
- `lib.py.cad.verification v0.16.0` @
  `c7c145b7be0c602724e8cca874ef29990baaad1e`.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #130 Publish lib.py.cad.ci 0.18.1 | **now** | Qualify, merge and verify the immutable release, then repin the thin tool. |
| #89 Align historical changelog | later / docs-only | Keep separate from the active Forge migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- source inventory remains one enumeration per run;
- verification package remains one shared target;
- only requesting repository builders gain that dependency;
- build123d/CadQuery compatible models remain one shared reference runtime;
- current/cache results avoid unnecessary package/runtime work.
