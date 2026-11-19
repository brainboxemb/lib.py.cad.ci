"""Create and restore cacheable bundles for declared CI step outputs.

SCons caches ordinary files well but a CAD CI step may declare either files or
complete directories. Each step therefore has one deterministic tar bundle as
its SCons target. The user command writes its normal output below build/<item>;
the bundle captures that output for CacheDir, and a separate materializer
restores it when the bundle is current or cache-restored.

The bundle is execution evidence, not a second rebuild-decision engine. SCons
alone decides whether the bundle target needs to be rebuilt.
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


BUNDLE_MANIFEST = "__cad_ci_bundle__.json"
BUNDLE_SCHEMA = 1


class BundleError(RuntimeError):
    """Raised when declared output cannot be bundled or restored safely."""


def _sha256_file(path: Path) -> str:
    """Return a SHA-256 digest for one regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_digest(path: Path) -> str:
    """Hash directory structure and file contents in stable relative order."""

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


def _normalized_output(value: str) -> str:
    """Return one safe POSIX-style output path relative to an item build root."""

    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise BundleError(f"unsafe declared output: {value}")
    return path.as_posix()


def output_snapshot(output_root: Path, outputs: tuple[str, ...] | list[str]) -> dict[str, dict[str, Any]]:
    """Describe current declared output, raising when anything is missing."""

    result: dict[str, dict[str, Any]] = {}
    for raw in outputs:
        name = _normalized_output(str(raw))
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


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Normalize archive ownership/timestamps while preserving file modes."""

    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def write_bundle(bundle: Path, output_root: Path, outputs: tuple[str, ...] | list[str]) -> dict:
    """Write one deterministic tar bundle containing every declared output."""

    normalized = tuple(_normalized_output(str(value)) for value in outputs)
    snapshot = output_snapshot(output_root, normalized)
    manifest = {
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
                path = output_root / Path(name)
                # tarfile can store links. CI output may not escape its owned
                # tree, so reject them before adding the tree recursively.
                if path.is_symlink():
                    raise BundleError(f"declared output is a symlink: {path}")
                if path.is_dir():
                    for child in path.rglob("*"):
                        if child.is_symlink():
                            raise BundleError(
                                f"declared output contains a symlink: {child}"
                            )
                archive.add(
                    path,
                    arcname=name,
                    recursive=True,
                    filter=_tar_filter,
                )

            payload = (
                json.dumps(manifest, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            info = tarfile.TarInfo(BUNDLE_MANIFEST)
            info.size = len(payload)
            info.mode = 0o644
            info = _tar_filter(info)
            archive.addfile(info, io.BytesIO(payload))

        temp.replace(bundle)
    finally:
        temp.unlink(missing_ok=True)

    return manifest


def read_bundle_manifest(bundle: Path) -> dict:
    """Read and validate the metadata stored inside one CAD CI bundle."""

    try:
        with tarfile.open(bundle, "r") as archive:
            member = archive.getmember(BUNDLE_MANIFEST)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise BundleError(f"bundle has no readable manifest: {bundle}")
            data = json.loads(extracted.read().decode("utf-8"))
    except (FileNotFoundError, KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
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
    """Return whether current declared output exactly matches bundle metadata."""

    try:
        expected = read_bundle_manifest(bundle)["outputs"]
        normalized = tuple(_normalized_output(str(value)) for value in outputs)
        if set(expected) != set(normalized):
            return False
        return output_snapshot(output_root, normalized) == expected
    except BundleError:
        return False


def _remove_output(path: Path) -> None:
    """Remove one file/directory output before restoring it from a bundle."""

    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _member_is_allowed(name: str, outputs: tuple[str, ...]) -> bool:
    """Return whether one archive member belongs to a declared output path."""

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized = path.as_posix()
    return any(
        normalized == output or normalized.startswith(output.rstrip("/") + "/")
        for output in outputs
    )


def materialize_bundle(
    bundle: Path,
    output_root: Path,
    outputs: tuple[str, ...] | list[str],
) -> bool:
    """Restore declared output from a bundle when current output differs.

    Returns True when files/directories were restored and False when the
    existing output already matched the bundle.
    """

    normalized = tuple(_normalized_output(str(value)) for value in outputs)
    manifest = read_bundle_manifest(bundle)
    expected = manifest["outputs"]
    if set(expected) != set(normalized):
        raise BundleError("bundle outputs do not match configured outputs")

    if outputs_match_bundle(bundle, output_root, normalized):
        return False

    output_root.mkdir(parents=True, exist_ok=True)
    for name in normalized:
        _remove_output(output_root / Path(name))

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
            archive.extractall(output_root, members=members, filter="data")
    except tarfile.TarError as exc:
        raise BundleError(f"could not restore output bundle: {bundle}") from exc

    current = output_snapshot(output_root, normalized)
    if current != expected:
        raise BundleError("restored output does not match bundle metadata")
    return True


def bundle_sha256(bundle: Path) -> str:
    """Return the digest used as durable result evidence for one step bundle."""

    return _sha256_file(bundle)
