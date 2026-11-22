"""Package and materialize declared step output for the SCons engine.

Each step has one deterministic regular-file target: an uncompressed tar
bundle. The bundle lets SCons CacheDir handle files and complete directories
uniformly, including empty directories.

This module verifies output integrity and materializes bundle contents. It does
not decide whether a step should rebuild; SCons owns that decision.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
from typing import Any


BUNDLE_MANIFEST = ".cad-ci/__bundle__.json"
BUNDLE_SCHEMA = 1
MATERIALIZATION_RESULTS = ("UNCHANGED", "RESTORED", "REPAIRED")


class BundleError(RuntimeError):
    """Raised when declared output cannot be bundled or restored safely."""


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_sha256(bundle: Path) -> str:
    """Return the digest used as durable evidence for one target bundle."""

    return _sha256_file(bundle)


def _normalize_output(value: str) -> str:
    """Return one safe POSIX output path relative to an item build root."""

    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and path.parts[0] == ".cad-ci")
    ):
        raise BundleError(f"unsafe declared output: {value}")
    return path.as_posix()


def _directory_digest(path: Path) -> str:
    """Hash complete directory membership and regular-file contents."""

    if path.is_symlink():
        raise BundleError(f"declared output is a symlink: {path}")
    if not path.is_dir():
        raise BundleError(f"declared directory output is not a directory: {path}")

    digest = hashlib.sha256()
    digest.update(b"directory\0")
    for child in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if child.is_symlink():
            raise BundleError(f"declared output contains a symlink: {child}")
        relative = child.relative_to(path).as_posix()
        if child.is_dir():
            digest.update(b"dir\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
        elif child.is_file():
            digest.update(b"file\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_sha256_file(child).encode("ascii"))
            digest.update(b"\0")
    return digest.hexdigest()


def output_snapshot(
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> dict[str, dict[str, Any]]:
    """Describe declared output, raising when anything is missing or unsafe."""

    result: dict[str, dict[str, Any]] = {}
    for raw in outputs:
        name = _normalize_output(str(raw))
        path = output_root / Path(name)
        if path.is_symlink():
            raise BundleError(f"declared output is a symlink: {path}")
        if path.is_file():
            result[name] = {
                "kind": "file",
                "sha256": _sha256_file(path),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        elif path.is_dir():
            result[name] = {
                "kind": "directory",
                "sha256": _directory_digest(path),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        else:
            raise BundleError(f"missing declared output: {name}")
    return result


def _normalized_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Normalize non-content archive metadata for deterministic bundle bytes."""

    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def _add_path(
    archive: tarfile.TarFile,
    path: Path,
    *,
    arcname: str,
) -> None:
    """Add one file/directory tree in lexical order without following links."""

    if path.is_symlink():
        raise BundleError(f"declared output is a symlink: {path}")

    entries = [path]
    if path.is_dir():
        entries.extend(
            sorted(path.rglob("*"), key=lambda value: value.as_posix())
        )

    for entry in entries:
        if entry.is_symlink():
            raise BundleError(f"declared output contains a symlink: {entry}")
        relative = entry.relative_to(path)
        member_name = (
            arcname
            if not relative.parts
            else f"{arcname}/{relative.as_posix()}"
        )
        info = _normalized_tar_info(
            archive.gettarinfo(str(entry), arcname=member_name)
        )
        if entry.is_file():
            with entry.open("rb") as handle:
                archive.addfile(info, handle)
        elif entry.is_dir():
            archive.addfile(info)
        else:
            raise BundleError(f"unsupported declared output entry: {entry}")


