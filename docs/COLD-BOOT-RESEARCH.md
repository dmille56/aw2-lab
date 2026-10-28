# Cold-boot trace capture

`aw2-lab record-cold-boot` records a manual controller trace for the supported
US revision 0 ROM. It launches mGBA with a private configuration, save path, and
XDG data/cache directories. An existing save is copied into that isolated
directory; the original file is never opened by mGBA. Evidence must be written
outside the checkout and `/nix/store`.

Build the pinned emulator frontends first. Do the discovery runs in windowed
mode so you can see and follow the game. Use a distinct, new output directory
for each save condition:

```sh
nix build .#mgba
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode windowed --save-mode fresh \
  --full-ram --output /tmp/aw2-coldboot-windowed-fresh
```

Repeat with an existing `.sav` file to capture the Continue path. The recorder
copies it before launching the emulator:

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode windowed --save-mode existing \
  --existing-save /absolute/path/to/aw2.sav --full-ram \
  --output /tmp/aw2-coldboot-windowed-existing
```

Windowed mode requires a working display. Stop any other AW2 Lab/mGBA process
using the bridge port (`127.0.0.1:43128`) first. Headless verification should
replay the recorded input trace after the navigation path is implemented; do
not try to discover the menu path headlessly.

At the prompt, enter one or more button names joined with `+`, followed by the
number of frames to hold them. For example:

```text
cold-boot> neutral 99
cold-boot> start 1
cold-boot> neutral 30
cold-boot> down+a 1
cold-boot> capture versus-selected
cold-boot> quit
```

Valid buttons are `a`, `b`, `select`, `start`, `up`, `down`, `left`, `right`,
`l`, and `r`; frame counts range from 1 to 600. The tool captures an initial
observation and another after every input or `capture LABEL` command. Each step
contains a PNG, JSON metadata with frame/input/lifecycle signals and researched
setup bytes, and (with `--full-ram`) a binary concatenation of EWRAM and IWRAM
with its hash and memory layout. `trace.jsonl` records sequence and emulator
build identity. Emulation remains paused between explicit bridge inputs.

For each run, continue through the actual title/save path and the fixed Versus
setup: Bean Island, Andy/Max in Red/Blue slots 1/2, separate teams, standard
rules, fog disabled. Record the button and frame count for every transition;
use `capture LABEL` at each visible screen boundary and after the battle settles.
Do not try to force the same button sequence across fresh-save and existing-save
runs. Keep each output directory intact so the traces can be compared across
frontends and paths.

The manual trace remains the source evidence for the automated cold-boot
sequence. Without `--automate-fixed-match`, the recorder does not navigate menus
or claim that a particular setup is correct.

To run the fixed-match path automatically and record its recognized screen
boundaries, add `--automate-fixed-match`. Fresh saves use `--save-mode fresh`;
existing saves must also specify the source `.sav` file, which is copied into
the isolated output directory before mGBA starts:

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode headless --save-mode fresh \
  --automate-fixed-match --full-ram \
  --output /tmp/aw2-coldboot-automated-headless
```

For an existing save, use `--save-mode existing --existing-save
/absolute/path/to/aw2.sav` and choose a new output directory.

Use `--mode windowed` to watch the same sequence. Mode and Continue/New menus
are navigated using verified selector signatures rather than a fixed starting
cursor. If the existing save presents an overwrite confirmation, automation
confirms it only after recognizing the prompt and its Yes selection; this
affects only the isolated save copy. It stops with diagnostics if the selected
map, team setup, lifecycle phase, or first playable state differ from the
supported configuration. In the recognized Rules screen, IWRAM byte
`0x03001698` is checked as `0` with the default Fog ON and `1` after Down
selects Fog OFF. Manual fresh/existing traces plus automated fresh headless and
existing headless/windowed runs agree with the screenshots. Automation waits
for the Rules screen to render and stops if either value differs.

## Fresh-save windowed trace (2026-10-28)

The completed run is preserved outside Git at
`/tmp/aw2-coldboot-windowed-fresh-retry`. It used the supported US revision 0
ROM and windowed mGBA build SHA-256
`46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The trace contains 83 captures from initial boot through frame 3141, where the
lifecycle recognizes `battle_player_turn`.

The title screen displayed “Press Start,” but a one-frame Start input did not
leave it; a one-frame A input did. The observed route was: wait for title, A to
open Select Mode, Down to highlight Versus, A to open its New choice, A to
start a new Versus battle, A to confirm the default first Classic map (Bean
Island), navigate the Teams choices with Left/Up/Left/Left/Left, A to open
Rules, Down to change Fog from ON to OFF, then A to begin battle entry. Neutral
frames were used between taps for screen transitions. The trace's recorded
actions and screenshots are authoritative for this run; do not substitute the
older prepared-checkpoint Start input for the fresh-title A input.

The final coherent RAM capture confirms map ID 1 at 16 x 15, active player
slots 1 and 2 with CO IDs 1 (Andy) and 2 (Max), team IDs 0 and 1, day 1, clear
weather, and player 1's turn. The Rules screenshot shows Fog OFF, Weather
Random, Funds 1000, Turn Off, Capture Off, and Power ON. This establishes the
fresh-save windowed path. The fresh-save headless automation is also recorded
above.

## Existing-save windowed trace (2026-10-28)

The completed run is preserved outside Git at
`/tmp/aw2-coldboot-windowed-existing`. It used the same ROM and windowed mGBA
build as the fresh-save run. The trace contains 80 captures through frame 3327,
where the lifecycle recognizes `battle_player_turn`.

The main-menu cursor can open on the most recently played mode, so it is not
safe to assume Campaign is selected. In this run, Versus had a saved battle:
selecting Versus opened a `Continue`/`New` choice. Choosing `New` then opened a
separate confirmation that the saved game would be overwritten. After that
confirmation, the trace followed the same Bean Island, CO/team, and rules setup
path as the fresh-save run.

The automatic path completed with the existing save in both modes. The
windowed replay presented Continue/New and the overwrite confirmation; the
headless replay went directly to New with the same source save. Both reached
the first player turn with the supported configuration verified. These runs
are preserved at `/tmp/aw2-coldboot-fog-existing-windowed` and
`/tmp/aw2-coldboot-fog-existing-headless`. The fresh-save headless run is at
`/tmp/aw2-coldboot-fog-fresh-headless`. Automation supports either observed
branch and confirms an overwrite only for the recognized prompt inside its
isolated copy. The different frontend paths remain a research note.
