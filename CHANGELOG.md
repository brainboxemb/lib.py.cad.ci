# Changelog

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
