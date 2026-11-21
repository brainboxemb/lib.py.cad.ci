# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current status

`lib.py.cad.ci 0.9.0` is the current released library.

The existing durable publication model distinguishes only:

- complete `main` build state;
- sparse `pr/<number>` overlays;
- stable Pages root;
- PR previews below `previews/pr-<number>`.

Forge #572 needs two long-lived development integration lanes in addition to
stable `main`. That requires a generic named complete-scope contract here
rather than Forge-local generated-branch logic.

## Current goal

Complete #72: support generic named complete build scopes and named Pages
subtrees while preserving all existing main/PR behavior.

The intended consumer model is:

```text
build/
  main/
  <named-scope-a>/
  <named-scope-b>/

gh-pages/
  <stable root>
  <named-subtree-a>/
  <named-subtree-b>/
```

Names are caller-owned safe relative names. This library must not know
`dev_cad`, `dev_ci` or any Forge-specific branch name.

## Required proof

- a named complete build scope uses the same reconciliation semantics as main;
- updating one named scope preserves main and every unrelated sibling scope;
- invalid/unsafe scope names are rejected;
- generated-branch freshness and retry guarantees remain unchanged;
- named Pages publication replaces only its subtree;
- stable-root publication preserves configured named subtrees;
- named publication cannot remove or overwrite stable root or siblings;
- existing main and PR publication tests remain green.

## Execution order

1. [#72, now] Define safe generic named-scope semantics.
2. [#72] Generalize complete build-scope preparation/update/install.
3. [#72] Add named Pages subtree installation/publication.
4. [#72] Extend generated-branch tests for sibling preservation and races.
5. [#72] Release the exact green library revision.
6. [tool.cad.ci #80] Expose the released behavior through the thin CLI/workflow layer.
7. [tool.cad.ci.test #60] Black-box accept named build and Pages scopes.
8. [Forge #572] Introduce `dev_cad` and `dev_ci` only after the released stack is accepted.

## Open issue assessment — 2026-11-21

| Issue | Status | Assessment |
| --- | --- | --- |
| #72 Support named complete build scopes and named Pages subtrees | now | Required generic publication primitive for Forge #572 and any future long-lived integration lane. |
| #71 Reduce fixed selective-run startup overhead before first SCons target | later | Independent performance work. Do not mix it into the named-scope migration. |

Immediate chain:

`#72 library -> tool #80 -> acceptance #60 -> Forge #572`.
