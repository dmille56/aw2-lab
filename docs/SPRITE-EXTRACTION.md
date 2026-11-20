# Local sprite extraction proof

The redesign extraction proof was verified on 2026-11-15 with the checksum-verified
US revision-0 ROM (`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`).
It produces representative samples, not a complete client sprite pack.

Run from the project environment, choosing an output directory outside the
repository and Nix store:

```sh
PYTHONPATH=src python -m aw2_lab.sprite_extraction \
  --rom "$AW2_ROM_PATH" --output-dir /tmp/aw2-redesign-sprite-proof
AW2_RUN_SPRITE_ACCEPTANCE=1 PYTHONPATH=src pytest tests/test_sprite_extraction.py
```

The command verifies the ROM before creating output and reads it without modifying
it. Generated PNGs and `samples.json` remain external. Metadata includes ROM
identity, dimensions, and limitations; it contains no local ROM path. The opt-in
acceptance test checks all 30 outputs and verifies the source ROM is unchanged.
Default tests use synthetic compressed bytes, palettes, tile data, and PNG pixels;
no ROM is needed.

## Verified layout

All addresses below are ROM **file offsets**. GBA CPU ROM addresses add `0x08000000`.

| Content | Offset | Interpretation |
| --- | --- | --- |
| Stationary unit frames | `0x10BE60` | Three frames, each `0xD80` bytes; 27 sprites of four 8x8 4bpp tiles |
| Unit army palettes | `0x10E6E0` | Five 16-color BGR555 palettes, 32 bytes each |
| Army/unit lookup | `0x499608` | Five rows of 25 little-endian halfwords; index by unit type including zero |
| Compressed ground graphics | `0x0BD1EC` | BIOS type-`0x10` LZ77, producing `0x6000` bytes |
| Clear ground palette | `0x0BF8C4` | Eight 16-color palettes; banks 0–3 visible, 4–7 dimmed |
| Ground metatiles | `0x0BFBC4` | 1024 records of four little-endian GBA tilemap halfwords |
| Terrain/owner lookup | `0x0C1BC4` | 1024 bytes, existing decoder's terrain/ownership lookup |
| First animated terrain page | `0x0C1FC4` | `0x1000` bytes loaded at graphics offset `0x2000` |
| First second terrain page | `0x0C9FC4` | `0xC00` bytes loaded at graphics offset `0x4000` |
| City foreground | `0x0CFFC4 + 0x440` | Six tiles arranged as 16x24 pixels |
| Property palettes | `0x0D3EE4` | Neutral and army palettes, 32 bytes each |

A 4bpp tile stores its left pixel in the low nibble. Metatile halfwords carry a
10-bit tile index, horizontal/vertical flip flags, and a palette bank. Color zero
is transparent for unit/property foregrounds and opaque for the ground layer.
Colors expand from 5-bit channels using `value * 255 // 31`.

Stationary unit rendering follows routine `0x0802216C`: the first row uses tiles
1 and 0 with horizontal flip, followed by tiles 3 and 2 with horizontal flip.
The per-army lookup selects distinct Infantry/Mech silhouettes; other types share
silhouettes and use their army palette. Army IDs are ROM nation IDs, not arbitrary
match slot assignments. Future client integration must resolve that distinction.

City sampling follows the source selection in `0x0803F79C`. This source is also
used by the game's terrain information display. The complete pack still needs
verified HQ, base, port, airport, silo, and other feature mappings and composition.
Ground samples alone do not include property foregrounds.

## Evidence and limits

The extraction run produced plain, mountain, woods, and sea ground tiles;
Infantry, Tank, Fighter, and Battleship for all five army palettes; and a City
foreground for neutral plus all five armies. Visual inspection confirmed
recognizable silhouettes, army colors, and transparent backgrounds, including
comparison with existing emulator screenshots. All 12 decoder/PNG/extraction
checks passed with the live-ROM opt-in. This establishes representative extraction
feasibility, not complete sprite coverage or pixel-for-pixel board reproduction.

