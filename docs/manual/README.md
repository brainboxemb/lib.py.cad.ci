# lib.py.cad.ci consumer manual

This manual describes the configuration owned by the reusable CAD-CI library.

Use it for:

- root `cad-ci.yml`;
- item-local `ci.yml`;
- built-in `build123d` and `cadquery` builder selection;
- repository-owned builder aliases and `builder.yml`.

GitHub Actions workflow wrappers do **not** live here. Copy those from the
released `tool.cad.ci/docs/manual/templates/` directory so workflow and library
ownership stay separate.

## Copy-ready templates

| File | Purpose |
| --- | --- |
| `templates/cad-ci.yml` | Root repository configuration. |
| `templates/model-build123d-ci.yml` | Item using the built-in build123d builder. |
| `templates/model-cadquery-ci.yml` | Item using the built-in CadQuery builder. |
| `templates/model-repository-builder-ci.yml` | Item using a repository-owned builder alias. |
| `templates/builder.yml` | Repository-owned builder implementation contract. |

See [configuration.md](configuration.md) for ownership and performance rules.

## Ownership rule

Model configuration says **what model uses which builder**. It must not repeat
generic builder execution, batch collection, runtime startup or projection
plumbing.

Built-in builder execution belongs to this library. Repository-owned builder
execution belongs to the repository's configured builder directory.
