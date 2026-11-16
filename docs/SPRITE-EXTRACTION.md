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