def write_bundle(
    bundle: Path,
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Write one deterministic target bundle for all declared step output."""

    normalized = tuple(_normalize_output(str(value)) for value in outputs)
    snapshot = output_snapshot(output_root, normalized)
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "outputs": snapshot,
    }

    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{bundle.name}.",
        suffix=".tmp",
        dir=bundle.parent,
        delete=False,
    ) as handle:
        temp = Path(handle.name)

    try:
        with tarfile.open(temp, "w") as archive:
            for name in sorted(normalized):
                _add_path(
                    archive,
                    output_root / Path(name),
                    arcname=name,
                )

            payload = (
                json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            info = tarfile.TarInfo(BUNDLE_MANIFEST)
            info.size = len(payload)
            info.mode = 0o644
            info = _normalized_tar_info(info)
            archive.addfile(info, io.BytesIO(payload))

        temp.replace(bundle)
    finally:
        temp.unlink(missing_ok=True)

    return manifest


def read_bundle_manifest(bundle: Path) -> dict[str, Any]:
    """Read and validate metadata stored inside one target bundle."""

    try:
        with tarfile.open(bundle, "r") as archive:
            member = archive.getmember(BUNDLE_MANIFEST)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise BundleError(f"bundle has no readable manifest: {bundle}")
            data = json.loads(extracted.read().decode("utf-8"))
    except (
        FileNotFoundError,
        KeyError,
        tarfile.TarError,
        json.JSONDecodeError,
    ) as exc:
        raise BundleError(f"invalid output bundle: {bundle}") from exc

    if not isinstance(data, dict) or data.get("schema") != BUNDLE_SCHEMA:
        raise BundleError(f"unsupported output bundle: {bundle}")
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        raise BundleError(f"bundle has no output map: {bundle}")
    return data


def outputs_match_bundle(
    bundle: Path,
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> bool:
    """Return whether materialized output exactly matches bundle metadata."""

    try:
        expected = read_bundle_manifest(bundle)["outputs"]
        normalized = tuple(_normalize_output(str(value)) for value in outputs)
        if set(expected) != set(normalized):
            return False
        return output_snapshot(output_root, normalized) == expected
    except BundleError:
        return False


def _remove_path(path: Path) -> None:
    """Remove one owned file/directory without following a symlink."""

    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def remove_outputs(
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> None:
    """Remove only the output paths owned by one step."""

    for raw in outputs:
        name = _normalize_output(str(raw))
        _remove_path(output_root / Path(name))


def _member_is_allowed(name: str, outputs: tuple[str, ...]) -> bool:
    """Return whether an archive member belongs to declared consumer output."""

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized = path.as_posix()
    return any(
        normalized == output
        or normalized.startswith(output.rstrip("/") + "/")
        for output in outputs
    )


def materialize_bundle(
    bundle: Path,
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> str:
    """Ensure output matches a bundle and report how materialization changed it."""

    normalized = tuple(_normalize_output(str(value)) for value in outputs)
    manifest = read_bundle_manifest(bundle)
    expected = manifest["outputs"]
    if set(expected) != set(normalized):
        raise BundleError("bundle outputs do not match configured outputs")

    if outputs_match_bundle(bundle, output_root, normalized):
        return "UNCHANGED"

    existed_before = any(
        (output_root / Path(name)).exists()
        or (output_root / Path(name)).is_symlink()
        for name in normalized
    )

    output_root.mkdir(parents=True, exist_ok=True)
    remove_outputs(output_root, normalized)

    try:
        with tarfile.open(bundle, "r") as archive:
            members: list[tarfile.TarInfo] = []
            for member in archive.getmembers():
                if member.name == BUNDLE_MANIFEST:
                    continue
                if member.issym() or member.islnk():
                    raise BundleError(
                        f"bundle contains an unsupported link: {member.name}"
                    )
                if not _member_is_allowed(member.name, normalized):
                    raise BundleError(
                        f"bundle member escapes declared output: {member.name}"
                    )
                members.append(member)
            archive.extractall(
                output_root,
                members=members,
                filter="data",
            )
    except tarfile.TarError as exc:
        raise BundleError(f"could not restore output bundle: {bundle}") from exc

    current = output_snapshot(output_root, normalized)
    if current != expected:
        raise BundleError("restored output does not match bundle metadata")

    return "REPAIRED" if existed_before else "RESTORED"


def _path_is_within(path: PurePosixPath, parent: PurePosixPath) -> bool:
    """Return whether path is parent itself or one of its descendants."""

    return path.parts[: len(parent.parts)] == parent.parts


def copy_dependency_outputs(
    source_bundle: Path,
    target_bundle: Path,
    source_root: str,
    outputs: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Build a consumer bundle from selected members of a dependency bundle.

    Only members below <source_root>/<declared output> are extracted. The
    dependency's complete output tree is never materialized.
    """

    normalized = tuple(_normalize_output(str(value)) for value in outputs)
    root_text = source_root.replace("\\", "/")
    root = PurePosixPath(root_text)
    if root_text in ("", "."):
        root = PurePosixPath(".")
    if (
        root.is_absolute()
        or ".." in root.parts
        or ".cad-ci" in root.parts
    ):
        raise BundleError(f"unsafe dependency copy source: {source_root}")

    manifest = read_bundle_manifest(source_bundle)
    dependency_outputs = tuple(
        PurePosixPath(str(name))
        for name in manifest["outputs"]
    )

    selected_roots: dict[str, PurePosixPath] = {}
    for output in normalized:
        selected = (
            PurePosixPath(output)
            if root.as_posix() == "."
            else root / PurePosixPath(output)
        )
        if not any(
            _path_is_within(selected, dependency_output)
            for dependency_output in dependency_outputs
        ):
            raise BundleError(
                "dependency copy source is outside declared dependency output: "
                + selected.as_posix()
            )
        selected_roots[output] = selected

    target_bundle.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target_bundle.name}.copy.",
        dir=target_bundle.parent,
    ) as temp_name:
        temp_root = Path(temp_name)

        try:
            with tarfile.open(source_bundle, "r") as archive:
                for member in archive.getmembers():
                    if member.name == BUNDLE_MANIFEST:
                        continue
                    member_path = PurePosixPath(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise BundleError(
                            f"bundle member escapes declared output: {member.name}"
                        )

                    destination_name: str | None = None
                    for output, selected in selected_roots.items():
                        if _path_is_within(member_path, selected):
                            relative = member_path.relative_to(selected)
                            destination = PurePosixPath(output)
                            if relative.parts:
                                destination /= relative
                            destination_name = destination.as_posix()
                            break
                    if destination_name is None:
                        continue

                    if member.issym() or member.islnk():
                        raise BundleError(
                            "dependency copy contains an unsupported link: "
                            + member.name
                        )
                    destination_path = temp_root / Path(destination_name)
                    if member.isdir():
                        destination_path.mkdir(parents=True, exist_ok=True)
                        destination_path.chmod(member.mode)
                    elif member.isfile():
                        destination_path.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise BundleError(
                                "dependency copy member is unreadable: "
                                + member.name
                            )
                        with destination_path.open("wb") as handle:
                            shutil.copyfileobj(extracted, handle)
                        destination_path.chmod(member.mode)
                    else:
                        raise BundleError(
                            "dependency copy contains unsupported entry: "
                            + member.name
                        )
        except tarfile.TarError as exc:
            raise BundleError(
                f"could not read dependency output bundle: {source_bundle}"
            ) from exc

        return write_bundle(
            target_bundle,
            temp_root,
            normalized,
        )
