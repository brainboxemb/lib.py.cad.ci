# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

## Accepted implementation baseline

- `lib.py.cad.ci v0.17.2` @
  `d4e8140d988be06460326fda802e514b6b306d64`;
- `tool.cad.ci v0.33.2` @
  `4812d87304109a68538d844e8baa5bacdbbc198d`;
- `lib.py.cad.verification v0.16.0` @
  `c7c145b7be0c602724e8cca874ef29990baaad1e`;
- external released-stack acceptance #240 is complete, including real
  build123d/CadQuery cold/current/rebuild behavior.

Forge #740 is the active consumer migration and has exposed two generic owner
requirements that must be fixed here before Forge adopts them.

## Current work

### #121 — wildcard prefixes before trailing /**

**Now.**

Configured recursive patterns such as `examples/*/scpf/**` must preserve normal
wildcard semantics in the prefix while retaining literal `folder/**`
folder-and-descendant behavior.

This is a focused path-matching correctness fix. It must not change planning,
selection fan-out, SCons scheduling or source-inventory ownership.

### #123 — public verification package for repository-owned builders

**Next after #121.**

Expose the root-pinned verification wheel to repository-owned builders through a
public builder capability/environment contract. Consumers must not name the
internal synthesized package item.

After #121 and #123 are green, publish one coherent owner release, repin/release
the thin tool, black-box accept the new stack, then resume Forge #740.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #121 Make trailing /** path matching honor wildcard prefixes | **now** | Fix/document/test recursive wildcard prefix semantics. |
| #123 Expose pinned verification wheel to repository-owned builders | **next** | Add public builder capability after #121. |
| #89 Align historical changelog | later / docs-only | Keep separate from active consumer migration. |

## Performance boundary

- SCons remains the only rebuild/reuse engine;
- source inventory remains one enumeration per run;
- path matching must not introduce a second repository scan;
- one compatible N-model build+verification batch means one Docker runtime
  start;
- current/cache results avoid Docker and engine-process startup entirely.
