# Changelog

## 0.6.0

- add optional item-level `process` selection, defaulting to `true`;
- exclude `process: false` items from changed-path selection, dependency fan-out, full runs and SCons target generation;
- reject explicit execution of non-processed items and processed dependencies on non-processed items;
- preserve existing SCons rebuild/cache semantics for processed items.

## 0.5.0

- add validated repository-wide `variables` in root `cad-ci.yml`;
- inject those values into every consumer command while protecting CAD-CI-owned environment names;
- include repository variables in each SCons target signature so value changes rebuild affected targets.


## 0.4.0

- rename public SCons output evidence from `materialization` to `output_state`;
- rename public restore failure status from `materialization_error` to `output_restore_error`;
- print literal `output=unchanged|restored|repaired` target results instead of `materialization=...`;
- bump the private run-report schema version to 2 and public step-evidence schema to 2;
- keep bundle restoration terminology internal to the implementation.


## 0.3.0

- replace the custom fingerprint/reuse runner with SCons 4.11.1 as the single execution and incremental-build engine;
- add step-level input patterns while keeping item watch paths for coarse Git selection;
- add deterministic cumulative step bundles for file and complete-directory output, CacheDir restore and output repair;
- define exact partial-run semantics for step, until and from execution;
- expose bundle-backed dependency context and structured BUILT/CACHE_RESTORED/CURRENT/ERROR evidence;
- publish complete item evidence under .cad-ci and validate durable main/PR build scopes against current item configuration;
- remove the obsolete custom state/fingerprint engine.


## 0.2.0

- add repository-default and per-step execution timeouts;
- record timeout failures distinctly from command exit failures;
- include effective timeout configuration in reuse fingerprints;
- define the complete generic CI contract and the permanent `tool.cad.ci.test` acceptance repository.

## 0.1.3

- add authenticated read-only materialization of generated remote branches.

## 0.1.2

- expose the current item output directory through ItemContext.output.

## 0.1.1

- add validated runtime dependency context for consumer aggregate steps;
- expose current item-result validation as public library API.

## 0.1.0

- Initial extraction of reusable CAD CI Python mechanics.
- Add direct-only affected-item selection for fan-in summary items.
