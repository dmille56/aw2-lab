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

## Provision a save copy for a locked Versus map

Unlocking remains a player action in AW2. Use this recorder to do it in a
dedicated copy: the ROM and source `.sav` are copied under the output directory,
and mGBA writes only to that copy. In the windowed recorder, navigate the game's
own modes and Battle Maps, complete any required progress or purchase, save in
game, and quit. The output `save-data/aw2.sav` is kept alongside
`save-data/aw2.gba`; `manifest.json` records its final hash and whether the
source save stayed unchanged. The original save is never used as mGBA's writable
save file.

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode windowed --save-mode existing \
  --existing-save /absolute/path/to/aw2.sav \
  --output /tmp/aw2-map-save-provision
```

The recorder accepts either an mGBA `.sav` or the supplied GameShark SP `.sps`.
For `.sps`, it validates the SharkPort container and embedded ROM identity, then
extracts the 64 KiB SRAM payload into the isolated `.sav` copy. The original
container remains untouched. For example, to prepare from the all-unlocked
profile:

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /absolute/path/to/aw2.gba --mode windowed --save-mode existing \
  --existing-save /absolute/path/to/advance-wars-2-black-hole-rising.5719.sps \
  --output /tmp/aw2-all-unlocked-profile
```

Quit the recorder after it opens. The pair in `save-data` is a standalone
profile. Point the local runtime at
`/tmp/aw2-all-unlocked-profile/save-data/aw2.gba` to use its companion save; keep
the output directory intact. To verify a requested map before creating a normal
match, use the automated path in a separate output directory:

```sh
nix develop -c python -m aw2_lab record-cold-boot \
  --rom /tmp/aw2-map-save-provision/save-data/aw2.gba \
  --mode headless --save-mode existing \
  --existing-save /tmp/aw2-map-save-provision/save-data/aw2.sav \
  --automate-fixed-match --map-id hourglass_isle \
  --output /tmp/aw2-map-save-verify
```

The verifier reports the requested map, last reached navigation checkpoints,
and a concrete failure reason in `automation-result.json`; successful
verification records the settled playable map ID. A locked map remains a
failure and does not change the source profile. This flow does not patch SRAM
or earn game progress automatically.

### Cheat-code investigation

An initial mGBA test used the published CodeBreaker “Have All Battle Maps”
code (`42028040 FFFF / 0000000D 0002`) with its enable code on a disposable ROM
copy. It changed bytes at `0x02028040`, but Hourglass Isle remained unavailable
in the Versus selector. This code therefore does not solve the Versus-map
provisioning case in our setup. A separate published “All Vs Maps” code is
Action Replay MAX encrypted (`E8999409 0322EA64`); it has not been validated or
converted to a format accepted by our mGBA build. The next useful experiment is
to convert that exact code (or identify its underlying save flag), then repeat
the unlock and persistence checks on a disposable save. Do not apply unverified
codes to a user's source save.

