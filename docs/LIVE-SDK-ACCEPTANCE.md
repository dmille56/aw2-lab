# Live SDK and emulator acceptance

The opt-in checks in [test_sdk_live_integration.py](../tests/test_sdk_live_integration.py)
exercise the fixed Bean Island profile with Andy/Red and Max/Blue under external
control, fog disabled, Clear weather, and the verified rules. The main scenario
starts actual CLI server processes, connects separate operator/Red/Blue SDK
clients over loopback TCP, and uses real SSE for command completion and turn
wakeups. The CLI's normal authorization, storage, emulator isolation, and MCP
scaffold lifetimes run normally; MCP gameplay is outside this verification.

## Reproduction

Provide the supported local ROM and a working display for windowed runs. Close
other bridge emulators first because the bridge uses loopback port 43128. Each
check generates private credentials and isolated storage under pytest's external
temporary directory. Existing cartridge saves are copied into the runtime's
isolated directory. No ROM, save, screenshot, credential, or checkpoint is added
to Git or the Nix store. Keep the chosen evidence directory after the check.

```sh
AW2_RUN_SDK_LIVE_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  nix develop -c pytest -s tests/test_sdk_live_integration.py \
  -k two_sdk --basetemp=/tmp/aw2-sdk-live
```

This runs headless then windowed. `-k 'two_sdk and headless'` or
`-k 'two_sdk and windowed'` selects one. The server is restarted mid-scenario
with the same storage/operator file and new listening socket. The test reuses
player credentials and retries an old completed purchase to check durable
receipt identity after restart.

The deterministic input-only scenario buys an Infantry and Tank for Red and a
Tank for Blue, moves both armies, partially and fully captures the neutral city
at (5,4), and moves Red's Tank before attacking Blue's at (8,5). It checkpoints
that midgame, finishes through surrender, restores the checkpoint, restarts the
server, and continues the Infantry to Blue's HQ at (14,7) for partial capture
and natural victory. Stale, wrong-turn, duplicate, and illegal-route requests
are sent through the same public SDK boundary. Reads and saved snapshots record
revisions, frame, unit identities, health, fuel, ammo, turn use, property ownership,
and capture progress. A boundary screenshot is fetched after victory.

## Recovery with controlled failure injection

```sh
AW2_RUN_SDK_LIVE_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  nix develop -c pytest -s tests/test_sdk_live_integration.py \
  -k live_input_timeout --basetemp=/tmp/aw2-sdk-live-recovery
```

This separate check hosts the real app on a loopback listener and injects a
`TimeoutError` immediately after a real `press_keys` operation has completed.
It verifies actual emulator/checkpoint rollback and restored observations and
identities at a fresh revision. A second action additionally injects rollback
provider failure, requires explicit operator checkpoint restoration, then makes
a successful gameplay purchase. Only the independent MCP scaffold lifecycle is
substituted in this diagnostic composition. This is fault injection backed by
a live emulator, not evidence that an unmodified emulator naturally timed out.
ROM-independent tests cover arbitrary unresolved menus and watchdog expiry.

## Shared-checkpoint frontend parity

Use `initial.state` from the headless main run as the identical native source
for both isolated frontends:

```sh
AW2_RUN_SDK_LIVE_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  AW2_SDK_PARITY_STATE_PATH=/external/evidence/headless/initial.state \
  nix develop -c pytest -s tests/test_sdk_live_integration.py \
  -k identical_native --basetemp=/tmp/aw2-sdk-live-parity
```

The parity check directly tests emulator bridge primitives in isolated processes.
Both frontends load exactly the same native state, then receive Right 1,
neutral 30, Left 1, neutral 30. Complete decoded observations before and after
must match, including frame. Public checkpoint import/restore still enforces
frontend/build compatibility; this native parity diagnostic does not rewrite
manifest identities or advertise cross-frontend public checkpoint portability.

## Cartridge save RAM

The existing full-state integration check can verify actual in-game save-data
changes and restoration in both frontends, using a matching local state/save:

```sh
AW2_RUN_EMULATOR_TESTS=1 AW2_ROM_PATH=/absolute/path/to/aw2.gba \
  AW2_TEST_SAVE_STATE_PATH=/external/evidence/headless/initial.state \
  AW2_TEST_SAVE_PATH=/absolute/path/to/aw2.sav \
  nix develop -c pytest -s tests/test_frame_gate_integration.py \
  -k checkpoint_restores_in_game_save_data --basetemp=/tmp/aw2-sdk-live-saveram
```

This test changes cartridge save data through the game's Save menu, checks the
savedata payload embedded in a new mGBA state, restores a checkpoint, and checks
that the embedded payload returns to its original bytes. It exercises both
file and in-memory full-state checkpoint operations in each frontend. The
external `.sav` is an isolated startup copy; after loading a native checkpoint,
its embedded save data is authoritative, so comparing the backing file directly
does not establish whether checkpoint restore preserved save RAM.

## Evidence format and limits

