# Queued playable runtime

`PlayableRuntime` binds one launcher bridge to queued startup, all six gameplay
executors, the current `CheckpointSession`, checkpoint persistence, input release,
and rollback. The default application's lifespan installs it after emulator startup
and checkpoint recovery, before starting the controller queue. Transport routes
remain a separate task; the service entry point is
`AuthorizedMatchService.start(principal, match_id, StartMatchRequest(...))`.

Start requires an operator, expected revision zero, and both slots joined. Its
navigation executes in the same FIFO lane as gameplay. Permissions, lifecycle,
revision, and current claims are rechecked before input. Retrying the same request
returns its receipt; a distinct queued start becomes stale after the first start
succeeds. Joining never starts emulation by itself.

Start persists an executing setup boundary before reset/navigation, then resets
the isolated emulator and runs bounded fixed-match menu navigation. It commits
revision 1, an initial checkpoint and CURRENT pointer, and its terminal command
result before reporting completion. Reads during startup expose executing with no
invented playable observation. Failure after startup begins leaves a
recovery-required match with no playable publication; operator inspection and close
remain possible. On restart, an interrupted start without a committed initial
checkpoint is terminalized as recovery-required instead of restoring another
match's checkpoint or replaying controller input. A committed initial checkpoint
uses the existing pointer/journal reconciliation path.

## Configuration correction and verification

The previously documented defaults did not match the cold-boot routine: the Rules
screen showed Turn OFF and Random weather. The UI's Funds 1000 option is income
per owned property, not an initial 1,000 balance for each army. On Bean Island,
the first Red turn has 11,000 after income while Blue still has zero.

The transport contract now uses `rules.income_per_property: 1000` in place of
`starting_funds`. It still requests a 30-day limit, Clear weather, Fog Off, and
CO effects/powers On. `FixedMatchConfiguration` retains its old stored field name
for checkpoint/authorization-ledger compatibility; the explicit adapter converts
it to the correct transport name. Old transport payloads with `starting_funds`
are rejected rather than silently promising initial cash. This correction is in
the unreleased v1 transport contract; persisted legacy documents retain their shape.

Startup now selects Clear and sets the day limit to 30 explicitly. The Rules
widgets have a 0x60-byte stride starting at `0x03001698`: Fog Off index 1,
Weather Clear index 1, Funds 1000 index 0, Turn 30 index 26, Capture limit Off
index 0, and Powers On index 0. Turn goes from OFF to 5 on the first Down, then
increments one day per Down. Every increment and final combination is checked
before confirming. The final playable observation verifies Bean Island ID 1,
16×15 dimensions, Red Andy/Blue Max, external control, separate teams A/B,
day 1/Red turn, Clear weather, Fog Off, CO effects On, and funds 11,000/0.
Unknown or mismatched settings fail startup through recovery.

## Sessions, gameplay, and persistence

The dispatcher supports MoveWait, MoveAttack, MoveCapture, Purchase, EndTurn,
and Surrender using the existing executors and bounded `ActionNavigator`.
It constructs the chosen executor with the current session tracker on each
command. Checkpoint restoration and rollback replace `session.tracker`; no
long-lived executor retains the prior tracker.

A pre-action checkpoint is captured before gameplay input. A completed playable
or recognized terminal boundary prepares its own durable checkpoint commit.
Failures after input use the pre-action checkpoint and advance revision during
rollback; subsequent gameplay sees that replacement tracker. Finished checkpoints
can be adopted on restart with unavailable battle RAM/unit identities, without
reopening gameplay. Restoring an older playable checkpoint cannot reopen a
finished or closed match. Authorization remains independent of emulator states.

The application's checkpoint-service reference is updated when a new match starts.
Recovery/input-release delegates resolve the current service, so closing a match
and creating another does not leave providers attached to the previous session.
The server launcher copies the ROM and any adjacent `.sav` into a private temporary
workspace and points mGBA's saves/configuration there. Existing-save overwrite
prompts affect that copy. Original ROM/save files are not modified; the workspace
is removed after emulator shutdown. Researchers can still explicitly use the
standalone launcher without server save isolation.

## Verification

ROM-independent tests in `test_playable_runtime.py` cover queued/deduplicated
startup, both claims and operator checks, initial checkpoint commit, failed and
interrupted startup, all six dispatch choices, tracker replacement after explicit
restore and rollback, terminal checkpoint restart, and rule verification. Launcher
and app tests cover save isolation, cleanup, and shared bridge wiring.

Run the opt-in application-service regression with a local supported ROM:

```sh
AW2_RUN_RUNTIME_TESTS=1 AW2_ROM_PATH=/path/to/aw2.gba \
  nix develop -c pytest tests/test_playable_runtime_integration.py -v
```

`AW2_RUNTIME_MODE=windowed` selects windowed mGBA and requires a working display.
The check creates its own operator/player credentials, copies saves, starts via the
queue, ends Red's turn, restores a checkpoint, then ends Blue's turn using the
replacement tracker. It uses the actual app/runtime but substitutes the independent
MCP session lifecycle; no HTTP gameplay or MCP integration claim is made.

Headless evidence on 2026-10-31 passed with US revision-0 ROM SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`
and mGBA build
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
The opt-in regression passed in 37.92 seconds. A separate real app-lifespan run
also completed Start at revision 1, EndTurn at revision 2 with Blue active, and
Restore at revision 3. External evidence is under
`/tmp/aw2-playable-runtime-live/`; rule selector screenshots and memory samples
are under `/tmp/aw2-runtime-rules-probe/`. These artifacts contain local game data
and private authorization storage and must stay outside Git/Nix. The Rules
screenshot shows Clear, income 1000, Turn 30, Capture OFF, Powers ON, Fog OFF.
This verification covers the new headless composition path. Windowed runtime,
live purchase/surrender composition, and failure-induced live rollback remain
explicit acceptance work; prior individual executor evidence remains separate.
