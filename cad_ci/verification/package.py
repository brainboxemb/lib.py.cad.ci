"""Materialize one exact released cad_verification wheel for SCons consumers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

from ..execution.process import (
    DEFAULT_PROCESS_RUNNER,
    ProcessExecutionError,
    ProcessRunner,
)
from ..model import Step, VerificationPackage


PACKAGE_ITEM_ID = "cad-ci-verification-package"
PACKAGE_ITEM_PATH = Path(".cad-ci-verification") / "package"
_WHEEL_PREFIX = "brainboxemb_cad_verification_lib-"


class VerificationPackageError(RuntimeError):
    """Raised when the exact verification package cannot be materialized."""


def package_step(
    package: VerificationPackage,
    *,
    timeout_seconds: int | None,
) -> Step:
    """Return the SCons-owned command step for the exact verification package."""

    return Step(
        id="package",
        run=(
            "python",
            "-m",
            "cad_ci.verification.package",
            "build",
            "--repository",
            package.repository,
            "--version",
            package.version,
            "--commit",
            package.commit,
        ),
        outputs=("dist", "provenance.json"),
        timeout_seconds=timeout_seconds,
        inputs=(),
    )


def _output_root(environ: dict[str, str] | os._Environ[str]) -> Path:
    value = environ.get("CAD_CI_OUTPUT", "").strip()
    if not value:
        raise VerificationPackageError("CAD_CI_OUTPUT is required")
    output = Path(value).resolve()
    output.mkdir(parents=True, exist_ok=True)
    return output


def materialized_wheel(dist: Path) -> Path:
    """Return the one exact verification wheel in a materialized dist output."""

    wheels = tuple(sorted(Path(dist).glob(f"{_WHEEL_PREFIX}*.whl")))
    if len(wheels) != 1:
        raise VerificationPackageError(
            f"expected one CAD verification wheel, found {len(wheels)}"
        )
    return wheels[0]


def _wheel_version(path: Path) -> str:
    """Read the canonical Version field from one built wheel."""

    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(candidates) != 1:
                raise VerificationPackageError(
                    "verification wheel must contain exactly one METADATA file"
                )
            metadata = archive.read(candidates[0]).decode("utf-8")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise VerificationPackageError(
            f"could not inspect verification wheel: {path}: {exc}"
        ) from exc

    for line in metadata.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise VerificationPackageError("verification wheel METADATA has no Version")


def build_package(
    package: VerificationPackage,
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    process: ProcessRunner | None = None,
) -> Path:
    """Build, validate and record one exact verification wheel."""

    env = os.environ if environ is None else environ
    runner = DEFAULT_PROCESS_RUNNER if process is None else process
    output = _output_root(env)
    dist = output / "dist"
    dist.mkdir(parents=True, exist_ok=True)

    for old in dist.glob(f"{_WHEEL_PREFIX}*.whl"):
        old.unlink()

    source_url = (
        f"https://github.com/{package.repository}/archive/{package.commit}.zip"
    )
    runner.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(dist),
            source_url,
        ],
        cwd=output,
        check=True,
    )

    wheel = materialized_wheel(dist)
    actual = _wheel_version(wheel)
    if actual != package.version:
        raise VerificationPackageError(
            "CAD verification wheel version mismatch: "
            f"expected {package.version}, got {actual}"
        )

    provenance = {
        "schema": 1,
        "repository": package.repository,
        "version": package.version,
        "commit": package.commit,
        "source_url": source_url,
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    (output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return wheel


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by the synthesized verification-package item."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repository", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--commit", required=True)
    args = parser.parse_args(argv)

    try:
        package = VerificationPackage(
            repository=args.repository,
            version=args.version,
            commit=args.commit,
        )
        build_package(package)
    except (VerificationPackageError, ProcessExecutionError) as exc:
        print(f"CAD CI verification package error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