Each main run writes an `evidence.json` index, selected full state snapshots,
`initial.state`, an operator checkpoint archive, a victory PNG, and a local
server log. The index records ROM/build identities, native-state and image
fingerprints, command outcomes, boundary revisions/frames, and completion.
Recovery and parity checks write their own evidence indexes. Credentials and
authorization verifiers remain only in private external run storage; the tracked
results summarize safe observations and artifact hashes.

A live acceptance pass verifies these scenarios on the pinned frontends and
supported ROM/profile. It does not broaden supported maps, CO/rule combinations,
unit production menus, fog, gameplay actions, or MCP support.

## Current results (2026-11-03)

The live playable-slice acceptance passed in both headless and windowed modes
through actual CLI/TCP/SSE servers:

- Fixed-profile cold boot, separate player claims, purchases by both armies,
  illegal/stale/wrong-turn rejection, duplicate receipt identity, and a bounded
  client wait that left its accepted purchase running.
- Move/wait, partial neutral-city capture at 10 points, ownership change on
  completing capture, and move/attack with damage/ammo/turn-use postconditions.
- Checkpoint creation, archive export/import, surrender to a finished boundary,
  restore, actual server shutdown/restart, preserved unit identities and state,
  fresh revisions, and an old purchase retry returning its original command.

Both runs passed the formerly failing Infantry route from (5,4) through
(6,4), (7,4), (8,4), which presents a three-row Fire/Capture/Wait selector.
They continued through HQ capture and natural victory. Controlled timeout and
failed-rollback recovery, debug-route authorization/recovery, and shared-native
checkpoint parity passed. Cartridge save-RAM checkpoint restoration passed
both storage forms in both frontends. The test verifies the save-data payload
inside the mGBA state before the in-game Save, after it, and after restoring the
checkpoint. The original source `.sav` remained unchanged.

Live failure diagnoses and corrections:

1. Consecutive route directions could be sent while the movement overlay was
   still rearming input. The same Tank route failed with a two-frame release
   and passed with eight; route steps now use at least eight neutral frames.
   A regression check models input rearming across consecutive route steps.
2. Fire targeting put its initialized cursor process in UI slot 1 while slot 0
   was empty. Recognition now finds exactly one initialized cursor among the
   three known slots while retaining Fire-parent/controller guards. The exact
   Tank attack checkpoint completed with normal runtime timing after the fix.
   Synthetic checks cover all slots, initialization, and ambiguous cursors.

3. The HQ approach destination at (8,4) offered Fire/Capture/Wait because an
   enemy was adjacent and the neutral city could be captured. Its selector had
   row IDs `(0, 2, 0x0A)`, count 3, selected row 0, object `0x0848A42C`, table
   `0x0849AE28`, controller state 13/lock 1/input state 4, and the verified unit
   action parent process. The decoder previously accepted at most two rows.
   It now admits this exact three-row signature for a capture-eligible unit.
   Wait/Fire/Capture navigation now checks each intermediate row instead of
   waiting for the final destination after the first button. Regression tests
   cover all three actions and selector slots. The complete headless/windowed
   replays on 2026-11-03 passed this route and continued through HQ victory.

The final available focused checks passed: 228 decoding/navigation/combat tests,
Ruff lint/format checks, and mypy. On 2026-11-03 the full two-mode playable
scenario, timeout recovery, debug-route recovery, shared-state parity, and all
four save-RAM checkpoint round trips passed. The first save-RAM assertion
incorrectly compared the runtime `.sav` file with the payload in a loaded
native state; these can differ because the checkpoint carries its own save
data. Replacing that assertion with a comparison of the mGBA `gbAx` savedata
payload confirmed the game Save changes the payload and checkpoint restore
returns it to the original bytes in both frontends and checkpoint formats.
The final `nix develop -c pre-commit run --all-files` passed after the test
correction.

External evidence root: `aw2-sdk-acceptance-complete`, with directories
`test_two_sdk_clients_play_save0` (headless) and
`test_two_sdk_clients_play_save1` (windowed). The files include private runtime
storage; share only selected safe observations or the hashes below.

Supported ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Frontend build identities:

- Headless: `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`
- Windowed: `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`

| Artifact | Headless SHA-256 | Windowed SHA-256 |
| --- | --- | --- |
| `initial.state` | `f0c142cee0d0a075d9b7ef4b5516810d8a94169419f959926d3a387c80361fbe` | `78bf25c496636814224c03f4eeca6b3c2a33df2da6231e841e05a689a46766eb` |
| `midgame.zip` | `ab66e8cc20d0dce360ee0bc4229cf16aeac42e2fd0b7229970bcdfc207c4e3a8` | `0cc7329e1b16622c2f8968226ffec2aebda199d8a316b7f54b82520ad9c83786` |
| `evidence.json` | `2a257e246648d1914c6360a91514e87b05e941c9222d2eb44f6cb5daf901532b` | `2d9e873a438e88f94ab9c564601f4b1c0a87ec3f2e470bd24321386764ce2c2f` |

Both runs reached midgame at revision 18, finished through surrender at 19,
restored at 20, and restarted at 21. Emulator frames were 7208 for the
headless midgame/restore/resume and 6640 for windowed. Public state equality
and lifetime identities were checked within each restore/restart sequence;
these independent cold boots do not establish identical native-state parity.
