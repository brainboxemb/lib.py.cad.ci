# Test architecture

The test suite is executable documentation for the public CAD-CI contracts.
A future maintainer should be able to understand **why a test exists** without
reverse-engineering every assertion.

## Test layers

### Unit tests

Unit tests isolate one owner module or small collaboration. External tools are
replaced at an explicit adapter/process boundary.

Examples include configuration validation, builder catalog lookup/lowering,
manifest construction, path/output safety and runtime command construction.

A unit test should not start Docker, GitHub Actions or a real CAD engine merely
to prove Python decision logic.

### Conformance tests

Conformance tests prove documented library contracts across multiple owner
modules, especially configuration -> normalized Item/Step -> SCons target
specification.

When a test implements a case from `docs/scons-acceptance.md`, its docstring
names that case. Example:

```python
def test_active_models_feed_signature_safe_shared_batch_context(self):
    """Acceptance Case 32: active dependents define shared-batch identity."""
```

These tests may use the real SCons integration when SCons behaviour itself is
the contract under test.

### Repository integration tests

Repository integration tests run the installed/built package through realistic
repository fixtures and verify package/install boundaries. Real local tools are
used only when that boundary is what the test is proving.

### External black-box acceptance

Released-stack behaviour belongs in `tool.cad.ci.test`. It proves the exact
released `lib.py.cad.ci` + `tool.cad.ci` pair from outside the library.
Do not duplicate GitHub Actions/lane acceptance logic here.

## Documentation rule

Every non-trivial test method has a short docstring describing the contract it
protects. The method name says what scenario is exercised; the docstring says
why that scenario matters architecturally.

Comments explain intent that is not obvious from the code, such as why two
items deliberately share one runtime, why a fake process/engine is used, or
why call count/order is contract-significant.

Do not add comments such as "assert value is X" above obvious assertions. That
adds noise and becomes stale.

## Fixtures, fakes and mocks

Prefer stable fakes/adapters over patching implementation internals.

Fixture helpers need a docstring when their exact repository shape matters to
the contract. A fake should expose only the boundary the production code owns.

For external processes the preferred architecture is:

```text
owner logic -> runtime/tool adapter -> process adapter -> subprocess
```

Unit tests normally replace the process adapter, not `subprocess.run`
throughout owner modules.

## Development-cycle performance

Test cost is part of the system performance budget.

- prove a contract at the cheapest reliable layer;
- unit/structural tests are the default for owner logic and architecture
  invariants;
- use real SCons only when SCons behavior is the subject of the contract;
- do not start Docker or real CAD engines in the normal library suite for
  behavior that a fake adapter can prove;
- keep released-stack/container acceptance in `tool.cad.ci.test`;
- avoid duplicate assertions of the same contract across multiple expensive
  layers;
- prefer deterministic call-count/graph assertions over timing sleeps or
  wall-clock thresholds.

A new test must justify its maintenance/runtime cost by protecting a distinct
regression risk or public contract.

## Maintenance checklist

When changing behaviour:

1. update requirement/design/acceptance documentation first when observable
   behaviour changes;
2. update or add the smallest test at the correct layer;
3. update its docstring/comments so the architectural reason remains clear;
4. remove obsolete implementation-specific tests instead of preserving them;
5. keep released-stack acceptance in `tool.cad.ci.test`.
