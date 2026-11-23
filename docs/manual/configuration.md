# Configuration manual

## Repository layout

A normal consumer can use this shape:

```text
cad-ci.yml
models/
  example-build123d/
    ci.yml
    model.py
  example-cadquery/
    ci.yml
    model.py
ci/
  builders/
    repository-model/
      builder.yml
      build.py
```

The root file discovers items and defines repository-wide defaults, runtime-role
images and optional repository-owned builder aliases.

## Root `cad-ci.yml`

Start from `templates/cad-ci.yml`.

Built-in builders use library-owned names and therefore do not appear under
`builders:`. The root `runtimes:` mapping provides the explicit image for the
runtime role they require.

Repository-owned aliases map a name to a source directory:

```yaml
builders:
  repository-model: ci/builders/repository-model
```

Built-in names such as `build123d` and `cadquery` are reserved and cannot be
shadowed by repository aliases.

## Built-in model items

A build123d item needs only its identity, builder choice and normal item-owned
selection data:

```yaml
id: example-build123d
builder: build123d

watch:
  item:
    - model.py
```

The item-local `model.py` exposes final geometry as global `model`.

CadQuery uses the same model/configuration boundary:

```yaml
id: example-cadquery
builder: cadquery
```

The initial canonical built-in output is `model.stl`.

Do not add shared producer IDs, Docker commands, batch commands, runtime-start
steps or dependency-copy projection to these item files. Those are generic
builder mechanics.

## Runtime and performance contract

Compatible active built-in models are collected into one shared runtime batch.
Initially build123d and CadQuery share the `reference` runtime role.

The performance contract is structural:

- compatible N-model work stays one shared runtime/container invocation;
- SCons remains the only dependency/freshness/cache engine;
- current/cache-restored work must not introduce an avoidable CAD runtime start;
- configuration lowering must not create a second planner or execution engine.

The normal library tests prove graph/call-count behavior cheaply. Real
container/engine acceptance belongs to the released-stack acceptance layer.

## Repository-owned builders

A repository-owned builder is declared once in root `cad-ci.yml` and selected
by items by name.

The item stays declarative:

```yaml
id: example-repository-model
builder: repository-model
```

The executable implementation is separate under the configured builder path.
Start from `templates/builder.yml`.

When generic behavior is missing, change the owning library/tool instead of
copying generic execution mechanics into every consumer.

## Workflow configuration

This library does not own GitHub Actions wrapper templates.

Use the templates shipped by the exact released `tool.cad.ci` version for
workflow setup. This prevents library configuration and workflow orchestration
from becoming duplicated sources of truth.
