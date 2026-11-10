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

## Milestone 5 stationary attack action (2026-11-09)

The distinct pathless `attack` action passed live headless execution against
both a direct-fire unit and indirect Rockets, using the production executor and
real mGBA bridge. The direct Tank attack at revision 1 returned a verified
playable boundary at revision 2 (frames 19421–19979); target health changed
from 44 to destroyed. On the Rockets checkpoint, the indirect unit attacked
without movement and returned to the playable turn (frames 129662–129794);
ammo changed from 6 to 5 and the target was destroyed. Both cases verified the
acting unit's post-attack turn state. The direct run used checkpoint SHA-256
`e34dddc4216fef3a84390796a0b188f76ff51f123983f0dc4da423fe970b36d0`; the
indirect run used `ca10e6e6b5293a7986f9fceb9e8925c3288d45cca93fbefc3c1155c5d57e3539`.
The ROM SHA-256 and headless build identity matched the recorded acceptance
environment above. Windowed verification passed on 2026-11-09 using the same
direct Tank case and checkpoint. The pathless `attack` command completed from
frame 19421 to 19991 on windowed build
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`;
Tank reference 3 retained 98 health and 60 fuel, target reference 130 went
from 44 health to destroyed, and the match returned to a ready playable turn.
The ROM SHA-256 is
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`, and the
checkpoint SHA-256 is
`e34dddc4216fef3a84390796a0b188f76ff51f123983f0dc4da423fe970b36d0`.
Evidence and screenshot are outside Git at
`/tmp/aw2-attack-windowed-stationary/`; evidence JSON SHA-256
`69e3378a55674b8924eedd594030e2b0041a3459148ac697cafb663367002912`, screenshot
SHA-256 `27fd23ce77ed4aba840115b6863be5c7cd1a43992fb1831fd0c25fff68466a14`.
This closes live frontend verification of the stationary `attack` action in
both headless and windowed mGBA.

## Milestone 5 normal CO Power action (2026-11-09)

The production `ActivateNormalPowerActionExecutor` completed against the
supplied normal-Power checkpoint in both headless and windowed mGBA. The source
checkpoint was on the COMMAND menu with Power selected at frame 13242. Pressing
B returned it to a ready map-input boundary at frame 13247; the executor then
opened the menu, selected Power, and waited for the settled player-turn
boundary. Both runs returned playable at frame 13779, revision 1 to 2, with
map input available. Andy (CO ID 1) changed from inactive Power to active
Power; meter changed from 54,000 to 21,600 (32,400 spent), and the use counter
changed from 0 to 1. The effect state was recognized after the animation and
before any further player action.

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Source checkpoint `aw2.ss3` SHA-256:
`558078226bc01a35832d61a0d54a4cdb3165628d512af665711272ccdf63ce1d`.
Frontend build identities:

- Headless: `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`
- Windowed: `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`

| Evidence | Headless SHA-256 | Windowed SHA-256 |
| --- | --- | --- |
| Executor-ready derived state | `667312f191b5d6d6aa348cdc97105592f5e7c2de3cb09581e3db3ac089d02a4e` | `1a46a5ba5fb255807d92d2a80ec29b68af456385a40d8bc5d26b6ebee339d6bd` |
| Settled state | `f81230ec7530b55fd9d8d78d617b1412d2c6ef94469a25fd66f8d77a26fdd691` | `4790a1f16f32d7923b48213f6e7f6070c302238a893ae1a98069ddeae325e360` |
| Before screenshot | `4f8b3488c31be0e2ac98abd45565ba1c9d4ad7e99bf4fe6285ff4014f3675efc` | `4f8b3488c31be0e2ac98abd45565ba1c9d4ad7e99bf4fe6285ff4014f3675efc` |
| After screenshot | `04db1e4e811f9485087e1c6c291fec5d2b101171fb99418f816b7d73dbeb87ad` | `04db1e4e811f9485087e1c6c291fec5d2b101171fb99418f816b7d73dbeb87ad` |
| Evidence JSON | `d14a4537f862b478b139f0eb0e82565c3236e8c06d1e0d068daa3d938e4d7019` | `d442bf1ac37ea0405e43284a271757c60e085e81e578a987c1ae7d2509016ac6` |

Artifacts and per-file hash manifests are stored outside Git at
`/tmp/aw2-normal-power-live/{headless,windowed}/`. The supported-ROM layout
loader also exposed and this run corrected a bad CO-table ROM offset: the
table literal is `0x085D3DD0`, so its file offset must subtract
`0x08000000` from that full address. Before that correction, layout loading
raised `struct.error` before the executor could run.
