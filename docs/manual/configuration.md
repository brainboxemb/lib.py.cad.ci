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

## Built-in build + verification profile

Reusable verification does not require a repository-owned `verify` command.

For a reference-model layout such as:

```text
models/
  example/
    build123d/
      ci.yml
      model.py
    verification/
      reference_geometry.json
```

start from `templates/cad-ci-verified-reference.yml`.

The root profile pins the released verification library independently from the
runtime image:

```yaml
verification:
  package:
    repository: brainboxemb/lib.py.cad.verification
    version: "0.16.0"
    commit: c7c145b7be0c602724e8cca874ef29990baaad1e
```

The item profile selects the generic builder and reusable verification adapter:

```yaml
templates:
  verified-reference:
    builder: build123d
    verification:
      adapter: mesh-geometry
      definition: ../verification/reference_geometry.json
```

An individual model can then contain only:

```yaml
id: example-build123d
template: verified-reference
```

A CadQuery model may use the same profile and override only
`builder: cadquery`.

CAD-CI materializes the pinned verification wheel once through the SCons graph,
mounts it read-only into the existing shared `reference` runtime and runs
geometry verification immediately after each model export. It does not install
the wheel in the host environment or start a second CAD container for
verification.

The verification definition remains consumer-owned data. Its fields and
semantics are owned by `lib.py.cad.verification`; do not reproduce them in
CAD-CI templates or repository scripts.

## Repository-owned builder using the verification package

A repository-owned builder that needs the exact released
`lib.py.cad.verification` wheel may request it declaratively:

```yaml
# ci/builders/solidcraft-model/builder.yml
schema: 1
verification_package: true

steps:
  - id: verify
    run: 'python "$CAD_CI_BUILDER_PATH/verify.py"'
    outputs: [verification]
```

Root `cad-ci.yml` must provide the normal exact package pin:

```yaml
verification:
  package:
    repository: brainboxemb/lib.py.cad.verification
    version: "0.16.0"
    commit: c7c145b7be0c602724e8cca874ef29990baaad1e
```

CAD-CI materializes that package once through the normal SCons graph and gives
each command step of the requesting item:

```text
CAD_CI_VERIFICATION_WHEEL=/absolute/target-private/path/...whl
```

The path is inside the command target's private dependency snapshot. Consumer
configuration must not name `cad-ci-verification-package`, inspect the
synthesized dependency layout or build/download a second copy of the wheel.

The builder remains responsible for its domain runtime. For example, it may
mount `CAD_CI_VERIFICATION_WHEEL` read-only into a SolidCraft container and
place that mounted wheel on `PYTHONPATH`.

This capability is unavailable to `publication.pages.builder` because the
Pages renderer runs after the SCons graph at the durable publication boundary.
