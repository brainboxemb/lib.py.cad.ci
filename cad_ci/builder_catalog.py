"""Built-in generic CAD builder catalog.

Built-in model items are lowered to the same shared-producer plus
copy-from-dependency graph already used by consumers such as Forge. This module
contains only builder/runtime metadata and normal Step construction; it is not
a second scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import DependencyCopy, Step


@dataclass(frozen=True)
class BuiltinBuilder:
    """One reusable generic CAD engine builder."""

    name: str
    runtime_role: str
    contract: int
    output: str = "model.stl"


BUILTIN_BUILDERS: dict[str, BuiltinBuilder] = {
    "build123d": BuiltinBuilder(
        name="build123d",
        runtime_role="reference",
        contract=1,
    ),
    "cadquery": BuiltinBuilder(
        name="cadquery",
        runtime_role="reference",
        contract=1,
    ),
}

RUNTIME_BATCH_CONTRACTS = {
    "reference": 1,
}


def runtime_batch_id(role: str) -> str:
    """Return the stable internal item id for one shared runtime batch."""

    return f"cad-ci-runtime-{role}"


def runtime_batch_path(role: str) -> Path:
    """Return the private logical item path used for batch output/evidence."""

    return Path(".cad-ci-runtime") / role


def runtime_catalog_signature(role: str) -> str:
    """Return stable engine-contract identity for one compatible runtime group."""

    rows = sorted(
        (
            builder.name,
            builder.contract,
            builder.output,
        )
        for builder in BUILTIN_BUILDERS.values()
        if builder.runtime_role == role
    )
    if not rows:
        raise ValueError(f"unknown built-in runtime role: {role}")
    return ",".join(
        f"{name}:{contract}:{output}"
        for name, contract, output in rows
    )


def runtime_batch_step(
    role: str,
    *,
    inputs: tuple[str, ...],
    timeout_seconds: int | None,
) -> Step:
    """Return the normal command step for one shared built-in runtime batch."""

    try:
        contract = RUNTIME_BATCH_CONTRACTS[role]
    except KeyError as exc:
        raise ValueError(f"unknown built-in runtime role: {role}") from exc
    catalog_signature = runtime_catalog_signature(role)
    return Step(
        id="build",
        run=(
            "python",
            "-m",
            "cad_ci.cad_builder",
            "batch",
            "--runtime",
            role,
            "--contract",
            str(contract),
            "--catalog",
            catalog_signature,
        ),
        outputs=("items", "batch-manifest.json", "batch-report.json"),
        timeout_seconds=timeout_seconds,
        inputs=inputs,
        selection_context="direct_dependents",
    )


def projection_step(
    builder_name: str,
    *,
    dependency: str,
    item_path: Path,
) -> Step:
    """Return the normal copy step projecting one model from its shared batch."""

    builder = BUILTIN_BUILDERS[builder_name]
    return Step(
        id="build",
        copy=DependencyCopy(
            dependency=dependency,
            source=f"items/{item_path.as_posix()}",
        ),
        outputs=(builder.output,),
        inputs=(),
    )
