# Live SDK and emulator acceptance

The opt-in checks in [test_sdk_live_integration.py](../tests/test_sdk_live_integration.py)
exercise the default Bean Island profile with Andy/Red and Max/Blue under external
control, fog disabled, Clear weather, and the default rules. The main scenario
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

The original 2026-11-03 live acceptance pass verified the scenarios below on
the pinned frontends and supported ROM/profile. It did not broaden supported
maps, CO/rule combinations, unit production menus, fog, gameplay actions, or
MCP support; later Milestone 5 follow-up scenarios are recorded separately.

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

## Milestone 5 Super Power action (2026-11-09)

The opt-in `tests/test_super_power_live_acceptance.py` replays the supplied
ready Andy checkpoint through the production `ActivateSuperPowerActionExecutor`
and the real mGBA bridge in both frontends. It validates the settled source
boundary before input, performs the distinct Super menu action, and waits for
the active-power flag, meter result, use counter, map-input UI, and settled
player-turn boundary together. This acceptance calls the executor directly;
HTTP/SDK/MCP routing and the human-client control are covered by ROM-independent
contract/client tests.

Reproduction:

```sh
AW2_RUN_SUPER_POWER_LIVE_TESTS=1 \
AW2_ROM_PATH=/absolute/path/to/aw2.gba \
AW2_SUPER_POWER_STATE_PATH=/absolute/path/to/aw2.ss1 \
  nix develop -c pytest -s tests/test_super_power_live_acceptance.py \
  --basetemp=/tmp/aw2-super-power-live
```

Supported ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Source checkpoint SHA-256:
`19eec5b8576e77ea1ec38ec071413383f8226a1e9747419b880c46427e33a0a1`.
Both frontends restored frame 12924 with Andy/CO ID 1, Super readiness 2,
meter 54,000, use counter 0, active-power byte 0, and no RAM edits. The current
counter's readiness threshold is 54,000; after the game's counter increment,
the debit threshold becomes 64,800. The game clamps the 54,000 available meter
to zero. Both frontends settled at frame 13699 with meter 0, counter 1, and
active-power byte 2.

| Frontend | mGBA build identity | Evidence JSON SHA-256 |
|----------|---------------------|-----------------------|
| Headless | `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` | `d2a5f5276b9a3709ace319db868597d2a9d8aeedefdbdf12ede8b09d4114a8a5` |
| Windowed | `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810` | `9d7f63477c40b658ab49c3c0ef3e4a36459dafec02ec9e5a60d1a6fdf94d3327` |

Private evidence and screenshots are under
`/tmp/aw2-super-power-live-verified/`. This verifies Andy's Super activation
from the researched checkpoint; it does not generalize all CO costs/effects,
duration/reset behavior, or the intermediate presentation classifier.

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

## Milestone 5 Join action (2026-11-10)

The production `JoinActionExecutor` completed the naturally prepared Tank merge
from `aw2.ss1` in headless and windowed mGBA. The mover (reference 1, 27
internal health) started at `(8,5)` and followed `(8,4)`, then `(7,4)`, where
the same-army, same-type partner (reference 3, 51 internal health) stood. The
observed single-row action selector identifies Join with ROM row ID 8. After
confirmation, reference 1 survived at `(7,4)` with 90 internal health and its
turn used; reference 3 was gone. The observer returned to a ready player turn
at frame 27662. The health value is recorded as observed; this case does not
establish a general merge-health formula.

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Ready checkpoint `aw2.ss1` SHA-256:
`1b522efba629301e07041bd9a7ea2ab3f0d419cea06670934d566701f5bb561b`.

| Frontend | mGBA build identity | Evidence JSON SHA-256 |
|----------|---------------------|-----------------------|
| Headless | `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` | `4806cc1de921da1a04fe36ab4a7a9b198e7c569c8c033ee512b7e0509007d87a` |
| Windowed | `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810` | `3a78ed36625b616aebb338bb1ad01661de38d3431c305908e5aacadd097cd083` |

The opt-in acceptance is `tests/test_join_live_acceptance.py` and is enabled
with `AW2_RUN_JOIN_LIVE_TESTS=1`. It checks the complete action path and merge
outcome in both modes. Screenshot SHA-256 values are `fccae882aee0e8480027e1641fcce7ac28d88fb276c605b0286887aa27b6556b` before
and `d86fcde97b82e09f8037576f4f52abb7df9f6ccf3de35eff61efe363d11143d9` after.
Screenshots and JSON evidence are kept outside Git at
`/tmp/aw2-join-live-verified/`.

## Milestone 5 APC Supply action (2026-11-10)

The production `SupplyActionExecutor` completed in headless and windowed mGBA.
Both runs started from the same ready Tank checkpoint `aw2.ss1`, purchased an
APC at Red's owned base through the production menu, advanced through the
required turns, and staged the APC around the impassable mountain ridge using
ordinary Move/Wait. The final Supply route moved the APC from `(5,8)` to
`(6,4)`, adjacent to Red Neotanks at `(6,5)` and `(7,4)`. The live unit-action
selector showed `(Supply, Wait)` with Supply at observed ROM row ID 9; the APC
was consumed at `(6,4)`.

The two recipients changed as follows:

| Unit reference | Before fuel/ammo | After fuel/ammo |
|----------------|------------------|-----------------|
| 2 | 87 / 9 | 99 / 9 |
| 3 | 93 / 8 | 99 / 9 |

Both returned to the ready player-turn boundary at frame 28908. The source ROM
SHA-256 is
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`; the
source checkpoint SHA-256 is
`1b522efba629301e07041bd9a7ea2ab3f0d419cea06670934d566701f5bb561b`. The
separately saved APC-ready checkpoints have SHA-256
`44661a6792f432b2809e498a5e6a9e16ef407d02b1eaca3b3ef67df38bcb0dd8`
(headless) and
`fb41a8f7113d2627edcffb9044d540ff93aa1ce329d0a484299c65f2a9c6be6e`
(windowed). They are generated by the same in-game preparation sequence; the
accepted Supply replay in each frontend began at frame 28754.

| Frontend | mGBA build identity | Evidence JSON SHA-256 |
|----------|---------------------|-----------------------|
| Headless | `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` | `221569cab0e4a653e651a8cadd4e0ca909479aab3d3cf1cca09794e8f619399e` |
| Windowed | `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810` | `bd1ba6d61ebe935801c92cb86427b96e3e059866370a422bd272731acb848d17` |

The before/after screenshot SHA-256 values are
`e2d5c725019e77257546c7dd8129abb8122bbba31ab704afbe25029f02528844` and
`344e6b4362c3f862e054078d816ca2fe63f4870bb2c2d057f41a7e0de462ee6d`.
Per-mode screenshots, derived checkpoints, and JSON evidence are outside Git
at `/tmp/aw2-supply-live-final/`. The opt-in acceptance is
`tests/test_supply_live_acceptance.py`; run both modes with:

```sh
AW2_RUN_SUPPLY_LIVE_TESTS=1 \
AW2_ROM_PATH=/absolute/path/to/aw2.gba \
AW2_SUPPLY_STATE_PATH=/absolute/path/to/aw2.ss1 \
pytest -s tests/test_supply_live_acceptance.py --basetemp=/tmp/aw2-supply-live
```

Automatic allied-property replenishment remains the game's turn-start upkeep;
the live acceptance above focuses on explicit APC Supply. The earlier
[[file:AW2-MAP-RESEARCH.org::*Finding: allied-property recovery and turn-start fuel upkeep][allied-property observation]] records the automatic recovery evidence.

## Milestone 5 Sub Dive and Rise (2026-11-10)

The production Submarine action executors replayed both transitions from the
newly supplied natural checkpoints in headless and windowed mGBA. The surfaced
Sub (reference 1, `(4,7)`) showed `(Wait, Dive)` and finished with status bit 5
set and its turn used. The submerged Sub showed `(Wait, Rise)` and finished
with bit 5 cleared and its turn used. Both returned to a ready player-turn
boundary; no unit movement was requested.

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Surfaced checkpoint `aw2.ss1` SHA-256:
`ee3751cf9f910a10710652dbf9d9bdf52feada7d5db5e89b8c616cc67aa3d8cd`.
Submerged checkpoint `aw2.ss6` SHA-256:
`3a2698b25f93efa58acab80b4b148b55cf592cef8d7889243685ff309b1f15d7`.

| Action | Restored → settled frame | Headless evidence JSON SHA-256 | Windowed evidence JSON SHA-256 |
|--------|--------------------------|--------------------------------|--------------------------------|
| Dive | 4575 → 4687 | `85cfeafc4c45bf8f2c05a321c22ef08d85424d4ca6afddb17252c3c9ceda7980` | `f1bfd9c67e1f01bdcdc0301f116ea00cda1c37e620ee47696e949f67ffcebc17` |
| Rise | 5824 → 5936 | `4ac1f014585d07aa4d8e5ddf4f7180b88221c5357f7971ab4a47600c4c73dc99` | `1c826b5f2705be34eb8bc1a804c0181c5a41a2993b047e8dd8ee86c8a0c4ca57` |

Both frontends used build identities `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`
(headless) and `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`
(windowed). Dive before/after screenshot hashes are
`feba40bee11d018426757e341a5e73904b21f11d8017cbf2ba638b0dcad38f3e` /
`0f1a869b244aece60d2c756f973ab14e5c2fc1545cf1236e9441d0796d381ce6`;
Rise hashes are
`bf8730d0baec97c6825581b297ac824ff89c2856f9387b419ce7bc0475a9ed51` /
`ae2921c591f384e43925e58aba06b797008caf37d48f42d8a96338d50bd00b04`.
Per-run screenshots and evidence JSON are outside Git at
`/tmp/aw2-submarine-live-verified/`. The opt-in acceptance is
`tests/test_submarine_live_acceptance.py`; run it with
`AW2_RUN_SUBMARINE_LIVE_TESTS=1 pytest -s tests/test_submarine_live_acceptance.py`.

## Milestone 5 missile silo launch (2026-11-10)

The guarded `silo_launch` action replayed the supplied ready map ID 85 state in
headless and windowed mGBA. Infantry reference 1 at `(3,16)` selected the
observed Launch row, acknowledged the first-use tutorial, moved the target
cursor from `(3,16)` to `(2,13)`, and confirmed. Both runs returned to the
settled player-turn boundary at frame 5147. The Infantry remained at `(3,16)`
and became used; its silo changed from terrain 17 to spent terrain 18. Four
enemy Infantry in the 3x3 blast changed from 100 to 70 health: `(2,14)`,
`(1,13)`, `(2,12)`, and `(3,13)`. This records the observed damage in this
checkpoint only; no general damage formula or launch range is claimed.

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Ready checkpoint `aw2.ss1` SHA-256:
`77afc4d6ef7267e7a7ea57787baeeada3528a52c47c8a2054a2383890e71a2ef`.

| Frontend | mGBA build identity | Evidence JSON SHA-256 |
|----------|---------------------|-----------------------|
| Headless | `sha256:2428496c7cf6efaa59aa9533d2e3c2ce7c79771b642695a1fe24744c42871810` | `5582f882b290af7b6d326e29a1c5ab3828a4bd991d00e54ebd93c6dd3e87e251` |
| Windowed | `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810` | `87fd9000279a765c576ddc96715a5f2dcb4f9044eb10c5d16697debacefb1d1a` |

Both runs used the same screenshot hashes: before
`c3c82a69a2960e79aee393e6fbcb11d81184bc52493592d15941bdb2789910af`, after
`e80f78f2ef759bd4df098d7c7c8f33479bbd9c0376081b4e4497495a851f3257`.
Generated evidence and screenshots are outside Git under
`/tmp/pytest-of-dono/pytest-1304/test_live_silo_launch_headless0/headless/`
and
`/tmp/pytest-of-dono/pytest-1305/test_live_silo_launch_windowed0/windowed/`
(the repeated headless run produced identical evidence). Run both frontends
with:

```sh
AW2_RUN_SILO_LIVE_TESTS=1 pytest -s tests/test_silo_live_acceptance.py
```

ROM-independent UI tests cover the Launch/Wait row mapping and target
prompt/cursor classification. Public API, MCP, runtime, capabilities, and human
client payloads expose the typed launch action. Missile range restrictions and
spent-silo re-selection behavior remain outside the verified acceptance.


## Milestone 5 map selection (2026-11-10)

The first map selection implementation covered the 17 two-player **Classic**
maps, with Bean Island as the default. Each complete configuration was
advertised as `<map_id>_v1` and used Andy/Max, Red/Blue, teams A/B, external
control, and the verified rules.

The catalog's ROM IDs, names, army count, and dimensions were checked against
the supported original ROM: header table `0x085C77A0`, stride `0x5C`, map payload
pointer at offset 0, name ID at `+0x14`, army count at `+0x18`, category at `+0x1A`, and name string
pointer table `0x08610A38`. The first two decompressed payload bytes are width
and height. Live startup independently checks the loaded ID and decoded dimensions.

Every catalog entry reached the first recognized player turn in both frontends.
The checks verify two human-controlled armies (Andy/Max, teams A/B), day 1/Red,
Clear weather, Fog Off, CO effects On, and income from Red's observed properties.
No Bean Island opening-funds constant is applied to other maps.

| Map ID | ROM ID | Dimensions | Red / Blue opening funds | Headless / windowed frame |
| --- | --- | --- | --- | --- |
| `bean_island` | 1 | 16 × 15 | 11,000 / 0 | 3983 / 3984 |
| `crater_isle` | 2 | 16 × 15 | 11,000 / 0 | 4104 / 4105 |
| `triangles` | 3 | 16 × 15 | 5,000 / 0 | 4225 / 4226 |
| `ball_islands` | 4 | 42 × 15 | 10,000 / 0 | 4376 / 4377 |
| `coral_lagoon` | 5 | 16 × 15 | 5,000 / 0 | 4467 / 4468 |
| `puzzle_trio` | 6 | 32 × 15 | 15,000 / 0 | 4588 / 4589 |
| `fist_peninsula` | 7 | 16 × 15 | 4,000 / 0 | 4709 / 4710 |
| `deer_harbor` | 8 | 32 × 30 | 8,000 / 0 | 4860 / 4861 |
| `alara_range` | 9 | 32 × 15 | 7,000 / 0 | 4951 / 4952 |
| `lost_river` | 10 | 32 × 15 | 6,000 / 0 | 5072 / 5073 |
| `volcano_isle` | 11 | 16 × 15 | 5,000 / 0 | 5193 / 5194 |
| `turtle_atoll` | 12 | 16 × 30 | 12,000 / 0 | 5314 / 5315 |
| `squash_island` | 13 | 48 × 15 | 7,000 / 0 | 5465 / 5466 |
| `cube_keys` | 14 | 32 × 30 | 7,000 / 0 | 5556 / 5557 |
| `mirror_islands` | 15 | 32 × 15 | 6,000 / 0 | 5677 / 5678 |
| `shark_strait` | 16 | 37 × 30 | 17,000 / 0 | 5888 / 5889 |
| `royal_channel` | 17 | 39 × 30 | 23,000 / 0 | 6009 / 6010 |

The opt-in test also drops the map-navigation Down input when requesting Crater
Isle: Bean Island loads, and startup raises `ColdBootError` before any CO/team
input. The real application test selects Crater Isle, starts the match, ends
both turns, restores a checkpoint, and continues play. Public summaries and the
checkpoint manifest retain `crater_isle` throughout. ROM-independent tests cover
all map choices through durable authorization creation, restart/retry, profile
validation, runtime boot forwarding, and checkpoint metadata. Unknown maps and
unverified player/rule combinations retain their existing rejection behavior.

These commands reproduce the original Classic coverage on revision `acef405`.
Run them sequentially because the emulator bridge uses port 43128.

```sh
AW2_RUN_MAP_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_map_selection_live_acceptance.py
AW2_RUN_RUNTIME_TESTS=1 AW2_RUNTIME_MAP_ID=crater_isle AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_playable_runtime_integration.py
```

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Headless build: `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
Windowed build: `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.

Evidence is external at `/tmp/aw2-map-selection-acceptance/` and
`/tmp/aw2-map-selection-recheck/`: per-map JSON and screenshots; the latter also
contains the dropped-input rejection trace. The aggregate
`/tmp/aw2-map-selection-summary.json` records all 34 accepted mode/map cases,
frames, funds, build identities, screenshot hashes, and individual evidence hashes;
its SHA-256 is
`3cec678e895754678215e7ddf5c5784e8f87b566819e64bfee7becce2f670cf3`.
Application checkpoint/restore artifacts are external at
`/tmp/aw2-map-runtime-recheck/`.

An initial headless Volcano Isle case and initial application run overlapped on
the shared bridge port, producing a frame mismatch/input-release error. The
sequential Volcano Isle retry and dropped-input case passed; the remaining 33
map/mode cases passed in the original matrix. This was a test-run collision,
not accepted map evidence. Saves and ROMs remain outside Git and the Nix store.

Limits: these checks establish startup and structured first-turn observations
for each map, plus alternate-map checkpoint continuity. They do not establish
complete playthroughs or new map categories, COs, rules, weather, fog modes, or
player counts. Cross-platform acceptance remains deferred until after Milestone 5.

## Milestone 5 additional Versus map categories (2026-11-10)

The original ROM has 137 entries across six built-in Versus categories. The
catalog contains every entry whose army count at header offset `+0x18` is two.
The category at offset `+0x1A` agrees with the live selector at `0x0300596C`.
Menu positions count all preceding entries in a category, including maps for
more than two players.

| Category | Selector | ROM rows | Two-player profiles | Profiles requiring unlocks |
| --- | ---: | ---: | ---: | ---: |
| Classic | 2 | 17 | 17 | 0 |
| Vs. Maps | 3 | 21 | 21 | 1 |
| Pre-Deployed | 4 | 20 | 12 | 1 |
| 3P Maps | 5 | 24 | 0 | 0 |
| 4P Maps | 6 | 25 | 0 | 0 |
| War Room | 7 | 30 | 22 | 6 |

All 72 profiles reached the expected first player turn in headless and windowed
mGBA. The checks verify the loaded ROM ID, dimensions, two external players,
and fixed match rules. The eight unlock-dependent profiles passed with the
companion cartridge save loaded from an isolated copy. The source save's hash
matched before and after each run.

The negative cases dropped Down while selecting Crater Isle and Right while
selecting Little Island. Both failed before CO setup. Hourglass Isle was
rejected with a fresh save in both frontends. ROM-independent tests verify that
the startup error retains the menu diagnostic and publishes a recovery-required
match without a playable observation.

To reproduce the map matrix, use a ROM with a companion `.sav` containing the
relevant unlocks. The fresh-save cases create their own isolated ROM copies.
Run emulator tests sequentially because the bridge uses port 43128.

```sh
AW2_RUN_MAP_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_map_selection_live_acceptance.py
```

The ROM and frontend build hashes match the original Classic acceptance above.
The source cartridge save SHA-256 was
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.
The initial run produced 77 map records before interruption. The resumed run
passed the remaining 67 map cases and all four rejection cases. External
evidence directories `aw2-versus-categories-acceptance` and
`aw2-versus-categories-resume` contain the per-case observations and screenshots.
The combined `aw2-versus-categories-summary.json` has SHA-256
`926c1b47663b4fbaf7fbd95702999df2c5e98e06b64c136f9e4eb43ae1ae0c9c`.

Little Island, Big Daddy, and Pay Dirt also passed the real application check
in each frontend. Each match starts, commits a checkpoint, advances to Blue's
turn, restores that boundary, and continues to Red's second day. The match
summary and checkpoint manifest retain the selected map ID. Run the same check
with `AW2_RUNTIME_MODE=headless` and `AW2_RUNTIME_MODE=windowed`.

## Milestone 5 locked Versus map availability (2026-11-10)

Individual map-unlock flags are not decoded reliably from SRAM, so
`configuration_profiles` expose `availability` as `always_available` or
`save_dependent`, alongside the existing `requires_unlock` field. This describes
the catalog, not the current save. Start checks the actual Versus selector and
fails before CO setup if a requested map is locked. The diagnostic directs the
operator to unlock the map in Battle Maps. With no companion `.sav`, mGBA starts
from a fresh isolated save and save-dependent maps are not selectable.

Fresh-save checks rejected a representative save-dependent map from each of the
five map categories (Versus, Pre-Deployed, War Room, 3P Maps, and 4P Maps) before
CO setup in both frontends. Using the supplied save, all 17 save-dependent
profiles reached the expected playable boundary in both frontends. Per project
direction, this check omitted a partially unlocked save. The user-supplied `aw2.sav` SHA-256
was `f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a` before
and after the runs.

ROM SHA-256:
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Headless build:
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
Windowed build:
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The paired screenshots matched across frontends for each map:

| Map | Frame | Screenshot SHA-256 |
| --- | ---: | --- |
| Archipelagos | 7802 | `2c0d31dc97c91321a6082423903cdd59cbfd3f8d4f78399c877a3bb0bc89aa33` |
| Badlands | 8563 | `023a953eb53ac286d205a0a7ff12228cc5ce9bdd2717f950e351cec7aa7ff9bc` |
| Banker Hills | 7917 | `41b81e08006053c9129f182024159847d1eeda6b0e21fcd674fd44a97d79d2e2` |
| Big Daddy | 6707 | `2a4a1f7797bba148abbc6a0a830baacbcf6657854c1523f108863980bfaddba8` |
| Crossroad | 7626 | `4dca062a667c67b52d375c4339e961b8d564d6d80e28f0829545e2a1edad8012` |
| Grid Assault | 7505 | `f919699a87ab45de372c5b85eb92d53b8e99434288e045bfbb0d427a663055f0` |
| Heartland | 8352 | `29cbb722205305fec6a7868e9efd1354ba2a18c19b80c13593eb0c13fcc40feb` |
| Hourglass Isle | 6949 | `2cd39c574bed2db90a1c124f8485a7d5bea18898620f0680acb678b9abf4068d` |
| Knotted Keys | 8014 | `8a3ac28a9bccb7b0a543b54b7bb5e26067af0ca3cc46f204c37f5e0c3a62cb36` |
| Lock Ridge | 8231 | `cf26ca7d04f554d7d7e87ee08f70b4de55d0161a7e7b5158a60472447d5bb95c` |
| Long Road | 7554 | `339dad1dab049f6724c27690861f342d13ff308226f0b11efd1f24fff58b0de2` |
| Missile Plains | 8068 | `06760a22c962bf26017993233383918ebcfb4c5180adec9edde3f5b53f42ccfe` |
| Nest Egg | 7675 | `35363c2912622fa0c9279af2a6c27cec12bce1b530ea4044ed3a303f37fc5d6e` |
| Pay Dirt | 7433 | `cbcec473c91aa419106ad6a7ac2d3421c6beddb75f8811f52ce5676529089eb1` |
| The Trident | 7826 | `ef5f012d65ebaaf8fa014d8063bfc5bc95965bc6f7e96d826a4a2bdb241eb7bb` |
| Wyrm's Eye | 7893 | `d86543a9dcfa208ff73221b4b2d24c1789574506bf6f36b0eed62459029c513e` |

Accepted-map evidence is external under `/tmp/aw2-map-unlock-final/`. Fresh-save
selector traces are under `/tmp/pytest-of-dono/pytest-1433/`; they end at each
map's confirmation label and contain no CO setup input.

## Follow-up isolated map-save provisioning (2026-11-11)

`record-cold-boot` now builds a reusable ROM/save pair in its external output
directory. It explicitly loads the copied save before resetting the core,
records the final isolated-save hash and source-save unchanged status, and never
opens the source `.sav` as a writable file. Manual windowed input can be used to
earn/purchase map unlocks through AW2 itself. The automated verifier accepts
`--map-id`, records the requested map and navigation progress, and writes a
failure reason if the game rejects the map. A successful result records the
settled playable map ID. This does not patch RAM or automate unlock progress.

The supplied save remained unchanged at SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`. With the
supported ROM SHA-256 `ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`,
Hourglass Isle loaded as map ID 38 at 16x24 in both headless build
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` and
windowed build
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The verifier completed at frame 6949. A fresh save rejected the same request
before Teams setup in both frontends, with the reason “Hourglass Isle is not
selectable in this save; unlock it in Battle Maps.”

Recorder evidence is in `/tmp/aw2-map-save-verify-1111-headless-v2/` (verified
existing save) and `/tmp/aw2-map-save-verify-fresh-1111/` (fresh-save rejection).
The separate headless/windowed acceptance traces are under
`/tmp/pytest-of-dono/pytest-1450/`, `pytest-1451/`, and `pytest-1452/`. No
partially unlocked `.sav` was available, so verification of mixed unlock states
remains open.

### Cheat-code provisioning probe (2026-11-11)

On a disposable ROM copy, mGBA loaded the published CodeBreaker “Have All
Battle Maps” code together with its enable code and wrote the expected unlock
pattern into EWRAM at `0x02028040`. The automated Versus selector still rejected
Hourglass Isle. This establishes that the code was being applied, but that it
does not provide the Versus unlock needed by this workflow. The separate
published “All Vs Maps” code is Action Replay MAX encrypted and remains
unvalidated. A startup cheat containing the direct write `0x02028046 = 0xFFFF`
also left the map unavailable. However, writing the same value at the selected
map checkpoint immediately before confirmation loaded Hourglass Isle (ID 38,
16x24) at frame 7041. That first run had a CO-index mismatch. A repeat using the
fresh-save roster indices Andy=0 and Max=1 passed the complete playable-state
checks at Hourglass Isle, map ID 38, 16x24, frame 6948, with battle CO IDs
`[1, 2]`. The application still needs an explicit fresh-roster mapping and an
opt-in late write to reproduce this path automatically. No in-game save was
made, so persistence is unverified. See
[[file:COLD-BOOT-RESEARCH.md::*Cheat-code investigation][the provisioning research note]].

The published all-CO GameShark Advance code and direct `0x0202805A = 0xFFFF`
write did not expose the campaign-locked COs in a fresh save under the tested
mGBA setup. The supplied SharkPort `.sps` was extracted to a disposable `.sav`;
its payload hash matches the existing `aw2.sav` exactly. With this profile, the
isolated launcher passed Hourglass Isle with Nell and Sturm at frame 7073, and
Pipe Maze with Nell, Hachi, Sturm, and Hawke at frame 8450 (battle CO IDs 0, 15,
10, and 14). The original `.sps` and `.sav` were not modified. The named
`gameshark-all-unlock/` directory was empty; the `.sps` was in
`all-unlocked-saves/`.

The recorder now accepts that `.sps` directly, validates its SharkPort
container and ROM identity, and extracts its 64 KiB payload to the disposable
profile's `save-data/aw2.sav`. A headless recorder run using the supplied `.sps`
reached Hourglass Isle (map ID 38) at the first player turn, frame 6949. The
source `.sps` remained unchanged (SHA-256
`b7cff54d1e06baaf79bf4a416f2e080243ba31d514e48d1d0d29be1d83ecedea`); the
manifest reports `source_save_unchanged: true`. The prepared pair is under
`/tmp/aw2-sps-profile-validation-hourglass2/`. This profile can be used for
local runs while the source GameShark save remains read-only; launcher runs also
copy companion saves into their own temporary workspace.

Normal runtime startup now accepts `--save-profile /path/to/profile.sps` or
`AW2_SAVE_PROFILE_PATH=/path/to/profile.sps`. The launcher creates an isolated
ROM/save pair, validates and converts the SPS before launch, explicitly loads
the temporary `.sav`, and removes the workspace at shutdown. A startup-path
probe used that setting with a blank adjacent `.sav`; Pipe Maze loaded at map ID
104 (22x22) with Nell, Hachi, Sturm, and Hawke (battle CO IDs 0, 15, 10, 14) at
frame 8450. The adjacent blank save and source SPS were unchanged.

```sh
AW2_RUN_RUNTIME_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  AW2_RUNTIME_MAP_IDS=little_island,big_daddy,pay_dirt AW2_RUNTIME_MODE=headless \
  pytest -q tests/test_playable_runtime_integration.py
