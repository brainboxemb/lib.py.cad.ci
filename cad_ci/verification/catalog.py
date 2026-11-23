"""Verification adapter compatibility owned by CAD-CI wiring only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationAdapter:
    """Runtime compatibility metadata for one verification adapter."""

    name: str
    runtime_role: str


VERIFICATION_ADAPTERS: dict[str, VerificationAdapter] = {
    "mesh-geometry": VerificationAdapter(
        name="mesh-geometry",
        runtime_role="reference",
    ),
}
