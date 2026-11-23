# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Release candidate

### #126 — publish 0.18.0 for Forge #740 owner contracts

**Now.**

Candidate implementation commit before release metadata:

`8eb5e031e93104cf85dd40f3a90e90ab8dbc213e`

Included owner changes:

- #121 — recursive `/**` matching preserves wildcard prefixes;
- #123 — repository-owned builders may request the root-pinned verification
  wheel through the public `verification_package: true` capability and
  `CAD_CI_VERIFICATION_WHEEL` environment;
- #128 — built-in CadQuery export accepts the documented `model` contract when
  final geometry is a `cq.Assembly`, as required by the Forge #740 consumer
  migration.

Release requirements:

1. #128 is implemented and qualified without restoring consumer-owned CadQuery
   export code or adding per-model runtime starts;
2. VERSION and pyproject declare exactly 0.18.0;
3. CHANGELOG records all public behavior changes;
4. installed-wheel/SCons CI is green on the release PR;
5. merge the release PR;
6. verify immutable `v0.18.0` targets the exact tested release commit;
7. repin/release the thin `tool.cad.ci`;
8. black-box accept the exact tool/library pair before Forge #740 resumes.

## Accepted baseline before this release

- `lib.py.cad.ci v0.17.2` @
  `d4e8140d988be06460326fda802e514b6b306d64`;
- `tool.cad.ci v0.33.2` @
  `4812d87304109a68538d844e8baa5bacdbbc198d`;
- `lib.py.cad.verification v0.16.0` @
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external acceptance #240 green for that baseline.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #128 Built-in CadQuery exports cq.Assembly | **now / blocks #126** | Define the generic Assembly export contract, implement it in the shared builder, and qualify Forge #755 without consumer exporter glue. |
| #126 Publish lib.py.cad.ci 0.18.0 | **blocked on #128** | After #128 is qualified, publish the combined owner-contract release, verify immutable tag, then repin tool. |
| #89 Align historical changelog | later / docs-only | Keep separate from the active Forge migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- source inventory remains one enumeration per run;
- verification package remains one shared target;
- only requesting repository builders gain that dependency;
- current/cache results avoid unnecessary package/runtime work.