```

## Milestone 5 CO selection (2026-11-10)

The Teams screen stores each player's CO roster index in the byte array at
`0x02017C6C..0x02017C6F`; the selected setup field is at `0x02017C82`.
The supplied checkpoints show that Down increments the focused CO index and Up
decrements it. From slot 1's CO field, two Right presses move focus through the
slot 1 player-control field to slot 2's CO field. Startup observes and checks
focus and the affected candidate byte after every input, then verifies both
settled battle CO IDs before proceeding to Rules.

The setup candidate order is `Nell, Andy, Max, Sami, Hachi, Olaf, Grit, Colin,
Kanbei, Sonja, Sensei, Eagle, Drake, Jess, Flak, Lash, Adder, Hawke, Sturm`.
Battle player records use a different ID order; cold boot verifies that mapping
rather than assuming the setup index equals the battle ID.

The live matrix exercised 19 adjacent roster pairs in headless mGBA. Across the
matrix, every CO was selected once in each player slot, and every match reached
day 1 with the requested battle CO IDs. A windowed mGBA run also passed for
Nell versus Andy. Match configuration, capabilities, durable summaries, and
checkpoint restore retain each CO selection. The source cartridge save remained
at SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.

The opt-in test covers the full 19-pair matrix in either mode. The recorded run
used:

```sh
AW2_RUN_CO_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_co_selection_live_acceptance.py -k headless
AW2_RUN_CO_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q 'tests/test_co_selection_live_acceptance.py::test_live_selected_cos[0-windowed]'
```

ROM SHA-256: `ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Headless build: `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
Windowed build: `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The supplied setup-state hashes and candidate bytes are recorded in
[`AW2-MAP-RESEARCH.org`](AW2-MAP-RESEARCH.org). Per-case screenshots and JSON
are external under `/tmp/pytest-of-dono/`; the aggregate
`/tmp/aw2-co-selection-acceptance.json` has SHA-256
`3b536f66563c13d8f0346650fe64c37d8cef5f8d68a4b0705153cb0ba6474390`.

