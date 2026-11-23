# Repository plan

Current source of truth for unfinished work in `lib.py.cad.ci` (2026-11-23).

This repository owns generic CAD-CI planning/execution, durable build-store and
complete-scope state, Pages and generated-branch publication semantics.
Tool/workflow repositories adapt these APIs; they do not reimplement them.

## Released and accepted baseline

- `lib.py.cad.ci 0.14.0` @
  `b24e9a3826dfc07e07b4f3fd9971fcb4ab5aa12d`;
- `tool.cad.ci v0.31.0` @
  `27bdf67077ddd485cea95ba199069249c20c2a46` pins that exact library;
- `tool.cad.ci.test` #223 externally accepted the complete v0.31 stack,
  including normal CI, durable publication, permanent-branch governance,
  exact-SHA retirement and cleanup;
- configurable generated build/Page branch names are accepted with
  compatibility defaults `build` / `gh-pages`.

## Current work

### #102 — post-build repository-owned Pages renderer

**Now.** Forge #740 exposed a generic publication gap.

The existing `publication.pages.item/output` mode is correct for sites that are
fully buildable before durable build publication. It cannot preserve a site
that needs the prepared complete-scope manifest and the exact generated
`build_commit`: those values are only authoritative/available after the normal
CAD-CI graph and durable build publication.

Add a second, mutually exclusive Pages mode:

```yaml
publication:
  pages:
    builder: pages-site
    output: site
```

The builder name resolves through the existing root `builders:` mapping.

Execution contract:

1. run the normal CAD-CI/SCons graph exactly once;
2. prepare and publish the durable complete scope exactly once;
3. after the exact build commit exists, execute the configured repository-owned
   Pages builder once as a publication renderer, not as a SCons target;
4. expose read-only publication context through CAD-CI-owned environment:
   complete-scope path, logical scope, source SHA/ref and exact build commit,
   plus one temporary `CAD_CI_OUTPUT` root;
5. require this publication builder to contain exactly one command step;
   engine-owned copy actions and multi-step execution are not supported in this
   mode;
6. validate the configured output with the existing safe output rules;
7. add generic `provenance.json` and publish with the existing stable/named
   Pages replacement/preservation semantics.

The existing item/output mode remains behaviorally unchanged.

This is **not** a second scheduler, SCons graph, cache/reuse engine or GitHub
workflow execution route.

Required order:

1. define requirements/design/SCons acceptance before implementation;
2. implement config/model + one-shot publication renderer + tests;
3. merge and release the exact library;
4. update/release `tool.cad.ci` to that exact library;
5. black-box accept the exact tool release in `tool.cad.ci.test`;
6. resume Forge #740 only after that acceptance.

## Open issue assessment

| Issue | Status | Next |
| --- | --- | --- |
| #102 Repository-owned Pages rendering after durable build publication | **now** | Define contract, implement/test, release, then tool/test adoption. |
| #89 Align historical changelog | **later / docs-only** | Apply shared changelog presentation without runtime/API changes. |

## Non-goals

- no second scheduler/freshness/rebuild engine;
- no second CAD-CI/SCons graph for publication;
- no consumer/domain-specific Forge/CAD concepts;
- no GitHub-specific workflow orchestration;
- no consumer Git branch mutation;
- no executable command embedded directly in root `cad-ci.yml`;
- no change to existing `publication.pages.item/output` behavior.