Offsets were located using the original-game disassembly in
[Eebit/aw2bhr, commit 63a2694](https://github.com/Eebit/aw2bhr/tree/63a26942a9a1249fe4e02c4c2ec0b3d2ee6b16cb)
and cross-checked against the local verified ROM. Relevant routines are
`0x08026190` (unit graphics), `0x080261A4` (unit lookup), `0x080261C8` (palettes),
`0x08021D64`/`0x08021DA0` (animated terrain pages), and `0x08023A4C` (metatiles).
The [Infinite COs modding source](https://github.com/XenesisXenon/AW2-InfiniteCOs/tree/5730d3dd58d82fc000bcc8449f245334fcc7d939)
provided an additional lead to the unit renderer. No downloaded artwork or
third-party implementation was added to the project.

No animation, weather selection, exact map edge composition, generated artwork
packaging, browser delivery, or client rendering is claimed by this proof.

## Complete static client pack

The next extraction layer covers the decoder's 19 supported unit types in all
five ROM army palettes (95 frames), and 18 supported terrain classes in neutral
plus five army palettes (108 frames). It uses representative ground tiles and
static property foregrounds. It does not reproduce per-map terrain connections.

```sh
PYTHONPATH=src python -m aw2_lab.sprite_pack \
  --rom "$AW2_ROM_PATH" --output-dir /tmp/aw2-redesign-sprite-pack
AW2_RUN_SPRITE_ACCEPTANCE=1 PYTHONPATH=src pytest tests/test_sprite_pack.py
```

The output consists of a content-addressed PNG atlas and an atomically replaced
`manifest.json`. The manifest identifies `aw2-client-sprites` version 1, the ROM
checksum, atlas checksum and dimensions, and regions with `x`, `y`, `width`, and
`height`. Unit keys are `unit_type:army_id` (army IDs 1–5); terrain keys are
`terrain_class:army_id` (neutral 0 and armies 1–5). Each unit occupies 16x16 pixels;
each terrain frame occupies 16x32, with ground at its bottom and foreground
anchored at the bottom. The manifest contains no local machine paths.

Every non-property terrain class is packed per graphical tile ID, not just per
class. Each variant frame composes the exact four native ground tiles, preserving
orientation, neighboring connections, palette indices, and flips, and is keyed
`terrain_class:graphical_tile_id` in the manifest's `terrain_variants` table. The
supported ROM contains 248 such IDs: 68 river, 52 sea, 40 road, 36 shoal, 19 wood,
11 plain, 10 pipe, 5 bridge, 4 mountain, 2 pipe seam, and 1 reef. Plains cells are
not flat: the tile ID they reference carries the tip of a mountain range that spills
out of the mountain cell below it, so class-only sprites cut mountain peaks in
half. Packs generated before `terrain_variants` remain compatible because clients
fall back to `terrain_class:owner_slot` when a variant is absent. Regenerate an
external pack to render each map's native mountain shapes, woods shapes, and road
bends, straights, and junctions.

Base, Airport, Port, City, Missile Silo, Spent Silo, and HQ artwork is selected by
army rather than by map cell, so those seven classes stay keyed by owner slot and
cannot be packed per cell without an army-specific overlay.

Live check on 2026-11-18: a Bean Island match rendered all 240 tiles from the atlas,
212 through a per-cell variant and 28 through an army-selected representative, with
no tile using a region other than the one its state data selects. Comparing the 150
tiles inside the emulator's 240x160 screen with the atlas region the client used, the
plain cell at (3,2) improved from an 8204-point RGB difference against the flat
representative to 497 points with its own `1:67` variant — the same tolerance as the
mountain cells beside it. Tiles underneath unit sprites or the emulator's status
panel still differ because those overlays are drawn by the emulator rather than by
the ground region.

Full-catalog audit (2026-11-19): the verified ROM's original map table at
`0x005C77A0 + rom_map_id * 0x5C` points at an LZ77 stream whose payload starts with
the width and height bytes and continues with `width * height` little-endian graphical tile
IDs. Decoding all 133 catalog maps (64,027 cells) and resolving each
cell through the client's lookup found no cell without artwork. Only classes 1-8,
10-17, and 19 occur in Versus maps, so class 9 and the campaign-only classes 20-31 never
appear. Class 18, the spent silo, exists only after a unit launches, so the static sweep
cannot reach it; `--spent-silo` fires one during the audit and measures the cell it leaves
behind. The complete pipe and seam
set is 258, 259, 288, 289, 320, 321, 322, 323, 352, 353 (pipe) and 354, 355 (seam),
all of which are packed. Six maps contain pipe or seam cells - Missile Plains (60),
Pipe Maze (88), The Trident (35), Wyrms Eye (16), Big Daddy (12), and Nest Egg (12) -
and `aw2-lab play` now launches three- and four-player maps, so Pipe Maze (map ID 104,
22x22) and Big Daddy were compared cell by cell against the emulator: 96 of the 100
pipe and seam cells across those two maps matched their exact atlas region within one
unit per channel, and the four outliers sit under unit sprites or the status panel. See
[Milestone 4](MILESTONE-4.org) for the method and the numbers. 43 distinct river IDs occur
across the catalog, all
within the 68 packed river variants: a Lost River match matched 20 of its 27 in-window
river cells within 1,500 points (median 254, minimum 108), the outliers being cells
covered by unit sprites or the emulator status panel. Follow-up work for the parts this
audit cannot reach - spent silos, animated terrain frames, per-cell property art, unit
and portrait comparison, and the four occluded pipe cells - is tracked as TODO items in
[Milestone 4](MILESTONE-4.org).

Additional property sources, relative to `0x0CFFC4`, are Base `+0x80` (four tiles),
Airport `+0x140`, Port `+0x240`, City `+0x440`, and Missile Silo `+0xA40` (six tiles
each), and Spent Silo `+0xB00` (four tiles). HQ sources are at
`0x0D16C4 + (army_id - 1) * 0x100` (eight tiles); neutral uses the first HQ shape
with the neutral palette. These regions were checked against the original source
selection routine and visually inspected in the generated atlas. Terrain ground
regions use the first graphical tile matching each class in the verified lookup,
except Sea: graphical tile 42 is open water observed at Bean Island (0,0).
Tile 8 is a shoreline/island transition and is unsuitable for a repeated sea
fill. The 2026-11-16 full-board live preview caught this selection issue.
Regenerate existing external packs to obtain the corrected sea region.

Rendered regions were compared with mGBA for a live Bean Island match on
2026-11-18: all 240 client tiles used the atlas region selected by their state
tile, and the plain cell at (3,2) changed from a flat green square to the mountain
peak tip that the emulator draws above the mountain at (3,3). Cells under unit
sprites or the emulator's status panel still differ because the client does not yet
composite those overlays into the ground region.

On 2026-11-15, all three pack checks passed with the live-ROM opt-in: coverage
matches the current observation/rules contract, every region is within the atlas,
the PNG hash matches the manifest, repeated extraction produces the same output,
and the input ROM hash stays unchanged. Visual inspection covered the full atlas,
including all 19 silhouettes and property families. Browser/native delivery and
rendering remain the next checklist item. Unsupported campaign-only terrain
classes use the client's symbolic fallback rather than a guessed mapping.

## Auditing the pack against mGBA

`aw2-lab sprite-audit` compares the packed atlas with what mGBA actually draws, so a
suspected artwork gap becomes a list of cells with verdicts instead of an ad hoc script.
The ground only renders while a game is running, so the audit boots its own mGBA into the
map it is measuring:

```sh
aw2-lab sprite-audit --map pipe_maze --rom ~/Downloads/aw2/aw2.gba \
  --save-profile ~/Downloads/aw2/game-saves/aw2-everything-unlocked.sav \
  --pack ~/.local/share/aw2-lab/sprites \
  --output /tmp/pipe-maze/sprite-audit.json \
  --screenshots-dir /tmp/pipe-maze/audit-shots \
  --tiles-dir /tmp/pipe-maze/audit-tiles \
  --animation-frames 60 \
  --spent-silo
```

It never borrows the emulator that is serving a match. The sweep presses D-pad buttons and
advances hundreds of frames, which on a live match would push the emulator past the frame
boundary the controller committed and make the next gameplay command fail with
`RECOVERY_REQUIRED`. `--attach-live <bridge-port>` (or `--run-dir` from `aw2-lab play`) is
the opt-in escape hatch for an emulator that is already running: the audit snapshots its
state and restores it when it finishes, and restoring a state buffer puts the emulator back
on the exact frame it was on (checked: frame 100, advance 50, load the buffer, frame 100
again), so the controller's committed boundary is intact. The match still has to stay idle
for the whole sweep, and the audit gives up with an error if it cannot put that frame back.
With `--run-dir`, the audit verifies the bridge instance recorded by `aw2-lab play`
on the connection for each request, including restoration. SIGTERM cancels the sweep
and waits for restoration before the audit exits. Older run directories require an
explicit `--attach-live` port for a verified running match.
`--emulator-mode windowed` shows the sweep in an mGBA window instead of headless.
An isolated audit starts with a blank save unless you pass `--save-profile`. A cartridge
save beside the ROM is ignored.

Two guards keep the isolated path honest. Before launching, the audit checks whether the
bridge port is already listening and refuses to start a second mGBA on an emulator it does
own, naming the port and the ways out. And the launcher exports a per-process nonce
(`AW2_BRIDGE_INSTANCE`) that its Lua bridge echoes back in the `connect` handshake, so a
stale emulator answering on the same port cannot be mistaken for the one the audit started.
The audit also refuses to measure an emulator that is not in a validated battle turn, since
without a live map there is nothing to compare against the pack.

The audit works in four steps:

1. **Sweep the camera over the whole map.** The battle camera pans one cell per D-pad
   press once the cursor reaches the viewport edge, so a cursor walk that visits every
   cell drags the 15x10 window over every viewport offset. `sweep_moves()` generates that
   walk and `tests/test_sprite_audit.py` proves it covers all `width * height` cells for
   all 133 catalog maps. `--max-screenshots` caps the sweep (default 1500, enough for the
   largest catalog map); the animation probes are measured in addition to that cap.
2. **Find which cells are on screen.** The audit compares sampled pixel signatures of
   candidate 240×160 windows against the packed art. It keeps the offset with the most
   exact signature matches, breaking ties on total signature distance. Once the view
   is known, cursor movement predicts the next offset and resolves ties. The audit
   considers only windows that could contain the observed cursor.
   If the tie remains, the audit reports an ambiguous camera position.
3. **Compare each cell with its own region.** Every screenshot is measured, not just the
   first one per offset, because the cursor and the status panel move without scrolling the
   view: a cell keeps the lowest difference across clear views that contain it. If the
   cursor or HUD covers the cell in every sampled view, the report marks it as occluded
   and skips nearest-artwork scoring. A cell passes when its packed region paints at
   least one pixel and the RGB difference is within
   900 points. Cells are never blamed for pixels the pack leaves transparent: plains have
   no mountain peak, and an army's HQ region has no annex for another army. A cell the pack
   has no region for at all is still measured and reported, so an incomplete pack cannot
   hide its own gaps as "never in view".
4. **Explain the failures.** For each mismatch the audit measures the closest *other*
   packed region, scoring every candidate fully (a candidate that exceeds the current best
   is abandoned early, so its unfinished score can never win). A near match means the
   client picked the wrong region; a far one means the artwork is genuinely absent. It also
   flags cells with a unit sprite or the status panel on them, cells whose visible ground
   comes from a 16x32 mountain frame anchored on the cell below, and terrain whose pixels
   change between two screenshots `--animation-frames` apart. Animation probes exclude
   cells covered by the cursor, HUD, units, and property effects. At least one sample must
   match the packed ground before a change counts as terrain animation.
   `--tiles-dir` writes one PNG per
   mismatch with the atlas composite on the left and the emulator's pixels on the right.

Pipe Maze audit on 2026-11-19 (isolated audit emulator, day 1, 468 screenshots, 98 viewport
offsets, all 484 cells in view): 459 cells matched their packed region and 25 did not. Of
the 25, 21 sit on nine terrain regions the animation probe saw changing between screenshots
60 frames apart (`1:1`, `1:33`, `2:24`, `4:134`, `5:97`, `5:164`, `14:454`, `14:469`,
`17:384`), 3 are army-keyed property cells (`8:458` at 20,2 = 20,636 points, `8:463` at
1,2 = 12,733 points, `8:468` at 20,19 = 10,712 points) where the pack's single per-army
region is not the tile the game selected, and 1 (`5:128` at cell 20,18, 25,879 points) has
no explanation yet. Matched cells land at exactly 0 points, so the packed terrain pixels
match what mGBA draws pixel for pixel. Every pipe (15) and seam (16) cell on Pipe Maze
matched, which closes the four pipe cells left unverified by the earlier manual checks:
Pipe Maze 9,0, 9,1, and 9,14 now match their packed regions, and Big Daddy 9,5 turns out to
be animated pipe art rather than missing artwork.

Big Daddy audit the same day (isolated audit emulator, 284 screenshots, 30 viewport
offsets, all 285 cells in view): 229 matched and 56 did not - 36 cells are covered by a unit
sprite or the status panel, 14 are animated terrain (23 regions cycle), 2 are army-keyed
property art, and 4 (`1:33`, `3:35`, `4:134`, `15:322`) are terrain regions the probe did
not catch cycling. The largest difference among matched cells there was 790 points, which
is the panel/edge overlap the 900-point tolerance allows.

Spent silo, live (2026-11-19): `--spent-silo` plays into the map before the sweep. It
produces infantry on a base next to a missile silo, walks the unit onto the silo, launches,
ends turns until the firing army can move again, and steps the unit two cells away so the
ground the launch leaves behind is unobstructed. On Pipe Maze army 1 fired the silo at
(1,20), which changed from `17:384` to `18:416` with owner slot 0. The sweep measured that
cell in 44 of the 104 viewport offsets and kept the cleanest view: the pack's `terrain/18:0`
region, all 256 pixels opaque, differs from what mGBA drew by 0 points, with all 256 pixels
identical. The nearest other class-18 region in the pack is `18:2` at 26,717 points, so the
army-keyed lookup is doing real work rather than matching any spent-silo tile, and the
class-18 bucket reports 1 cell, 1 matched, 0 mismatched. The client's symbolic terrain
fallback is never reached. The pack carries six spent-silo regions (`18:0`-`18:5`, four
source tiles each at `0x0CFFC4 + 0xB00`); the silo's cell keeps owner slot 0 after the
launch, so a spent silo renders the neutral artwork, which is what the emulator draws.

Limits: the audit measures the ground only, so unit sprites, HP bars, and the status panel
are ignored rather than compared; animation sampling covers only the two views probed; and
animated frames beyond frame 0 are still not packed. `--spent-silo` plays real turns, so it
needs a map where a silo touches a base the active army owns (Pipe Maze) and, with
`--attach-live`, it changes the running match.

## Prototype delivery and rendering


Configure the prototype server with an already extracted pack:

```sh
PYTHONPATH=src python prototypes/client/serve.py \
  --sprite-pack /tmp/aw2-redesign-sprite-pack
```

`AW2_CLIENT_SPRITES` is the equivalent environment setting. Vite development
proxies `/client-sprites` to the API, and the shared Tauri frontend uses its
configured loopback API base. The server validates the manifest version, ROM
identity, region bounds, atlas dimensions, and PNG checksum at startup. Only the
validated manifest and content-addressed PNG are served, from memory; the external
directory and its other files are never mounted. No configured pack returns JSON
`null` so the client quietly keeps its symbolic board.

The client loads and decodes the atlas before switching artwork. Missing,
unsupported, or failed artwork leaves symbolic tiles and units usable. Individual
unmapped entries also use symbols. Tile accessible names, board focus, keyboard
inspection, action overlays, and the exact-health inspector remain available.
Visible unit badges use ceil(internal health / 10); used sprites are dimmed and
retain a check mark. Owned units have underlined health badges. The prototype
uses its existing player-slot color convention (1–4) to select army palettes;
it does not claim a separately decoded native faction/skin identity.

The initial browser preview used the authentic extracted atlas with synthetic
match observations. This verifies artwork loading/rendering and interaction,
not new live emulator gameplay or native Tauri visual acceptance. ROM-independent
browser checks use original synthetic SVG artwork via mocked asset responses;
server tests use original synthetic PNG pixels. No game artwork enters fixtures
or visual baselines. The fallback-board visual baseline remains ROM-independent.
