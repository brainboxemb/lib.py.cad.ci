"""Prepare, validate and combine durable per-item build output.

Consumer execution writes candidate output below build/<source-item-path>/ and
public evidence below that item's reserved .cad-ci directory. This module copies
only validated complete item results into the generated build-branch layout:

- main/ is the complete accepted baseline;
- caller-named top-level scopes are independent complete baselines;
- pr/<number>/ is a sparse overlay for one pull request.

SCons private state and CacheDir content are never part of this store.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

from ..model import Item
from ..scons.engine import ENGINE_SCHEMA


MANIFEST = "build.json"
ITEM_STATE = Path(".cad-ci/item.json")
BUILD_SCHEMA = 1
CURRENT_EVIDENCE_SCHEMA = 2
READABLE_STORED_EVIDENCE_SCHEMAS = frozenset({1, 2})
ENGINE = "scons"


class BuildStoreError(RuntimeError):
    """Raised when candidate or stored build output cannot be trusted."""


def _safe_relative(path: Path | str) -> Path:
    """Return a safe repository-relative item storage path."""

    value = Path(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise BuildStoreError(f"unsafe item path: {path}")
    return value


def _safe_scope_name(name: str) -> str:
    """Return one safe top-level complete-scope name."""

    if not isinstance(name, str) or not name.strip():
        raise BuildStoreError("scope name must be non-empty text")
    value = name.strip()
    path = Path(value)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or value in {".", "..", "pr"}
        or "/" in value
        or "\\" in value
    ):
        raise BuildStoreError(f"unsafe scope name: {name}")
    return value


def _complete_scope_contract(scope_name: str) -> tuple[str, str | None]:
    """Return manifest scope/name fields for one complete scope."""

    name = _safe_scope_name(scope_name)
    if name == "main":
        return "main", None
    return "named", name


def _safe_owned_output(path: Path | str) -> Path:
    """Return one safe consumer-owned output path."""

    value = _safe_relative(path)
    if value.parts[0] == ".cad-ci":
        raise BuildStoreError("consumer output may not use .cad-ci")
    return value


def _owned_outputs(item: Item) -> tuple[Path, ...]:
    """Return the stable unique output paths owned by one configured item."""

    values = {
        _safe_owned_output(output)
        for step in item.steps
        for output in step.outputs
    }
    return tuple(sorted(values, key=lambda path: path.as_posix()))


def _row_outputs(row: dict, item_path: Path) -> tuple[Path, ...] | None:
    """Read optional durable ownership metadata from one stored row."""

    value = row.get("outputs")
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(output, str) for output in value
    ):
        raise BuildStoreError(
            f"invalid item outputs metadata: {item_path.as_posix()}"
        )

    outputs = tuple(_safe_owned_output(output) for output in value)
    if len(outputs) != len(set(outputs)):
        raise BuildStoreError(
            f"duplicate item outputs metadata: {item_path.as_posix()}"
        )
    return tuple(sorted(outputs, key=lambda path: path.as_posix()))


def _paths_nested(left: Path, right: Path) -> bool:
    """Return whether two distinct repository paths are ancestor/descendant."""

    if left == right:
        return False
    left_parts = left.parts
    right_parts = right.parts
    common = min(len(left_parts), len(right_parts))
    return left_parts[:common] == right_parts[:common]


def _remove_entry(path: Path) -> None:
    """Remove one owned file/directory without touching neighboring paths."""

    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _prune_empty_parents(path: Path, stop: Path) -> None:
    """Prune empty generated directories without crossing the scope root."""

    current = path
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _copy_entry(source: Path, target: Path) -> None:
    """Copy one validated owned file/directory to its exact target path."""

    if source.is_symlink():
        raise BuildStoreError(f"owned output is a symlink: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            raise BuildStoreError(f"owned output target already exists: {target}")
        shutil.copytree(source, target)
        return
    if source.is_file():
        if target.exists():
            raise BuildStoreError(f"owned output target already exists: {target}")
        shutil.copy2(source, target)
        return
    raise BuildStoreError(f"missing owned output: {source}")


def _copy_owned_item(
    source_scope: Path,
    target_scope: Path,
    item_path: Path,
    outputs: tuple[Path, ...],
) -> None:
    """Copy exactly one item's outputs and public evidence."""

    source_item = source_scope / item_path
    target_item = target_scope / item_path

    for output in outputs:
        _copy_entry(source_item / output, target_item / output)
    _copy_entry(source_item / ".cad-ci", target_item / ".cad-ci")


