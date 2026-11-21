"""Build and install small static documentation/publication sites.

The framework owns page structure, navigation, stable/preview locations and
provenance. Consumers own their text, domain-specific HTML and stylesheet.
This lets Forge, CAD and tool.cad.ci share publication mechanics without being
forced into one visual design.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable


@dataclass(frozen=True)
class Page:
    """One generated HTML page relative to the site root."""

    path: str
    title: str
    body_html: str


class PagesError(RuntimeError):
    """Raised when a page path or publication target is unsafe."""


def _page_path(path: str) -> Path:
    """Validate that a generated page remains below the site root."""

    value = Path(path)
    if value.is_absolute() or ".." in value.parts:
        raise PagesError(f"unsafe page path: {path}")
    if value.suffix.lower() != ".html":
        raise PagesError(f"page path must end in .html: {path}")
    return value


def _safe_subtree_name(name: str) -> str:
    """Return one safe caller-owned top-level Pages subtree name."""

    if not isinstance(name, str) or not name.strip():
        raise PagesError("subtree name must be non-empty text")
    value = name.strip()
    path = Path(value)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or value in {".", "..", ".git", "previews"}
        or "/" in value
        or "\\" in value
    ):
        raise PagesError(f"unsafe Pages subtree name: {name}")
    return value


def render_page(
    *,
    site_title: str,
    page: Page,
    navigation: Iterable[Page],
    stylesheet: str | None,
    base_path: str,
) -> str:
    """Render the shared semantic HTML shell around consumer-provided body HTML."""

    prefix = "/" + base_path.strip("/") if base_path.strip("/") else ""
    nav = "\n".join(
        f'<a href="{escape(prefix)}/{escape(item.path)}">{escape(item.title)}</a>'
        for item in navigation
    )
    style = (
        f'<link rel="stylesheet" href="{escape(prefix)}/{escape(stylesheet)}">'
        if stylesheet
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page.title)} — {escape(site_title)}</title>
  {style}
</head>
<body>
  <header>
    <strong>{escape(site_title)}</strong>
    <nav>{nav}</nav>
  </header>
  <main>
    <h1>{escape(page.title)}</h1>
    {page.body_html}
  </main>
</body>
</html>
"""


def build_site(
    *,
    out: Path,
    site_title: str,
    pages: Iterable[Page],
    provenance: dict,
    stylesheet_source: Path | None = None,
    stylesheet_name: str = "site.css",
    base_path: str = "",
) -> None:
    """Build a complete static site in a clean output directory."""

    page_list = tuple(pages)
    if not page_list:
        raise PagesError("site requires at least one page")
    paths = [_page_path(page.path) for page in page_list]
    if len(paths) != len(set(paths)):
        raise PagesError("site contains duplicate page paths")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    stylesheet = None
    if stylesheet_source is not None:
        if not stylesheet_source.is_file():
            raise PagesError(f"stylesheet does not exist: {stylesheet_source}")
        stylesheet = stylesheet_name
        shutil.copy2(stylesheet_source, out / stylesheet_name)

    for page, rel in zip(page_list, paths):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_page(
                site_title=site_title,
                page=page,
                navigation=page_list,
                stylesheet=stylesheet,
                base_path=base_path,
            ),
            encoding="utf-8",
        )

    # Provenance is framework-owned because every consumer needs the same basic
    # answer to "which source/build produced the site I am looking at?".
    (out / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _replace_tree(source: Path, target: Path) -> None:
    """Replace one preview directory without exposing a partial copy."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    shutil.rmtree(temp)
    try:
        shutil.copytree(source, temp)
        if target.exists():
            shutil.rmtree(target)
        temp.rename(target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def install_preview(*, site: Path, pages_root: Path, pull_request: int) -> Path:
    """Replace only `previews/pr-N` and preserve stable Pages output."""

    if pull_request <= 0:
        raise PagesError("pull_request must be positive")
    if not (site / "provenance.json").is_file():
        raise PagesError("site has no provenance.json")
    target = pages_root / "previews" / f"pr-{pull_request}"
    _replace_tree(site, target)
    return target


def install_named(
    *,
    site: Path,
    pages_root: Path,
    name: str,
) -> Path:
    """Replace one safe named Pages subtree and preserve every sibling."""

    if not (site / "provenance.json").is_file():
        raise PagesError("site has no provenance.json")
    target = pages_root / _safe_subtree_name(name)
    _replace_tree(site, target)
    return target


def install_stable(
    *,
    site: Path,
    pages_root: Path,
    preserve_subtrees: Iterable[str] = (),
) -> None:
    """Replace stable Pages while preserving previews and named subtrees."""

    if not (site / "provenance.json").is_file():
        raise PagesError("site has no provenance.json")

    names = tuple(_safe_subtree_name(name) for name in preserve_subtrees)
    if len(names) != len(set(names)):
        raise PagesError("duplicate preserved Pages subtree")
    for name in names:
        if (site / name).exists():
            raise PagesError(
                f"stable site collides with preserved Pages subtree: {name}"
            )

    preserved = {".git", "previews", *names}
    for child in tuple(pages_root.iterdir()) if pages_root.exists() else ():
        if child.name in preserved:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    pages_root.mkdir(parents=True, exist_ok=True)
    for child in site.iterdir():
        target = pages_root / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)

def remove_preview(*, pages_root: Path, pull_request: int) -> bool:
    """Remove one PR preview without changing the stable site or other previews."""

    if pull_request <= 0:
        raise PagesError("pull_request must be positive")
    target = pages_root / "previews" / f"pr-{pull_request}"
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
