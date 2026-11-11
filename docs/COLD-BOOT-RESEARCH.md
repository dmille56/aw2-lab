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

## Configurable Versus rules (2026-11-10)

On the Rules screen, the selector bytes begin at `0x03001698`; the next five
selector bytes are spaced by `0x60` bytes. Observed order is Fog, Weather,
Funds, Day, Capture, and CO Power. The default values are `(0, 0, 0, 0, 0, 0)`.
The configured choice sequence is guarded with an observed phase/subphase and a
RAM read after every Up/Down input.

The live non-default setup displayed Fog Off, Clear, Funds 2000, Day Off,
Capture 20, and Power Off. Funds required two Down inputs from 1000; the settled
first-turn funds matched 2,000 for each owned property. Capture 20 and Day Off
were visible in the Rules-screen screenshot. CO effects were Off at the first
playable boundary. The headless and windowed captures were visually identical
for the selected Rules screen.

The selector arithmetic used by automation is: weather Random/Clear/Rain/Snow
at indexes 0/1/2/3; income 1000–5000 in 500 steps; day Off or 5–99 (index 0 is
Off, then 5 upward by one); capture Off or 12–27 (index 0 is Off, then 12
upward by one); CO Powers On/Off at indexes 0/1. Fog remains Off.

## Multiplayer setup and Rules objects (2026-11-10)

CO/control focus alternates at indexes `2*(slot-1)` and `2*(slot-1)+1`.
External/computer controls occupy `0x02017C59..0x02017C5C` (1/2).
After confirming CO/control setup, three/four-player matches have a separate
team-assignment screen, with focus indexes 0 through player-count minus one.
Down cycles A–C or A–D; two-player setup skips this screen and retains A/B.
Every focus and selection transition is checked against the setup arrays.

Rules objects move in multiplayer setup. The observed four-player Fog selector
is at `0x03001758`, while Weather is at `0x03001938`. A constant offset for the
whole rule array is incorrect. Startup now locates the six selector objects in
`0x03001400..0x030023FF` using their object headers (`0x0858096C`,
`0x08580984`) and rule callback pointers: Fog/Power `0x08064739`, Weather
`0x08064775`, Funds `0x080647BD`, Day `0x0806486D`, Capture `0x08064919`.
Exactly two Fog/Power objects and one of each other rule object are required;
the shared callback's earlier/later objects are Fog/Power. Default values and
each subsequent change are verified. The old setup byte alone is insufficient
to distinguish all multiplayer setup screens. Final battle verification checks
all requested controls, CO IDs, teams, weather, map geometry, and opening income.

The full 133-map ROM scan also extends the supported graphical tile envelope
from 470 to 472. Tiles 471 and 472 map to encoded terrain `0x8A` and `0x8B`
(Yellow airports and ports). Thirteen new four-player maps contain one or both
IDs. Crop River's cells 731 and 825 use tile 471; the live lookup agreed with
the decompressed ROM. Validation still requires the exact ROM tile/terrain
mapping, valid owner bits and terrain classes, and bounded geometry.