Limits: the complete roster matrix ran headless; windowed coverage is one
non-default pair. Other map, rule, weather, fog, and player-count settings remain
outside the accepted configuration.

## Milestone 5 configurable match rules (2026-11-10)

Selected income, day-limit, capture-limit, and CO-power values are set on the
Versus Rules screen. The live scenario requested income 2,000, day limit Off,
capture limit 20, and CO powers Off, with fog Off and Clear starting weather.
The Rules-screen screenshot shows `Funds 2000`, `Day OFF`, `Capt 20`, and
`Power OFF`. The selector bytes were checked after each input; the first player
turn confirmed CO effects Off and Red's funds matched 2,000 per owned property.

The same configuration passed headless and windowed mGBA on the supported US
revision-0 ROM (SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`). The
headless and windowed builds were `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` and
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
Both Rules-screen screenshots had SHA-256
`69fbbd4d43cedb125a1c735aa6ca923ba6ba4ee7663f7371d2b33e1d5960d898`; the
first-turn screenshots had SHA-256
`00663b7db141912bd3e24bf5e8a2bcd71fdae6f6bd5c262f6602480cddd6041c`. The
source cartridge save remained SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.

The opt-in check is:

```sh
AW2_RUN_RULE_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_rule_selection_live_acceptance.py
```

This run verifies one non-default combination in both frontends. The unit and
contract tests cover each selector mapping and advertised range. Fog-enabled
matches remain a separate TODO.

## Milestone 5 starting weather selection (2026-11-10)

The Rules screen Weather selector order is Random, Clear, Rain, and Snow at
indexes 0, 1, 2, and 3. Match setup now selects each value with RAM-guarded
inputs. At the playable boundary, fixed weather is checked against the settled
weather byte at `0x03003FC2` and fixed mode at `0x03003FED`; Random is checked
for random mode. The API and durable match configuration advertise and retain
all four choices.

All four choices passed in headless and windowed mGBA using the supported US
revision-0 ROM (SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`). The
headless and windowed builds were
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` and
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
For each weather, the Rules screenshot SHA-256 was Clear
`69fbbd4d43cedb125a1c735aa6ca923ba6ba4ee7663f7371d2b33e1d5960d898`, Random
`7ee6434e72f4c0c15562cbccdc902cbd6a51037a895e17324eee9c1df574622a`, Rain
`c1419e41a155c4929e1bd86910b562e404e79138c6cd3462a505f84cc1709035`, and
Snow `98172a7acb4960e14b59cca029590316f1e675d2e8db0d9804b7528f8408ceac`.
First-turn screenshot SHA-256 values were Clear
`00663b7db141912bd3e24bf5e8a2bcd71fdae6f6bd5c262f6602480cddd6041c`, Random
`0f7ca9b75e36b639649e0f14602d88a20172677ca3d6d434623ad1b3abcbd15a`, Rain
`08cf45138a9adb9e4e800639b0cc98f0834352310ad989e37226cd2b0fd012de`, and
Snow `a94199cb62dbd809357a30fec9875ab4576111e9d59bbceae6230f29b2377e43`.
Screenshots matched between the two frontends for each weather. All runs used
the unchanged source cartridge save SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.
Per-case `evidence.json` and screenshots are retained externally under
`/tmp/nix-shell.VclHA9/pytest-of-dono/pytest-0/`.

The opt-in check is:

```sh
AW2_RUN_RULE_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_rule_selection_live_acceptance.py
```

This weather matrix uses Fog Off; fog has separate live coverage below.

## Milestone 5 fog-enabled matches (2026-11-10)

Fog On was selected through the guarded Versus Rules selector and observed as
enabled at the first playable boundary in both mGBA frontends. The public
capabilities document declares
`observation_visibility: "omniscient_trusted_clients"`; all authorized clients
can read the same full decoded board state, including during Fog matches.
Player-specific visibility filtering is intentionally not implemented, so
clients must be trusted with omniscient match data. The initial map boundary
contains no units; this run verifies the fog rule and observation policy, not
visibility of a particular hidden unit.

ROM SHA-256: `ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
The isolated headless mGBA build is
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`; the
windowed build is
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
Both reached frame 4257 with Fog On and produced the same screenshot SHA-256:
`bb500a932876f9e8e6db022131a15c65c3b36d7ce61e2b6384e207e29cfa3dd2`.
The source save stayed unchanged at SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.
Per-run `evidence.json` and `fog-on.png` are retained outside Git under
`/tmp/pytest-of-dono/pytest-1426/test_live_fog_enabled_match_is{0,1}/`.

## Milestone 5 two through four players and teams (2026-11-10)

The public configuration, durable match metadata, authorization ledger, and
checkpoint archives now preserve two through four ordered player slots.
Each configured slot has an independent invitation, credential, authorization
generation, and revocation state. Unconfigured slots fail with a safe slot error.
Start requires every configured slot to join. Legacy two-player metadata retains
its defaults. Contract tests cover durable reload, credential scope, invalid
player-count/team combinations, and three/four-player checkpoint archive round trips.

The supported ROM's built-in Versus catalog has 133 entries: the existing 72
two-player entries plus 61 three/four-player entries. Map profiles contain the
correct player count. Slots retain Red/Blue/Green/Yellow color order and external
control. Three-player teams use A–C, four-player teams A–D, and at least two
teams are required. Two-player matches retain A/B.

Twelve representative cases passed (each row in both headless and windowed mGBA):

| Map | Slots | Teams |
| --- | --- | --- |
| Bean Island | 2 | A/B |
| Pyramid Cape | 3 | A/B/B |
| Four Corners | 4 | A/A/B/B |
| Delta Heights | 3 | A/B/B |
| Coil Range | 4 | A/A/B/B |
| Stamp Islands | 3 | A/B/B |

Each run verified all settled COs, external controls, team IDs, map identity,
geometry, rules, day, active slot, and opening funds. Pyramid Cape and Four
Corners also completed a full round through every external player to day 2.
Four Corners continued as a playable match after player one's surrender.
The tests locate Rules selectors by their live object signatures because the
multiplayer setup allocates different selector layouts; see
[COLD-BOOT-RESEARCH.md](COLD-BOOT-RESEARCH.md).

ROM SHA-256: `ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
Headless build: `sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
Windowed build: `sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The source save remained SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`.
The representative runs used `/tmp/pytest-of-dono/pytest-1401/`; raw pytest
artifacts follow pytest temporary-directory retention.
The twelve-case aggregate `/tmp/aw2-multiplayer-acceptance.json` has SHA-256
`84c2bc1371a42c051fe281e24c674deac3edffb524816f8733ed005bfc5c9ad1`.
Headless and windowed first-turn screenshots match for each map; Four Corners
has SHA-256 `078ff781845527dd09cf5969e11d39583f659646575e77b1bcc2298f8a477cad`.

Run the representative matrix with:

```sh
AW2_RUN_MULTIPLAYER_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_multiplayer_live_acceptance.py
```

Live emulator checks must run sequentially: the bridge uses localhost port 43128.
Fog, visibility restrictions, locked-map discovery, and the final Milestone 5
acceptance audit remain separate tasks.

The full 61-map headless sweep passed 48 entries and exposed a previous tile-ID
limit on the other 13. The pinned ROM catalog and live memory confirmed tiles
471/472 as Yellow airports/ports; raising the supported limit from 470 to 472
fixed all 13 on rerun. The original sweep log `/tmp/multi-catalog-live.log` has
SHA-256 `bb45641c39073b0090bd0ccdd3d48b0213391598f4e367080e75846036f5866c`;
the thirteen-case successful rerun `/tmp/multi-tiles-live.log` has SHA-256
`cfc14fd2dc11c362cccf5421245ca5ab0e9d286b54a604a80bd2dd5522f6feb9`.
Together they verify startup for every newly enabled map. Run the complete new
catalog check sequentially with:

```sh
AW2_ADDITIONAL_MAPS_ONLY=1 AW2_RUN_MAP_SELECTION_TESTS=1 AW2_ROM_PATH=/private/aw2.gba \
  pytest -q tests/test_map_selection_live_acceptance.py -k headless
