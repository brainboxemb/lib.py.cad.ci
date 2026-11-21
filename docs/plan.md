# Repository plan

This file is the current work source of truth for `lib.py.cad.ci`.

Requirements and permanent product behavior live in the normal documentation;
issues contain detail and history.

## Current released state

`lib.py.cad.ci 0.9.3` is released at exact commit
`74486c441f1f2b170ff3dc06e0edcaf662fbec6b`.

The release is consumed by:
- `tool.cad.ci 0.16.2` @
  `59e4c4d3f377f906b33bb2d1fee808f96c6fb1b9`;
- external `tool.cad.ci.test` #62 / PR #63, which passed the complete
  released-stack suite.

The external selective-startup case proved the 0.9.3 behavior through the public
tool surface: a selected item remained runnable with an unrelated configured
symlink, while explicitly selecting the symlink-owning item still failed safely.
The same case observed a 0.446 s selected released-stack run; that value is
diagnostic evidence, not a contractual threshold.

## Current work

No generic library implementation is active.

Closed #71 delivered the selective-startup optimization:
- requested SCons target closure is resolved before source-input preparation;
- one repository source inventory is shared across active steps;
- inactive targets no longer contribute source-resolution work;
- active target signatures and SCons ownership remain unchanged.

New generic CAD-CI work must start from a new issue, update this plan before
implementation, and follow the owner-first release/acceptance chain.

## Next demand-driven priorities

There is no queued library change required for Forge at this point.

If future consumer evidence exposes a generic defect or performance bottleneck:
1. classify it in this repository first;
2. update requirements/design/acceptance before SCons-engine code;
3. implement and release the library;
4. repin the thin tool;
5. prove the exact released stack externally;
6. only then update consumers.

Bounded parallel execution is already library-owned and released. Exposing its
`jobs` input through the thin tool remains tool.cad.ci #76, not library work.