A second source gives a direct Versus unlock write at `0x02028046` (`FFFF`)
([GameHacking.org](https://gamehacking.org/game/3803)). Loading that write as a
startup cheat also failed to unlock Hourglass Isle, even though EWRAM later
showed the value. A timing probe on a disposable ROM copy wrote the same two
bytes through the bridge at the `hourglass-isle-selected` checkpoint, after the
map menu had opened and immediately before confirming it. That run passed map
confirmation and reached Hourglass Isle (map ID 38, 16x24, frame 7041). It is
promising evidence that the write needs to happen after the game has initialized
its map selector. That first attempt used the full CO roster indices and failed
CO identity verification. A follow-up used fresh-save roster indices Andy=0
and Max=1, while keeping all playable-state assertions enabled; it verified
Hourglass Isle through the first player turn at frame 6948 with battle CO IDs
`[1, 2]`. This confirms a complete experimental match path when the write
happens after the map selector initializes and the fresh roster is indexed
correctly. The isolated recorder now exposes this path with
`--experimental-late-versus-unlock`, restricted to a fresh save, Hourglass Isle,
and Andy vs Max; it reads the written flag back before confirming the map and
records automation failure progress. Normal startup and match provisioning do
not use this write. The follow-up live check saved the battle through AW2's
in-battle Save command. A fresh boot from that saved copy loaded Hourglass Isle
without the late write in both frontends, showing that this specific unlock
survives the game save and restart. The resumed profile then hit a CO identity
mismatch during first-turn verification; the map itself had already loaded in
Versus setup. This evidence accepts persistence only for this tested map/save
flow, not other save-dependent maps or partial unlock states.

To keep the windowed probe open for AW2's in-battle save, add
`--continue-after-automation` to the command in HTTP-API.md. At the recorder
prompt, enter `select 1`, then `down 1` followed by `neutral 8` three times to
highlight Save, then `a 1`, `neutral 120`, `a 1`, and `neutral 120` to confirm
the default Yes choice and wait for “Save complete!”. Use only the disposable
recorder save; the save menu writes battle progress to its isolated SRAM copy.

### CO unlock status

The [published “All COs Unlocked” GameShark Advance code](https://gamehacking.org/game/3803)
is `81D67E78 B20B1BE0`; the same source lists a “Must Be On” code for the
supported US ROM. The CodeBreaker write `0x0202805A = 0xFFFF` changes the EWRAM
save block but does not expand the fresh-save selector beyond its 16 entries.
Loading the published GameShark code through mGBA's cheat file did not change
the CO data in our probe. The supplied
`all-unlocked-saves/advance-wars-2-black-hole-rising.5719.sps` is a SharkPort
export whose 64 KiB payload matches `~/Downloads/aw2/aw2.sav` exactly (SHA-256
`f596b04b096de3a3b89615cf0ea2c3b6d2904bee26ff7b84fcbd0215e483e42a`). The
`gameshark-all-unlock/` directory was empty during this check. On an isolated
ROM/save copy, the imported profile passed complete playable-state verification
on Pipe Maze (map ID 104, 22x22) with Nell, Hachi, Sturm, and Hawke (battle CO
IDs 0, 15, 10, and 14) at frame 8450. It also passed with Hourglass Isle, Nell,
and Sturm at frame 7073. Use this profile for runs that need all maps and
campaign-locked COs. Generating that profile from a fresh save with cheat codes
remains unverified.

### Fresh-save unlock generation probe (2026-11-11)

The supplied profile was compared with a new, isolated fresh-save boot at the
same Versus/Teams boundary. At `0x02028030`, the fresh session read `00 00` and
the all-unlocked profile read `7f 01`. Other differences appeared at
`0x02028046`, `0x0202804b..4c`, `0x0202804f`, `0x02028052..53`, and
`0x0202805a..76`. These are observations only; copying the full observed block
`0x02028030..77` into fresh-session EWRAM did not expose the campaign-locked COs.

Additional disposable tests tried the published CodeBreaker repeat-write
codes for all COs (`4202C630 0101 0000000E 0002`) and maps
(`4202C6B0 0101 00000030 0002`) both as direct RAM writes at menu checkpoints
and through mGBA's continuously applied cheat file. Hourglass Isle remained
locked. A late write of `0xFFFF` at `0x02028046` still loaded the map as in the
earlier timing probe, but writing `0xFFFF` at `0x0202805A`, the published
repeat-write CO array, campaign-completion byte `0x02028030 = 0x77`, or the
observed all-unlocked profile block did not extend the fresh CO selector past
its first 16 entries. Attempts to select Sturm stopped at the fresh roster's
last available entry. These codes and writes therefore do not generate an
all-unlocked persistent save in this mGBA/US-ROM setup.

All experiments used ROM copies and temporary emulator RAM under `/tmp`; the
source `.sps` and `.sav` were read-only and remain unchanged. No save was
written or persisted by the failed fresh-save probes. The exact unlock fields
and a safe way to generate a persistent all-unlocked save from blank SRAM
remain unresolved. For working sessions, seed the isolated runtime from the
verified GameShark `.sps` profile described above.

To run the fixed-match path automatically and record its recognized screen
boundaries, add `--automate-fixed-match`. Fresh saves use `--save-mode fresh`;
existing saves must also specify a source `.sav` or GameShark SP `.sps` file,
which is copied or converted into the isolated output directory before mGBA
starts:

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
