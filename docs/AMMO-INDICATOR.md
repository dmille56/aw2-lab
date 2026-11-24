# Low-ammo indicator on the board

The human client flashes an ammunition badge on a unit's tile when that unit is
low on ammo. This page records what the cartridge actually does, the rule the
client uses, and how the badge is exposed accessibly.

## What the cartridge does (measured, 2026-11-23)

Method: isolated headless mGBA on the verified supported cartridge (`aw2.gba`,
SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`), Bean Island
Versus with Andy vs. Max, one purchased Tank at tile (1,6). The Tank's ammo field
(bits 7..10 of the packed halfword at unit record `+4`) was set to 9, 8, 7, 6, 5,
4, 3, 2, 1, 0, then back to 9 and 0. For each value the client captured 120
consecutive frames (four 30-frame terrain-animation cycles) and recorded every
colour each pixel took during that window.

- **There is no on-tile ammo marker anywhere in the Versus battle view.** Comparing
  the 9-ammo window with the 0-ammo window, only 7 pixels of the 240x160 screen
  ever differed: `(193,148)`, `(194,148)`, `(196,148)`, `(197,148)`, `(193,149)`,
  `(194,149)`, `(195,149)`, all inside the bottom-right status panel. Those pixels
  toggle between the panel's green background, its grey frame, and the white
  digit glyphs: the printed ammunition number changes shape in a 5x2 glyph area
  (x=193..197, y=148..149) when ammo goes from 9 to 0.
- Nothing in the unit's own 16x16 tile, in the tile's terrain animation, or
  anywhere else on the map changed shape, colour set, or blink cadence between
  ammo 9 and ammo 0. The disassembly agrees: the status-panel routine at
  `0x08039F80` extracts bits 7..10 and draws digits, with `cmp r0, #9; bhi` used
  only to shift the glyph by 4 pixels when the value needs two digits.
- The pixels that do blink on the board (roughly 1,500-3,000 across a 120-frame
  window at any ammo value) are water, river, mountain, and factory animation. The
  count does not depend on ammo: 2,535 blinking pixels at ammo 9, 3,059 at ammo 1,
  and 2,665 on a repeat control at ammo 9.

So there is no native artwork to extract into the sprite pack, and no native pulse
frequency to copy. The badge is a symbolic, clearly labelled client convention.

## The rule the client uses

Implemented in `prototypes/client/web/ammo_indicator.ts`:

- Units whose verified catalog capacity is 0 (Infantry, Recon, APC, Lander,
  Transport Copter) never get a badge; their ammo is always 0.
- **Low** means strictly below half capacity: `ammo * 2 < ammo_capacity`. For a
  Tank (9) that is 4 and under; 5 and above is not flagged.
  This is Advance Wars: The Best Offense revision 63, which moved its low-ammo
  animation from "1 or fewer rounds" to "below half". It is a documented design
  choice, not observed AW2 behaviour, and is stated as such in the source.
- **Empty** primary ammunition is called out separately. When a unit still has an
  unlimited secondary weapon (its catalog `secondary_targets` is non-empty), the
  label says the primary ammunition is gone and only the secondary weapon remains.
  Artillery, Rockets, Missiles, Fighters, Bombers, Battle Copters, Battleships,
  Cruisers, and Submarines have no secondary targets, so they read as simply out of
  ammunition.
- Embarked passengers are never flagged: they are not on the board.
- Fog of war gates other armies. While fog is enabled, or its state is unobserved,
  the badge appears only for units in the viewer's own slot. When fog is verified
  off, every unit on the board is exposed and gets the badge. The inspector's
  ammo number is unchanged; only its low/empty emphasis is gated.

## Rendering and accessibility

`prototypes/client/web/AmmoIndicator.css` places a high-contrast badge in the tile's
top-right corner, away from the HP badge (bottom right), the cargo badge (left
middle), and capture/coordinate labels (bottom left). The badge shows a filled
`▮` glyph plus the remaining round count, and a hollow `▯` with `0` when empty; the
empty case also switches to a dashed border. It flashes with a 1.2 s
`steps(1, end)` opacity pulse.

- The glyph and number carry the meaning, so colour alone is not load-bearing.
- The tile's accessible name includes `low ammo, 4 of 9` or
  `out of ammunition, 0 of 9`, and the badge itself is `aria-hidden` so screen
  readers do not repeat it.
- The tile button carries `data-low-ammo="4/9"` for checks.
- `prefers-reduced-motion: reduce` disables the pulse and leaves the badge solid.

## Verification

- `prototypes/client/tests/ammo_indicator.test.ts`: thresholds, capacity-0 units,
  secondary-only empties, fog on/off/unknown, embarked units, inspector text.
- `prototypes/client/tests/components.test.tsx`: badge presence and glyph,
  accessible tile name, `data-low-ammo`, no badge at full ammo or for
  capacity-0 units, fog hiding an enemy badge while keeping the viewer's own.
- `prototypes/client/tests/browser/viewer.spec.js`: synthetic live-server render
  of badge, empty badge, fog gating, `animationName` flashing by default and
  `none` under reduced motion, and the inspector line.

Not yet verified: a side-by-side human comparison of the client badge against a
live match on the real cartridge (the cartridge has no equivalent marker to
compare against).