def _replace_owned_item(
    source_scope: Path,
    target_scope: Path,
    item_path: Path,
    outputs: tuple[Path, ...],
) -> None:
    """Replace one item's owned paths while preserving nested neighbors."""

    target_item = target_scope / item_path
    for output in outputs:
        _remove_entry(target_item / output)
    _remove_entry(target_item / ".cad-ci")
    _copy_owned_item(source_scope, target_scope, item_path, outputs)


def _replace_stored_item(
    source_scope: Path,
    target_scope: Path,
    item_path: Path,
    row: dict,
    all_item_paths: tuple[Path, ...],
) -> None:
    """Replace one stored item using ownership metadata or safe legacy fallback."""

    outputs = _row_outputs(row, item_path)
    if outputs is not None:
        _replace_owned_item(
            source_scope,
            target_scope,
            item_path,
            outputs,
        )
        return

    if any(
        _paths_nested(item_path, other)
        for other in all_item_paths
        if other != item_path
    ):
        raise BuildStoreError(
            "legacy item ownership is ambiguous in nested layout: "
            f"{item_path.as_posix()}"
        )
    _replace_tree(source_scope / item_path, target_scope / item_path)


def _validate_removed_stored_item(
    item_path: Path,
    row: dict,
    all_item_paths: tuple[Path, ...],
) -> None:
    """Validate that one removed durable item has unambiguous ownership."""

    outputs = _row_outputs(row, item_path)
    if outputs is not None:
        return
    if any(
        _paths_nested(item_path, other)
        for other in all_item_paths
        if other != item_path
    ):
        raise BuildStoreError(
            "legacy item ownership is ambiguous in nested layout: "
            f"{item_path.as_posix()}"
        )


def _remove_stored_item(
    target_scope: Path,
    item_path: Path,
    row: dict,
    all_item_paths: tuple[Path, ...],
) -> None:
    """Remove one no-longer-configured item's owned durable state."""

    _validate_removed_stored_item(item_path, row, all_item_paths)
    outputs = _row_outputs(row, item_path)
    target_item = target_scope / item_path

    if outputs is None:
        _remove_entry(target_item)
        _prune_empty_parents(target_item.parent, target_scope)
        return

    for output in outputs:
        _remove_entry(target_item / output)
    _remove_entry(target_item / ".cad-ci")
    _prune_empty_parents(target_item, target_scope)


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
    if evidence.get("schema") != CURRENT_EVIDENCE_SCHEMA:
        raise BuildStoreError(
            f"unsupported current item evidence schema: "
            f"{item_path.as_posix()}"
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
        "outputs": [
            output.as_posix()
            for output in _owned_outputs(item)
        ],
    }


def _items(
    values: Iterable[Item],
    *,
    operation: str,
    allow_empty: bool = False,
) -> tuple[Item, ...]:
    """Freeze and validate the item set supplied by the consumer config."""

    result = tuple(values)
    if not result and not allow_empty:
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


def prepare_complete(
    *,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    scope_name: str,
) -> dict:
    """Create one complete named-scope candidate from validated item results."""

    manifest_scope, manifest_name = _complete_scope_contract(scope_name)
    operation = "main candidate" if scope_name == "main" else f"{scope_name} candidate"
    configured = _items(items, operation=operation)

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
        _copy_owned_item(
            candidate_root,
            out,
            item.path,
            _owned_outputs(item),
        )

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": manifest_scope,
        "source_commit": source_commit,
        "items": rows,
    }
    if manifest_name is not None:
        manifest["name"] = manifest_name
    _write_manifest(out, manifest)
    return manifest


