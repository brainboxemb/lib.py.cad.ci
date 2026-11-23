"""Resolve, prepare and publish durable complete build scopes.

This module owns generic state needed by long-lived complete scopes such as
`main` and caller-named integration scopes.  GitHub workflow adapters supply
repository paths/ref names; they do not interpret build manifests themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import shutil
import tempfile

from .build_store import (
    BuildStoreError,
    MANIFEST,
    _complete_scope_contract,
    load_manifest,
    prepare_main,
    prepare_named,
    update_main,
    update_named,
)
from .config import load_repository, load_repository_config
from .git import changed_files
from .git_publish import (
    materialize_generated_branch,
    publish_build_scope,
    publish_pages,
)
from .planner import affected_items


_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class DurableScopeState:
    """Resolved source state for one complete durable build scope."""

    scope: str
    base_sha: str
    full_run: bool
    exists: bool


def _exact_sha(value: str, name: str) -> str:
    """Return one exact lowercase Git commit id."""

    normalized = value.strip()
    if _SHA.fullmatch(normalized) is None:
        raise BuildStoreError(
            f"{name} must be exactly 40 lowercase hex characters"
        )
    return normalized


def _scope_name(value: str) -> tuple[str, str, str | None]:
    """Return normalized name plus expected manifest scope/name fields."""

    manifest_scope, manifest_name = _complete_scope_contract(value)
    normalized = "main" if manifest_scope == "main" else manifest_name
    assert normalized is not None
    return normalized, manifest_scope, manifest_name


def resolve_durable_scope_state(
    *,
    generated_build: Path,
    scope: str,
    source_sha: str,
) -> DurableScopeState:
    """Resolve full/incremental selection from one materialized build tree."""

    source_sha = _exact_sha(source_sha, "source_sha")
    scope, manifest_scope, manifest_name = _scope_name(scope)
    root = generated_build.resolve() / scope
    manifest = root / MANIFEST

    if not manifest.is_file():
        if scope == "main":
            raise BuildStoreError(
                "durable main scope is missing; stable integration cannot "
                "be updated incrementally"
            )
        return DurableScopeState(
            scope=scope,
            base_sha=source_sha,
            full_run=True,
            exists=False,
        )

    value = load_manifest(
        root,
        expected_scope=manifest_scope,
        expected_name=manifest_name,
    )
    base_sha = value.get("source_commit")
    if not isinstance(base_sha, str):
        raise BuildStoreError(
            f"durable scope has invalid source_commit: {scope}"
        )
    base_sha = _exact_sha(base_sha, "stored source_commit")
    return DurableScopeState(
        scope=scope,
        base_sha=base_sha,
        full_run=False,
        exists=True,
    )


def fetch_durable_scope_state(
    *,
    repo: Path,
    generated_build: Path,
    scope: str,
    source_sha: str,
    branch: str = "build",
    remote: str = "origin",
) -> DurableScopeState:
    """Materialize the generated build branch and resolve one complete scope."""

    generated_build = generated_build.resolve()
    if generated_build.exists():
        if generated_build.is_dir():
            shutil.rmtree(generated_build)
        else:
            generated_build.unlink()
    materialized = materialize_generated_branch(
        source_repo=repo.resolve(),
        branch=branch,
        out=generated_build,
        remote=remote,
        missing_ok=True,
    )
    if materialized is None:
        normalized_scope, _, _ = _scope_name(scope)
        return DurableScopeState(
            scope=normalized_scope,
            base_sha=_exact_sha(source_sha, "source_sha"),
            full_run=True,
            exists=False,
        )
    return resolve_durable_scope_state(
        generated_build=generated_build,
        scope=scope,
        source_sha=source_sha,
    )


def _processed_items(items):
    """Return current processed items in repository order."""

    selected = affected_items(items, None)
    return tuple(
        item
        for item_id, item in items.items()
        if item_id in selected
    )


def _affected_items(repo: Path, items, state: DurableScopeState, source_sha: str):
    """Return current items that replace durable state in this publication."""

    if state.full_run:
        return _processed_items(items)
    changed = changed_files(repo, state.base_sha, source_sha)
    selected = affected_items(items, changed)
    return tuple(
        item
        for item_id, item in items.items()
        if item_id in selected
    )


def publish_durable_scope(
    *,
    repo: Path,
    generated_build: Path,
    prepared_scope: Path,
    candidate_root: Path,
    state: DurableScopeState,
    source_sha: str,
    source_ref: str,
    build_branch: str = "build",
    remote: str = "origin",
    retries: int = 3,
) -> str:
    """Prepare and publish one complete main/named scope from a CAD-CI run."""

    repo = repo.resolve()
    generated_build = generated_build.resolve()
    prepared_scope = prepared_scope.resolve()
    candidate_root = candidate_root.resolve()
    source_sha = _exact_sha(source_sha, "source_sha")
    source_ref = source_ref.strip()
    if not source_ref:
        raise BuildStoreError("source_ref is required for durable publication")

    scope, manifest_scope, _ = _scope_name(state.scope)
    if scope != state.scope:
        raise BuildStoreError("durable scope state is not normalized")
    if state.full_run and state.exists:
        raise BuildStoreError("existing durable scope cannot require a full run")
    if not state.full_run:
        _exact_sha(state.base_sha, "base_sha")

    if prepared_scope.exists():
        if prepared_scope.is_dir():
            shutil.rmtree(prepared_scope)
        else:
            prepared_scope.unlink()

    items = load_repository(repo)
    selected_items = _affected_items(repo, items, state, source_sha)
    current_items = _processed_items(items)

    if manifest_scope == "main":
        if state.exists:
            update_main(
                main=generated_build / "main",
                candidate_root=candidate_root,
                out=prepared_scope,
                items=selected_items,
                current_items=current_items,
                source_commit=source_sha,
            )
        else:
            prepare_main(
                candidate_root=candidate_root,
                out=prepared_scope,
                items=current_items,
                source_commit=source_sha,
            )
        publish_scope = "main"
        scope_name = None
    elif state.exists:
        update_named(
            named=generated_build / scope,
            candidate_root=candidate_root,
            out=prepared_scope,
            items=selected_items,
            current_items=current_items,
            source_commit=source_sha,
            name=scope,
        )
        publish_scope = "named"
        scope_name = scope
    else:
        prepare_named(
            candidate_root=candidate_root,
            out=prepared_scope,
            items=current_items,
            source_commit=source_sha,
            name=scope,
        )
        publish_scope = "named"
        scope_name = scope

    return publish_build_scope(
        source_repo=repo,
        candidate=prepared_scope,
        scope=publish_scope,
        scope_name=scope_name,
        message=f"build: {scope} {source_sha}",
        branch=build_branch,
        remote=remote,
        retries=retries,
        source_ref=source_ref,
        expected_source=source_sha,
    )


def configured_pages_site(repo: Path, complete_scope: Path) -> Path | None:
    """Return the configured Pages directory inside one complete scope."""

    repository = load_repository_config(repo.resolve())
    pages = repository.pages
    if pages is None:
        return None
    item = repository.items[pages.item]
    site = complete_scope.resolve() / item.path / pages.output
    if not site.is_dir():
        raise BuildStoreError(
            "configured Pages output is not a directory in complete scope: "
            f"{pages.item}:{pages.output}"
        )
    return site


def _named_complete_scopes(generated_build: Path) -> tuple[str, ...]:
    """Return validated named complete scopes present in one build tree."""

    names: list[str] = []
    root = generated_build.resolve()
    if not root.is_dir():
        return ()
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name in {"main", "pr"}:
            continue
        if not (child / MANIFEST).is_file():
            continue
        _, manifest_scope, manifest_name = _scope_name(child.name)
        if manifest_scope != "named" or manifest_name is None:
            continue
        load_manifest(
            child,
            expected_scope="named",
            expected_name=manifest_name,
        )
        names.append(child.name)
    return tuple(names)


def publish_durable_pages(
    *,
    repo: Path,
    generated_build: Path,
    prepared_scope: Path,
    state: DurableScopeState,
    source_sha: str,
    source_ref: str,
    build_commit: str,
    pages_branch: str = "gh-pages",
    remote: str = "origin",
    retries: int = 3,
) -> str | None:
    """Publish configured stable/named Pages from one prepared complete scope.

    The consumer-owned builder produces only site content. CAD-CI adds generic
    publication provenance to a temporary copy so the durable build output is
    not mutated after its build-branch commit has been published.
    """

    repo = repo.resolve()
    source_sha = _exact_sha(source_sha, "source_sha")
    build_commit = _exact_sha(build_commit, "build_commit")
    source_ref = source_ref.strip()
    if not source_ref:
        raise BuildStoreError("source_ref is required for durable Pages publication")

    site = configured_pages_site(repo, prepared_scope)
    if site is None:
        return None

    scope, manifest_scope, _ = _scope_name(state.scope)
    if scope != state.scope:
        raise BuildStoreError("durable scope state is not normalized")

    preserve = _named_complete_scopes(generated_build) if manifest_scope == "main" else ()
    name = None if manifest_scope == "main" else scope

    with tempfile.TemporaryDirectory(prefix="cad-ci-pages-") as tmp:
        publish_site = Path(tmp) / "site"
        shutil.copytree(site, publish_site)
        (publish_site / "provenance.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "source_commit": source_sha,
                    "build_commit": build_commit,
                    "build_scope": scope,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return publish_pages(
            source_repo=repo,
            site=publish_site,
            name=name,
            preserve_subtrees=preserve,
            message=f"pages: {scope} {source_sha}",
            branch=pages_branch,
            remote=remote,
            retries=retries,
            source_ref=source_ref,
            expected_source=source_sha,
        )
