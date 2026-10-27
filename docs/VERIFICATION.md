# Verification workflow

Milestone 2 has two verification layers. The default checks use synthetic data
and do not need an AW2 ROM or an mGBA process. Emulator integration checks are
opt-in and require a local ROM plus the pinned, frame-gated mGBA frontends.

## Default checks

From the repository root, enter the development environment and run:

```sh
nix develop
pytest
pre-commit run --all-files
```

The default pytest run covers ROM profiles, memory dump/diff/watch behavior,
state validation and decoding, lifecycle/UI classification, unit identity, and
bridge/launcher behavior using synthetic memory and mocked processes. The
frame-gate integration module is skipped unless `AW2_RUN_EMULATOR_TESTS=1` is
set. `pre-commit` also runs Ruff, Luacheck, Lua syntax and bridge checks, mypy,
and pytest. `nix build` builds the package and runs its package checks.

## Optional emulator integration checks

Use an unmodified US retail revision 0 ROM whose SHA-256 is
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`. Keep the
ROM and any save files outside the repository and Nix store. Build the pinned
frontends, then point the opt-in test at the local ROM:

```sh
nix build .#mgba
nix develop
AW2_RUN_EMULATOR_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  pytest tests/test_frame_gate_integration.py -v
```

Stop any AW2 Lab emulator already using bridge port 43128 before running the
checks. They launch both headless and windowed frontends, use temporary mGBA
configuration, save, and checkpoint directories, and verify bridge startup,
idle frame stability, coherent reads, screenshots, exact frame budgets,
input release, save/restore, reset, and shutdown. Windowed coverage requires a
display; when X11 and `xdotool` are available it also checks that resume and
frame-step shortcuts leave the game paused. To select different frontend
executables, set `AW2_TEST_MGBA_HEADLESS` or `AW2_TEST_MGBA_WINDOWED` to their
paths. Integration checkpoints are generated under pytest's temporary
directory and are removed with it.

The application can also be started against the same local ROM for manual
research. See the [research session setup](MILESTONE-2.org#prerequisites-and-research-workflow)
and [research tool instructions](AW2-RESEARCH-NOTES.org). Restore save states
through the emulator or the documented bridge workflow; record the source
checkpoint hash, ROM/build identity, frame, inputs, and observations. Keep ROMs,
save states, screenshots, and RAM dumps outside Git. The
[snapshot evidence index](AW2-SNAPSHOT-EVIDENCE.org) documents reproduction of
the currently archived movement, combat, purchase, capture, and turn-change
comparisons. Some historical checkpoint files and comparison scripts live in
external research directories and must be recovered or recreated to repeat
those exact scenarios.

## Verified scope and limits

The supported decoder profile is limited to the checksum-verified US revision
0 ROM above. The emulator source is pinned to mGBA commit
`fd9dc5c2cbf234365068855851107e762fc6211b`; the launcher uses the repository's
frame-gate patch. Findings from other ROM revisions, unpinned emulator builds,
or modified images are outside the verified scope.

The typed decoder publishes researched battle fields only after the live battle
and structure checks pass. Cursor, menu, lifecycle, and validation observations
retain their own availability and limits. Runtime comparisons document
startup, menus, battle entry,
playable and resumed Versus turns, combat, regular and Super CO Powers, results,
and headless/windowed parity for the recorded inputs. See
[state validation](AW2-STATE-VALIDATION.org),
[lifecycle research](AW2-LIFECYCLE-RESEARCH.org),
[lifecycle coverage](AW2-LIFECYCLE-COVERAGE.org), and the
[snapshot evidence index](AW2-SNAPSHOT-EVIDENCE.org) for evidence and
checkpoint details.

Campaign event/dialogue flows and unknown UI/process contexts remain
unclassified. The documented research also leaves theoretical map/property
capacity, some property and unit flag bits, certain capture-field bits, and
other explicitly listed fields unresolved or deferred. The opt-in automated
emulator test is a bridge/frame-gate check; it does not automatically reproduce
the game-specific lifecycle and parity comparisons, whose evidence is recorded
separately.