def prepare_main(
    *,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
) -> dict:
    """Create the complete stable main candidate."""

    return prepare_complete(
        candidate_root=candidate_root,
        out=out,
        items=items,
        source_commit=source_commit,
        scope_name="main",
    )


def prepare_named(
    *,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    name: str,
) -> dict:
    """Create one complete caller-named candidate."""

    if _safe_scope_name(name) == "main":
        raise BuildStoreError("named scope may not use reserved name main")
    return prepare_complete(
        candidate_root=candidate_root,
        out=out,
        items=items,
        source_commit=source_commit,
        scope_name=name,
    )


def update_complete(
    *,
    complete: Path,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    scope_name: str,
    current_items: Iterable[Item] | None = None,
) -> dict:
    """Update selected items in one complete scope and reconcile membership."""

    manifest_scope, manifest_name = _complete_scope_contract(scope_name)
    complete_manifest = load_manifest(
        complete,
        expected_scope=manifest_scope,
        expected_name=manifest_name,
    )
    noun = "main" if scope_name == "main" else f"named scope {scope_name}"
    configured = _items(
        items,
        operation=f"{noun} update",
        allow_empty=current_items is not None,
    )
    current = (
        None
        if current_items is None
        else _items(
            current_items,
            operation=f"current {noun} configuration",
            allow_empty=True,
        )
    )

    selected_paths = {item.path for item in configured}
    previous_rows = dict(complete_manifest["items"])
    previous_paths = {
        _safe_relative(path)
        for path in previous_rows
    }

    removed_paths: set[Path] = set()
    all_item_paths = tuple(previous_paths)
    if current is not None:
        current_paths = {item.path for item in current}
        unknown_selected = selected_paths - current_paths
        if unknown_selected:
            names = ", ".join(
                sorted(path.as_posix() for path in unknown_selected)
            )
            raise BuildStoreError(
                f"selected item is not in current configuration: {names}"
            )

        missing_current = current_paths - (previous_paths | selected_paths)
        if missing_current:
            names = ", ".join(
                sorted(path.as_posix() for path in missing_current)
            )
            raise BuildStoreError(
                f"current {noun} item has no baseline or replacement: {names}"
            )

        removed_paths = previous_paths - current_paths
        all_item_paths = tuple(
            sorted(
                previous_paths | current_paths,
                key=lambda path: path.as_posix(),
            )
        )
        for item_path in removed_paths:
            _validate_removed_stored_item(
                item_path,
                previous_rows[item_path.as_posix()],
                all_item_paths,
            )

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
    shutil.copytree(complete, out)

    rows = dict(previous_rows)
    for item_path in sorted(
        removed_paths,
        key=lambda path: (-len(path.parts), path.as_posix()),
    ):
        _remove_stored_item(
            out,
            item_path,
            rows[item_path.as_posix()],
            all_item_paths,
        )
        rows.pop(item_path.as_posix())

    for item in configured:
        _replace_owned_item(
            candidate_root,
            out,
            item.path,
            _owned_outputs(item),
        )
        rows[item.path.as_posix()] = replacements[item.path]

    if current is not None:
        current_keys = {item.path.as_posix() for item in current}
        if set(rows) != current_keys:
            raise BuildStoreError(
                f"{noun} update did not produce the complete current item set"
            )

    manifest = {
        "schema": BUILD_SCHEMA,
        "scope": manifest_scope,
        "source_commit": source_commit,
        "items": rows,
    }
    if manifest_name is not None:
        manifest["name"] = manifest_name
    _write_manifest(out, manifest)
    return manifest


