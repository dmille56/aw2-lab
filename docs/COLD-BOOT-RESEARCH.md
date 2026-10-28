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

To run the captured fresh-save path automatically and record its recognized
screen boundaries, add `--automate-fixed-match`:

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode headless --save-mode fresh \
  --automate-fixed-match --full-ram \
  --output /tmp/aw2-coldboot-automated-headless
```

Use `--mode windowed` to watch the same sequence. The automatic path is only
enabled for fresh saves until existing-save behavior is recorded. It stops with
diagnostics if the selected map, initial teams/COs, lifecycle phase, or first
playable state differ from the supported configuration. The Rules screenshot is
saved for visual checking; Fog Off currently has no verified runtime RAM
postcondition.

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
fresh-save windowed path. Existing-save behavior and automated headless replay
remain unverified.
