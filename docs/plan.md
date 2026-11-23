# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted implementation baseline

- `lib.py.cad.ci v0.17.2` @
  `d4e8140d988be06460326fda802e514b6b306d64`;
- wildcard-recursive path correctness #121 merged at
  `6b19712f6c798a7d10b8f3725ac161e65a72815f`;
- `tool.cad.ci v0.33.2` remains the currently released thin wrapper;
- `lib.py.cad.verification v0.16.0` remains immutable at
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external released-stack acceptance #240 is complete for the v0.17.2 /
  v0.33.2 baseline.

Forge #740 is the active consumer migration. It requires one additional public
owner capability before Forge can remove its local verification-package
producer without depending on a library-internal item id.

## Current work

### #123 — public verification package for repository-owned builders

**Now.**

Add one declarative repository-builder capability:

```yaml
schema: 1
verification_package: true
```

Required public behavior:

1. root `verification.package` is required;
2. the existing exact verification package is materialized once;
3. the requesting item receives the normal SCons dependency internally;
4. command actions receive `CAD_CI_VERIFICATION_WHEEL` pointing at the exact
   wheel in their target-private dependency snapshot;
5. consumers never name `cad-ci-verification-package`;
6. unrelated builders/items are unaffected;
7. Pages publication builders cannot request this SCons-only capability.

After #123 is merged, publish the next library release, repin/release
`tool.cad.ci`, black-box accept the exact stack, then resume Forge #740.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #123 Expose pinned verification wheel to repository-owned builders | **now** | Implement/document/test the public builder capability and environment. |
| #89 Align historical changelog | later / docs-only | Keep separate from the active Forge migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- verification-package materialization remains one shared target;
- only requesting repository builders gain the package dependency;
- source inventory remains one enumeration per run;
- current/cache results avoid unnecessary package/runtime work.
