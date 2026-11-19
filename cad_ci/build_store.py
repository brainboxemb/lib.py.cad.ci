"""Prepare, validate and combine durable per-item build output.

Consumer execution writes candidate output below build/<source-item-path>/ and
public evidence below that item's reserved .cad-ci directory. This module copies
only validated complete item results into the generated build-branch layout:

- main/ is the complete accepted baseline;
- pr/<number>/ is a sparse overlay for one pull request.

SCons private state and CacheDir content are never part of this store.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

from .model import Item


MANIFEST = "build.json"
ITEM_STATE = Path(".cad-ci/item.json")
BUILD_SCHEMA = 1
EVIDENCE_SCHEMA = 1
ENGINE = "scons"
ENGINE_SCHEMA = 1


class BuildStoreError(RuntimeError):
    """Raised when candidate or stored build output cannot be trusted."""


def _safe_relative(path: Path | str) -> Path:
    """Return a safe repository-relative item storage path."""

    value = Path(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise BuildStoreError(f"unsafe item path: {path}")
    return value


def _read_json(path: Path) -> dict:
    """Read one JSON object and report malformed generated state clearly."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildStoreError(f"missing generated file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildStoreError(f"invalid JSON in generated file: {path}") from exc
    if not isinstance(data, dict):
        raise BuildStoreError(f"generated JSON must be an object: {path}")
    return data


