"""In-runtime bridge from CAD-CI wiring to released cad_verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_verification(
    *,
    adapter: str,
    model_output: Path,
    definition: Path,
    output_dir: Path,
    verification_id: str,
) -> dict[str, Any]:
    """Delegate one normalized CAD-CI verification request to the library."""

    if adapter != "mesh-geometry":
        raise RuntimeError(f"unsupported CAD-CI verification adapter: {adapter}")

    from cad_verification import (
        load_geometry_contract,
        run_mesh_geometry_verification,
    )

    contract = load_geometry_contract(definition)
    return run_mesh_geometry_verification(
        model_output,
        output_dir,
        contract,
        verification_id=verification_id,
    )
