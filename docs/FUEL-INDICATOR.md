# Low-fuel indicator on the board

## Cartridge observation (2026-11-24)

An isolated headless run of the supported US revision-0 cartridge (SHA-256
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`) started
Bean Island Versus with Andy and Max and purchased a Tank at (1,6). Its fuel
field, record byte `+6` bits 0–6, was set to 70, 69, 35, 34, 1, 0, and 70;
the decoder confirmed each value. With the cursor moved away, each value was
observed for 120 consecutive frames. Comparing the set of colours at every
screen pixel against the first full-fuel window found **zero different pixels**
for every value, including the repeat full-fuel control. The observation covers
this Tank in this battle, not every unit or game mode. An earlier run with the
cursor on the Tank produced differences around the cursor and in the status
panel; those cursor differences varied with animation and do not establish a
fuel marker. No native glyph or cadence was established, so no cartridge art
was extracted.

SHA-256 hashes of the single PNG captured immediately before each window, in
fuel order 70, 69, 35, 34, 1, 0, 70 (images stay outside Git):

```text
f95defe56098a60671dbd4ef29a4ba68b12f8b525acf43bc85d566bb17807382
88184e59d973472d6b6cd4cc825413ce45b406f482947177be82d9f313dc57da
1f3451e0546dc4832e15e18c01b1a59044029a9c07d688d389d112c42f34c802
90a71a1f60ae9d1c682b1de1a9157b50dbf43b9ac558e4c485c422a04fa1e560
bfa3166e77dc68b69dd846721740413ee6b5a24506d2dc47fd19ff5b54833a61
2d97092984a0fd69b9095460ebb778f2f1119a9cf577b2b3f7ed1b093b414331
0f67940a366908395cbb39bd90cb6f85b61a25cca2ffc697823346b39786781a
```

These hashes identify individual screenshots, not the full 120-frame windows.
Further unit-type coverage and a human live-client review remain open.

## Client behavior

The symbolic `F` badge uses a **client convention**, not a verified cartridge
rule: fuel is low when `fuel * 2 < fuel_capacity`. Zero-capacity and unknown
unit profiles have no badge. Empty fuel is named separately; units whose shared
rule profile says they are destroyed at zero fuel receive a destruction-risk
warning. The indicator uses committed state, hides embarked units, and follows
the ammo badge's fog policy: when fog is on or unknown, only the viewer's army
gets a warning. It is exposed in the tile accessible name and inspector, and in
`data-low-fuel`. Reduced-motion settings leave the badge solid.

The component and browser tests cover thresholds, empty-fuel wording, fog,
embarkation, accessible names, refreshes, reduced motion and coexistence with
the ammo badge. Visual acceptance in a live match remains outstanding.