def update_main(
    *,
    main: Path,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    current_items: Iterable[Item] | None = None,
) -> dict:
    """Update selected items in the stable main complete scope."""

    return update_complete(
        complete=main,
        candidate_root=candidate_root,
        out=out,
        items=items,
        current_items=current_items,
        source_commit=source_commit,
        scope_name="main",
    )


def update_named(
    *,
    named: Path,
    candidate_root: Path,
    out: Path,
    items: Iterable[Item],
    source_commit: str,
    name: str,
    current_items: Iterable[Item] | None = None,
) -> dict:
    """Update selected items in one caller-named complete scope."""

    if _safe_scope_name(name) == "main":
        raise BuildStoreError("named scope may not use reserved name main")
    return update_complete(
        complete=named,
        candidate_root=candidate_root,
        out=out,
        items=items,
        current_items=current_items,
        source_commit=source_commit,
        scope_name=name,
    )

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
        _copy_owned_item(
            candidate_root,
            out,
            item.path,
            _owned_outputs(item),
        )

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
    if evidence.get("schema") not in READABLE_STORED_EVIDENCE_SCHEMAS:
        raise BuildStoreError(
            f"unsupported stored item evidence schema: {item_path}"
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
    expected_name: str | None = None,
) -> dict:
    """Read and validate one durable build-scope manifest."""

    data = _read_json(root / MANIFEST)
    if data.get("schema") != BUILD_SCHEMA:
        raise BuildStoreError(
            f"unsupported build manifest schema in {root}"
        )

    scope = data.get("scope")
    if scope not in {"main", "named", "pr"}:
        raise BuildStoreError(
            f"invalid build scope in {root}: {scope!r}"
        )
    if expected_scope is not None and scope != expected_scope:
        raise BuildStoreError(
            f"expected {expected_scope} build scope in {root}, found {scope}"
        )

    name = data.get("name")
    if scope == "named":
        if not isinstance(name, str):
            raise BuildStoreError(f"named build scope has no name in {root}")
        normalized_name = _safe_scope_name(name)
        if normalized_name == "main":
            raise BuildStoreError("named scope may not use reserved name main")
        if expected_name is not None and normalized_name != _safe_scope_name(expected_name):
            raise BuildStoreError(
                f"expected named build scope {expected_name}, found {normalized_name}"
            )
    elif name is not None:
        raise BuildStoreError(f"{scope} build scope may not declare a name")
    elif expected_name is not None:
        raise BuildStoreError(
            f"expected named build scope {expected_name}, found {scope}"
        )

    rows = data.get("items")
    if not isinstance(rows, dict):
        raise BuildStoreError(
            f"build manifest has no item map: {root}"
        )
    for item_path, row in rows.items():
        _validate_stored_row(root, item_path, row)
        _row_outputs(row, _safe_relative(item_path))
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
        resulting_items = dict(merged_items)
        resulting_items.update(overlay_manifest["items"])
        all_item_paths = tuple(
            _safe_relative(path)
            for path in resulting_items
        )
        for item_path, row in overlay_manifest["items"].items():
            _replace_stored_item(
                overlay,
                out,
                _safe_relative(item_path),
                row,
                all_item_paths,
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
    resulting_items = dict(merged_items)
    resulting_items.update(overlay_manifest["items"])
    all_item_paths = tuple(
        _safe_relative(path)
        for path in resulting_items
    )
    for item_path, row in overlay_manifest["items"].items():
        _replace_stored_item(
            overlay,
            out,
            _safe_relative(item_path),
            row,
            all_item_paths,
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
    scope_name: str | None = None,
) -> Path:
    """Install one validated scope in a checked-out generated build branch."""

    if scope == "main":
        load_manifest(candidate, expected_scope="main")
        target = store / "main"
    elif scope == "named":
        if scope_name is None:
            raise BuildStoreError("named scope requires scope_name")
        name = _safe_scope_name(scope_name)
        if name == "main":
            raise BuildStoreError("named scope may not use reserved name main")
        load_manifest(
            candidate,
            expected_scope="named",
            expected_name=name,
        )
        target = store / name
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
