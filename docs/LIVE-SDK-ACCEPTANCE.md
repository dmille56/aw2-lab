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