```

A final Four Corners run passed in both frontends after player one's surrender:
players 2, 3, and 4 each ended their turns, player 1 was skipped, and player 2
received day 3. This verifies continuation through a defeated army even when
its player record remains allocated. First-turn screenshots and per-case JSON
are preserved externally under `/tmp/aw2-multiplayer-continuation-evidence/`;
its aggregate JSON has SHA-256
`19505fdba038b9280a73c4875a25af06420845695a3257c1f70a0cd575cf5ddb`.
The successful two-case log `/tmp/multi-surrender-live.log` has SHA-256
`99db33d5c94c6f7da021687c7391181685cc33299c5435b1c861e2db3be3ec87`.

## Milestone 5 late-write map unlock persistence (2026-11-13)

Using the supported ROM SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`, the
opt-in recorder run selected Hourglass Isle with Andy vs Max on a fresh isolated
save and verified the first player turn at frame 6948 in both modes. Pinned mGBA
builds were headless
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22` and
windowed
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The common automation-result SHA-256 is
`d20a692347ecf45622083446603f0ea2f64d2c317fbf651cafbcadc08711c24a`.

After the windowed run, the interactive recorder continued into the in-battle
Select menu. Save → “Save current data?” → Yes displayed “Save complete!” at
frame 7461. The isolated save became SHA-256
`44bd7fbcb21361df42c93eaa9036678215b2b0d5aaa3524d3658b1431f955677`; the
“Save complete!” screenshot is `/tmp/aw2-late-unlock-save-attempt-20261113/step-0106.png`
(SHA-256 `f37090527006f860b5e69df20491d7bbe386fab092f6632b194b4c84f9bbed4c`).
Before the in-game save, an otherwise equivalent fresh run's stopped-emulator
save remained SHA-256
`8b3943cb2ab71539a3510c0834658c397af2d2745ec60f3a7bc3b7e8e7426338` and was
still rejected on restart. This distinguishes the game save from mGBA shutdown.

Restarted from the in-game-saved copy without the late write in both frontends.
Both selected Hourglass Isle and entered Versus setup (map bytes `10001800`,
16x24); neither reported that the map was locked. Both later stopped at first
turn verification because the resumed save's CO setup produced Max for player
1 where the fresh-roster Andy expectation was configured. The matching restart
automation-result SHA-256 is
`16f470deaa57cd168cf8c0d8960b2f1646db5cad9140334f5344ad5ec84e27c5`. The
source save supplied to each restart remained unchanged. This accepts
persistence for the tested Hourglass Isle flow only; broader profiles and
partially unlocked saves remain unverified. Evidence directories are under
`/tmp/aw2-late-unlock-{headless,windowed,save-attempt,restart-check,post-save-restart,post-save-windowed}-20261113/`.