def _replace_tree(source: Path, target: Path) -> None:
    """Replace one directory without exposing a half-copied destination."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}-",
            dir=target.parent,
        )
    )
    shutil.rmtree(temp)
    try:
        shutil.copytree(source, temp)
        old = target.parent / f".{target.name}.previous"
        if old.exists():
            shutil.rmtree(old)
        if target.exists():
            target.rename(old)
        try:
            temp.rename(target)
        except Exception:
            if old.exists() and not target.exists():
                old.rename(target)
            raise
        if old.exists():
            shutil.rmtree(old)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def _nonempty_string(
    value: object,
    field: str,
    item_path: Path,
) -> str:
    """Read one required non-empty string from item evidence."""

    if not isinstance(value, str) or not value:
        raise BuildStoreError(
            f"item evidence has no {field}: {item_path.as_posix()}"
        )
    return value


def _item_record(
    candidate_root: Path,
    item: Item,
    source_commit: str,
) -> dict:
    """Validate one complete SCons item result and build its manifest row."""

    item_path = _safe_relative(item.path)
    item_root = candidate_root / item_path
    if not item_root.is_dir():
        raise BuildStoreError(
            f"missing candidate item: {item_path.as_posix()}"
        )

    evidence = _read_json(item_root / ITEM_STATE)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise BuildStoreError(
            f"unsupported item evidence schema: {item_path.as_posix()}"
        )
    if evidence.get("engine") != ENGINE:
        raise BuildStoreError(
            f"item evidence is not from SCons: {item_path.as_posix()}"
        )
    if evidence.get("engine_schema") != ENGINE_SCHEMA:
        raise BuildStoreError(
            f"unsupported SCons evidence schema: {item_path.as_posix()}"
        )
    if evidence.get("status") != "pass":
        raise BuildStoreError(
            f"item is not complete/pass: {item_path.as_posix()}"
        )
    if evidence.get("item") != item.id:
        raise BuildStoreError(
            f"item evidence ID does not match config: {item_path.as_posix()}"
        )

    expected_final_step = item.steps[-1].id
    if evidence.get("final_step") != expected_final_step:
        raise BuildStoreError(
            "item evidence final step does not match config: "
            f"{item_path.as_posix()}"
        )

    spec_digest = _nonempty_string(
        evidence.get("final_target_spec_digest"),
        "final_target_spec_digest",
        item_path,
    )
    bundle_digest = _nonempty_string(
        evidence.get("final_bundle_sha256"),
        "final_bundle_sha256",
        item_path,
    )

    return {
        "source_commit": source_commit,
        "item_id": item.id,
        "engine": ENGINE,
        "engine_schema": ENGINE_SCHEMA,
        "final_step": expected_final_step,
        "final_target_spec_digest": spec_digest,
        "final_bundle_sha256": bundle_digest,
    }


def _items(values: Iterable[Item], *, operation: str) -> tuple[Item, ...]:
    """Freeze and validate the item set supplied by the consumer config."""

    result = tuple(values)
    if not result:
        raise BuildStoreError(f"{operation} requires at least one item")

    paths: set[Path] = set()
    for item in result:
        path = _safe_relative(item.path)
        if path in paths:
            raise BuildStoreError(
                f"duplicate item path: {path.as_posix()}"
            )
        paths.add(path)
    return result


def _write_manifest(out: Path, manifest: dict) -> None:
    """Write one stable build-scope manifest."""

    (out / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_main(
    *,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
) -> dict:
    """Create a complete main candidate from validated item results."""

    configured = _items(items, operation="main candidate")

    # Validate every item before exposing any output candidate.
    rows = {
        item.path.as_posix(): _item_record(
            candidate_root,
            item,
            source_commit,
        )
        for item in configured
    }

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for item in configured:
        target = out / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate_root / item.path, target)

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": "main",
        "source_commit": source_commit,
        "items": rows,
    }
    _write_manifest(out, manifest)
    return manifest


def update_main(
    *,
    main: Path,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
) -> dict:
    """Replace selected validated item paths in one complete main baseline."""

    main_manifest = load_manifest(main, expected_scope="main")
    configured = _items(items, operation="main update")

    replacements = {
        item.path: _item_record(
            candidate_root,
            item,
            source_commit,
        )
        for item in configured
    }

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(main, out)

    rows = dict(main_manifest["items"])
    for item_path, row in replacements.items():
        _replace_tree(
            candidate_root / item_path,
            out / item_path,
        )
        rows[item_path.as_posix()] = row

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": "main",
        "source_commit": source_commit,
        "items": rows,
    }
    _write_manifest(out, manifest)
    return manifest


def prepare_overlay(
    *,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    pull_request: int,
) -> dict:
    """Create one sparse PR overlay from selected complete item results."""

    if pull_request <= 0:
        raise BuildStoreError("pull_request must be positive")
    configured = _items(items, operation="overlay")

    rows = {
        item.path.as_posix(): _item_record(
            candidate_root,
            item,
            source_commit,
        )
        for item in configured
    }

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for item in configured:
        target = out / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate_root / item.path, target)

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": "pr",
        "pull_request": pull_request,
        "source_commit": source_commit,
        "items": rows,
    }
    _write_manifest(out, manifest)
    return manifest


def _validate_stored_row(
    root: Path,
    item_path: str,
    row: object,
) -> None:
    """Validate manifest/evidence consistency for one stored item."""

    safe_path = _safe_relative(item_path)
    if not isinstance(row, dict):
        raise BuildStoreError(
            f"invalid item manifest row: {item_path}"
        )

    source_commit = row.get("source_commit")
    if not isinstance(source_commit, str) or not source_commit:
        raise BuildStoreError(
            f"item manifest has no source_commit: {item_path}"
        )

    evidence = _read_json(root / safe_path / ITEM_STATE)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise BuildStoreError(
            f"unsupported item evidence schema: {item_path}"
        )
    if (
        evidence.get("engine") != row.get("engine")
        or evidence.get("engine_schema") != row.get("engine_schema")
        or evidence.get("item") != row.get("item_id")
        or evidence.get("final_step") != row.get("final_step")
        or evidence.get("final_target_spec_digest")
        != row.get("final_target_spec_digest")
        or evidence.get("final_bundle_sha256")
        != row.get("final_bundle_sha256")
        or evidence.get("status") != "pass"
    ):
        raise BuildStoreError(
            f"item manifest does not match evidence: {item_path}"
        )


def load_manifest(
    root: Path,
    *,
    expected_scope: str | None = None,
) -> dict:
    """Read and validate one durable build-scope manifest."""

    data = _read_json(root / MANIFEST)
    if data.get("schema") != BUILD_SCHEMA:
        raise BuildStoreError(
            f"unsupported build manifest schema in {root}"
        )

    scope = data.get("scope")
    if scope not in {"main", "pr"}:
        raise BuildStoreError(
            f"invalid build scope in {root}: {scope!r}"
        )
    if expected_scope is not None and scope != expected_scope:
        raise BuildStoreError(
            f"expected {expected_scope} build scope in {root}, found {scope}"
        )

    rows = data.get("items")
    if not isinstance(rows, dict):
        raise BuildStoreError(
            f"build manifest has no item map: {root}"
        )
    for item_path, row in rows.items():
        _validate_stored_row(root, item_path, row)
    return data


def resolve_view(
    *,
    main: Path,
    overlay: Path | None,
    out: Path,
) -> dict:
    """Create a complete view from main plus an optional sparse PR overlay."""

    main_manifest = load_manifest(main, expected_scope="main")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(main, out)

    merged_items = dict(main_manifest["items"])
    source_commit = main_manifest.get("source_commit", "")
    if overlay is not None:
        overlay_manifest = load_manifest(
            overlay,
            expected_scope="pr",
        )
        for item_path, row in overlay_manifest["items"].items():
            _replace_tree(
                overlay / item_path,
                out / item_path,
            )
            merged_items[item_path] = row
        source_commit = overlay_manifest.get(
            "source_commit",
            source_commit,
        )

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": "main",
        "source_commit": source_commit,
        "items": merged_items,
    }
    _write_manifest(out, manifest)
    return manifest


def promote_overlay(
    *,
    main: Path,
    overlay: Path,
    out: Path,
    source_commit: str,
) -> dict:
    """Create the next main baseline by replacing only overlay item paths."""

    main_manifest = load_manifest(main, expected_scope="main")
    overlay_manifest = load_manifest(
        overlay,
        expected_scope="pr",
    )

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(main, out)

    merged_items = dict(main_manifest["items"])
    for item_path, row in overlay_manifest["items"].items():
        _replace_tree(
            overlay / item_path,
            out / item_path,
        )
        merged_items[item_path] = row

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": "main",
        "source_commit": source_commit,
        "items": merged_items,
    }
    _write_manifest(out, manifest)
    return manifest


def install_scope(
    *,
    candidate: Path,
    store: Path,
    scope: str,
    pull_request: int | None = None,
) -> Path:
    """Install one validated scope in a checked-out generated build branch."""

    if scope == "main":
        load_manifest(candidate, expected_scope="main")
        target = store / "main"
    elif scope == "pr":
        load_manifest(candidate, expected_scope="pr")
        if pull_request is None or pull_request <= 0:
            raise BuildStoreError(
                "PR scope requires a positive pull_request"
            )
        target = store / "pr" / str(pull_request)
    else:
        raise BuildStoreError(f"unknown scope: {scope}")

    _replace_tree(candidate, target)
    return target


def remove_pr(*, store: Path, pull_request: int) -> bool:
    """Remove one PR overlay without changing any other durable scope."""

    if pull_request <= 0:
        raise BuildStoreError("pull_request must be positive")
    target = store / "pr" / str(pull_request)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
