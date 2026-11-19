"""Public execution API for the generic CAD CI library.

This module is intentionally thin. It resolves the public run selectors and
hands one complete target request to the SCons engine. SCons owns dependency
ordering, signatures, incremental decisions and cache reuse.
"""

from __future__ import annotations

from pathlib import Path

from .model import Item
from .scons_engine import (
    RunRequest,
    SConsRunError,
    resolve_request,
    run_scons,
)


class RunError(RuntimeError):
    """Public execution failure with the structured SCons report when available."""

    def __init__(self, message: str, *, report: dict | None = None):
        super().__init__(message)
        self.report = report


def run_repository(
    repo: Path,
    items: dict[str, Item],
    selected: set[str],
    *,
    item_id: str | None = None,
    step: str | None = None,
    start: str | None = None,
    until: str | None = None,
) -> dict:
    """Execute one repository selection through a single SCons invocation.

    `selected` is the coarse top-level item set from Git selection or an
    explicit command. Dependencies are not manually expanded/executed here;
    SCons traverses the configured target graph.

    Partial selectors have the semantics defined by the public contract:
    `--step` forces one exact step, `--until` requests one step normally, and
    `--from` forces the named step plus every following step.
    """

    try:
        request: RunRequest = resolve_request(
            items,
            selected,
            item_id=item_id,
            step=step,
            start=start,
            until=until,
        )
        return run_scons(repo, items, request)
    except SConsRunError as exc:
        raise RunError(str(exc), report=exc.report) from exc
