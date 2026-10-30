# AW2 unit and terrain rules

This reference and `aw2_rules_data.py` map the supported US revision-0 ROM,
`ef3cc89273f9df88020f07751ea6306b25c39df01893822fe431550eedf9b134`.
The catalog records all 19 supported unit types, all 32 terrain-table indices,
seven movement types, and movement/range/table selections for all 19 COs in
inactive, Power, and Super states. Values are ROM-audited; representative live
checks are recorded below. This does not establish every weather, terrain,
weapon, and CO combination through live play.

Sources: [StrategyWiki units and terrain charts](https://strategywiki.org/wiki/Advance_Wars_2:_Black_Hole_Rising/Units),
[Nintendo unit guide](https://www.guiasnintendo.com/1_GAMEBOY_ADVANCE/AdvanceWars2/advancewars2_SP/unidades.html),
[original unit-ID definitions](https://github.com/XenesisXenon/AW2-InfiniteCOs/blob/master/common/definitions_unit.asm),
and [terrain class names](https://github.com/XenesisXenon/AW2-InfiniteCOs/tree/master/datatables/terrainclassinfo).
The modding references corroborate names/IDs only; numeric rules were read from
the original supported ROM, not a modified game. Source discrepancies are resolved
against that ROM. See [the existing CO reference](AW2-CO-REFERENCE.org) for effects
outside movement and range.

## Unit table

Ammo is main-weapon capacity. Zero means either an unlimited secondary weapon
or an unarmed transport; consult the weapon matrix. `—` range means unarmed.
Movement is the baseline allowance before terrain costs or CO adjustments.

| ID | Unit | Move type | Move | Fuel | Ammo | Range | Vision | Cost |
|---:|---|---|---:|---:|---:|---|---:|---:|
| 1 | Infantry | Foot | 3 | 99 | 0 | 1 | 2 | 1000 |
| 2 | Mech | Mech | 2 | 70 | 3 | 1 | 2 | 3000 |
| 3 | Medium Tank | Treads | 5 | 50 | 8 | 1 | 1 | 16000 |
| 5 | Tank | Treads | 6 | 70 | 9 | 1 | 3 | 7000 |
| 6 | Recon | Wheels | 8 | 80 | 0 | 1 | 5 | 4000 |
| 7 | APC | Treads | 6 | 70 | 0 | — | 1 | 5000 |
| 8 | Neotank | Treads | 6 | 99 | 9 | 1 | 1 | 22000 |
| 10 | Artillery | Treads | 5 | 50 | 9 | 2–3 | 1 | 6000 |
| 11 | Rockets | Wheels | 5 | 50 | 6 | 3–5 | 1 | 15000 |
| 14 | Anti-Air | Treads | 6 | 60 | 9 | 1 | 2 | 8000 |
| 15 | Missiles | Wheels | 4 | 50 | 6 | 3–5 | 5 | 12000 |
| 16 | Fighter | Air | 9 | 99 | 9 | 1 | 2 | 20000 |
| 17 | Bomber | Air | 7 | 99 | 9 | 1 | 2 | 22000 |
| 19 | Battle Copter | Air | 6 | 99 | 6 | 1 | 3 | 9000 |
| 20 | Transport Copter | Air | 6 | 99 | 0 | — | 2 | 5000 |
| 21 | Battleship | Ship | 5 | 99 | 9 | 2–6 | 2 | 28000 |
| 22 | Cruiser | Ship | 6 | 99 | 9 | 1 | 3 | 18000 |
| 23 | Lander | Lander | 6 | 99 | 0 | — | 1 | 12000 |
| 24 | Submarine | Ship | 5 | 60 | 6 | 1 | 5 | 20000 |

The earlier baseline profiles used incorrect IDs for Medium Tank, Recon, Neotank,
Artillery, Rockets, Anti-Air, Missiles, Battleship, Lander, and Submarine. This
catalog corrects those assignments. IDs 4, 9, 12, 13, and 18 are unused unit slots.
Combat target column 25 is a submerged Submarine, not an additional supported
logical unit type. Its status/visibility must still be checked by AW2.

## Terrain and movement

Columns follow the ROM movement-type IDs: Foot 0, Mech 1, Treads 2, Wheels 3,
Air 4, Ship 5, Lander 6. A dash is impassable. Costs apply to each entered tile;
the starting tile costs nothing. A route containing any impassable tile has no
valid cost. Pipes and seams block air as well as ground and naval movement.

The decoder currently accepts terrain classes 1–8 and 10–19. The catalog also
records Lab (20), Campaign structures (21–30), and empty/unused entries (0, 9, 31).
Their static table entries do not expand live decoder support. Campaign structure
orientation names are corroborated by the modding reference; individual Campaign
structures have not all been restored and named from screenshots in this project.

### Clear

| ID | Terrain | Foot | Mech | Treads | Wheels | Air | Ship | Lander |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | Empty | — | — | — | — | — | — | — |
| 1 | Plain | 1 | 1 | 1 | 2 | 1 | — | — |
| 2 | River | 2 | 1 | — | — | 1 | — | — |
| 3 | Mountain | 2 | 1 | — | — | 1 | — | — |
| 4 | Wood | 1 | 1 | 2 | 3 | 1 | — | — |
| 5 | Road | 1 | 1 | 1 | 1 | 1 | — | — |
| 6 | City | 1 | 1 | 1 | 1 | 1 | — | — |
| 7 | Sea | — | — | — | — | 1 | 1 | 1 |
| 8 | HQ | 1 | 1 | 1 | 1 | 1 | — | — |
| 9 | Unused | — | — | — | — | — | — | — |
| 10 | Airport | 1 | 1 | 1 | 1 | 1 | — | — |
| 11 | Port | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 12 | Bridge | 1 | 1 | 1 | 1 | 1 | — | — |
| 13 | Shoal | 1 | 1 | 1 | 1 | 1 | — | 1 |
| 14 | Base | 1 | 1 | 1 | 1 | 1 | — | — |
| 15 | Pipe | — | — | — | — | — | — | — |
| 16 | Pipe Seam | — | — | — | — | — | — | — |
| 17 | Missile Silo | 1 | 1 | 1 | 1 | 1 | — | — |
| 18 | Spent Silo | 1 | 1 | 1 | 1 | 1 | — | — |
| 19 | Reef | — | — | — | — | 1 | 2 | 2 |
| 20 | Lab | 1 | 1 | 1 | 1 | 1 | — | — |
| 21 | Minicannon South | — | — | — | — | — | — | — |
| 22 | Minicannon North | — | — | — | — | — | — | — |
| 23 | Minicannon West | — | — | — | — | — | — | — |
| 24 | Minicannon East | — | — | — | — | — | — | — |
| 25 | Laser | — | — | — | — | — | — | — |
| 26 | Black Cannon South | — | — | — | — | — | — | — |
| 27 | Black Cannon North | — | — | — | — | — | — | — |
| 28 | Volcano | — | — | — | — | — | — | — |
| 29 | Black Hole Factory | — | — | — | — | — | — | — |
| 30 | Deathray | — | — | — | — | — | — | — |
| 31 | Unused Blocked | — | — | — | — | — | — | — |

### Snow

| ID | Terrain | Foot | Mech | Treads | Wheels | Air | Ship | Lander |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | Empty | — | — | — | — | — | — | — |
| 1 | Plain | 2 | 1 | 2 | 3 | 2 | — | — |
| 2 | River | 2 | 1 | — | — | 2 | — | — |
| 3 | Mountain | 4 | 2 | — | — | 2 | — | — |
| 4 | Wood | 2 | 1 | 2 | 3 | 2 | — | — |
| 5 | Road | 1 | 1 | 1 | 1 | 2 | — | — |
| 6 | City | 1 | 1 | 1 | 1 | 2 | — | — |
| 7 | Sea | — | — | — | — | 2 | 2 | 2 |
| 8 | HQ | 1 | 1 | 1 | 1 | 2 | — | — |
| 9 | Unused | — | — | — | — | — | — | — |
| 10 | Airport | 1 | 1 | 1 | 1 | 2 | — | — |
| 11 | Port | 1 | 1 | 1 | 1 | 2 | 2 | 2 |
| 12 | Bridge | 1 | 1 | 1 | 1 | 2 | — | — |
| 13 | Shoal | 1 | 1 | 1 | 1 | 2 | — | 1 |
| 14 | Base | 1 | 1 | 1 | 1 | 2 | — | — |
| 15 | Pipe | — | — | — | — | — | — | — |
| 16 | Pipe Seam | — | — | — | — | — | — | — |
| 17 | Missile Silo | 1 | 1 | 1 | 1 | 2 | — | — |
| 18 | Spent Silo | 1 | 1 | 1 | 1 | 2 | — | — |
| 19 | Reef | — | — | — | — | 2 | 2 | 2 |
| 20 | Lab | 1 | 1 | 1 | 1 | 2 | — | — |
| 21 | Minicannon South | — | — | — | — | — | — | — |
| 22 | Minicannon North | — | — | — | — | — | — | — |
| 23 | Minicannon West | — | — | — | — | — | — | — |
| 24 | Minicannon East | — | — | — | — | — | — | — |
| 25 | Laser | — | — | — | — | — | — | — |
| 26 | Black Cannon South | — | — | — | — | — | — | — |
| 27 | Black Cannon North | — | — | — | — | — | — | — |
| 28 | Volcano | — | — | — | — | — | — | — |
| 29 | Black Hole Factory | — | — | — | — | — | — | — |
| 30 | Deathray | — | — | — | — | — | — | — |
| 31 | Unused Blocked | — | — | — | — | — | — | — |

### Rain

| ID | Terrain | Foot | Mech | Treads | Wheels | Air | Ship | Lander |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | Empty | — | — | — | — | — | — | — |
| 1 | Plain | 1 | 1 | 2 | 3 | 1 | — | — |
| 2 | River | 2 | 1 | — | — | 1 | — | — |
| 3 | Mountain | 2 | 1 | — | — | 1 | — | — |
| 4 | Wood | 1 | 1 | 3 | 4 | 1 | — | — |
| 5 | Road | 1 | 1 | 1 | 1 | 1 | — | — |
| 6 | City | 1 | 1 | 1 | 1 | 1 | — | — |
| 7 | Sea | — | — | — | — | 1 | 1 | 1 |
| 8 | HQ | 1 | 1 | 1 | 1 | 1 | — | — |
| 9 | Unused | — | — | — | — | — | — | — |
| 10 | Airport | 1 | 1 | 1 | 1 | 1 | — | — |
| 11 | Port | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 12 | Bridge | 1 | 1 | 1 | 1 | 1 | — | — |
| 13 | Shoal | 1 | 1 | 1 | 1 | 1 | — | 1 |
| 14 | Base | 1 | 1 | 1 | 1 | 1 | — | — |
| 15 | Pipe | — | — | — | — | — | — | — |
| 16 | Pipe Seam | — | — | — | — | — | — | — |
| 17 | Missile Silo | 1 | 1 | 1 | 1 | 1 | — | — |
| 18 | Spent Silo | 1 | 1 | 1 | 1 | 1 | — | — |
| 19 | Reef | — | — | — | — | 1 | 2 | 2 |
| 20 | Lab | 1 | 1 | 1 | 1 | 1 | — | — |
| 21 | Minicannon South | — | — | — | — | — | — | — |
| 22 | Minicannon North | — | — | — | — | — | — | — |
| 23 | Minicannon West | — | — | — | — | — | — | — |
| 24 | Minicannon East | — | — | — | — | — | — | — |
| 25 | Laser | — | — | — | — | — | — | — |
| 26 | Black Cannon South | — | — | — | — | — | — | — |
| 27 | Black Cannon North | — | — | — | — | — | — | — |
| 28 | Volcano | — | — | — | — | — | — | — |
| 29 | Black Hole Factory | — | — | — | — | — | — | — |
| 30 | Deathray | — | — | — | — | — | — | — |
| 31 | Unused Blocked | — | — | — | — | — | — | — |

## Weapons and target compatibility

The matrix contains eligibility from the two ROM weapon tables, not damage
predictions. Column IDs refer to the unit table; 25 is a submerged Submarine.
`P` requires at least one main-weapon round, `S` is an unlimited secondary weapon,
`B` supports both, and `—` supports neither. A main-weapon shot consumes one round;
a secondary shot does not consume main ammo. AW2 chooses the actual weapon and
applies visibility, fog, range, counterattacks, and damage.

Infantry and Recon use the secondary table with no main ammo. Cruiser torpedoes
require main ammo against submarines; its anti-air secondary remains available
at zero main ammo. Anti-Air has no unlimited fallback. Artillery, Rockets,
Missiles, and Battleship are indirect: a nonempty movement path prevents firing
in that action. Direct units may move then attack.

| Attacker ID | 1 | 2 | 3 | 5 | 6 | 7 | 8 | 10 | 11 | 14 | 15 | 16 | 17 | 19 | 20 | 21 | 22 | 23 | 24 | 25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | S | S | S | S | S | S | S | S | S | S | S | — | — | S | S | — | — | — | — | — |
| 2 | S | S | B | B | B | B | B | B | B | B | B | — | — | S | S | — | — | — | — | — |
| 3 | B | B | B | B | B | B | B | B | B | B | B | — | — | S | S | P | P | P | P | — |
| 5 | B | B | B | B | B | B | B | B | B | B | B | — | — | S | S | P | P | P | P | — |
| 6 | S | S | S | S | S | S | S | S | S | S | S | — | — | S | S | — | — | — | — | — |
| 7 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 8 | B | B | B | B | B | B | B | B | B | B | B | — | — | S | S | P | P | P | P | — |
| 10 | P | P | P | P | P | P | P | P | P | P | P | — | — | — | — | P | P | P | P | — |
| 11 | P | P | P | P | P | P | P | P | P | P | P | — | — | — | — | P | P | P | P | — |
| 14 | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P | — | — | — | — | — |
| 15 | — | — | — | — | — | — | — | — | — | — | — | P | P | P | P | — | — | — | — | — |
| 16 | — | — | — | — | — | — | — | — | — | — | — | P | P | P | P | — | — | — | — | — |
| 17 | P | P | P | P | P | P | P | P | P | P | P | — | — | — | — | P | P | P | P | — |
| 19 | B | B | B | B | B | B | B | B | B | B | B | — | — | S | S | P | P | P | P | — |
| 20 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 21 | P | P | P | P | P | P | P | P | P | P | P | — | — | — | — | P | P | P | P | — |
| 22 | — | — | — | — | — | — | — | — | — | — | — | S | S | S | S | — | — | — | P | P |
| 23 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| 24 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | P | P | P | P | P |

## CO and Power modifiers

The following are total changes relative to the baseline unit table, including
passive effects. Do not add the passive change again when applying a Power row.
Power IDs are 0 inactive, 1 Power, and 2 Super. Unlisted units/states have zero
movement/range adjustment. Grit reaches **+3 maximum range** during Super, so
the previous global +2 range bound was insufficient. Direct attack range stays 1.

| CO ID/name | Power | Unit IDs | Movement change | Maximum range change |
|---|---:|---|---:|---:|
| 1 Andy | 2 | 1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24 | +1 | +0 |
| 2 Max | 0 | 10, 11, 15, 21 | +0 | -1 |
| 2 Max | 1 | 3, 5, 6, 8, 14, 16, 17, 19, 22, 24 | +1 | +0 |
| 2 Max | 1 | 10, 11, 15, 21 | +0 | -1 |
| 2 Max | 2 | 3, 5, 6, 8, 14, 16, 17, 19, 22, 24 | +2 | +0 |
| 2 Max | 2 | 10, 11, 15, 21 | +0 | -1 |
| 4 Sami | 0 | 7, 20, 23 | +1 | +0 |
| 4 Sami | 1 | 1, 2, 7, 20, 23 | +1 | +0 |
| 4 Sami | 2 | 1, 2 | +2 | +0 |
| 4 Sami | 2 | 7, 20, 23 | +1 | +0 |
| 5 Grit | 0 | 10, 11, 15, 21 | +0 | +1 |
| 5 Grit | 1 | 10, 11, 15, 21 | +0 | +2 |
| 5 Grit | 2 | 10, 11, 15, 21 | +0 | +3 |
| 9 Drake | 0 | 21, 22, 23, 24 | +1 | +0 |
| 9 Drake | 1 | 21, 22, 23, 24 | +1 | +0 |
| 9 Drake | 2 | 21, 22, 23, 24 | +1 | +0 |
| 13 Adder | 1 | 1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24 | +1 | +0 |
| 13 Adder | 2 | 1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24 | +2 | +0 |
| 17 Jess | 1 | 3, 5, 6, 7, 8, 10, 11, 14, 15 | +1 | +0 |
| 17 Jess | 2 | 3, 5, 6, 7, 8, 10, 11, 14, 15 | +2 | +0 |
| 18 Sensei | 0 | 7, 20, 23 | +1 | +0 |
| 18 Sensei | 1 | 7, 20, 23 | +1 | +0 |
| 18 Sensei | 2 | 7, 20, 23 | +1 | +0 |

Weather table exceptions:

- Olaf uses clear costs in snow and snow costs in rain.
- Drake uses clear costs in rain.
- Sturm uses cost 1 on normally traversable tiles in clear/rain, and ordinary snow costs.
- Lash Power/Super use cost 1 on normally traversable tiles in clear/rain, and ordinary snow costs.
- Sami Power/Super select separate table addresses whose costs equal the baseline tables.

There are seven stored movement table addresses and four distinct cost matrices.
Cost-one movement preserves impassability. `RuleContext()` selects baseline rules
with CO effects disabled; `RuleContext(co_id, active_power)` explicitly enables
the chosen CO effects. The existing observation does not expose the game option
that enables/disables CO effects, so the executor uses permissive bounds across
contexts rather than assuming that option.

## Fuel consumption and boundaries

Under normal fuel-consumption rules the movement debit uses the route movement
cost. The original movement finalizer `0x080424FC` calls the masked fuel subtractor
`0x08025B80` with the route expenditure cached at `0x03004074`; the subtraction
is skipped when the no-consumption option at game context +0x0D is set.
`route_cost` returns that expenditure for an explicit weather/CO context.

Turn-start upkeep is mapped from the unit table's +0x58 pointer and routine
`0x080253B0`, separately from movement fuel. The following are baseline costs:

| Units | Fuel per turn start |
|---|---:|
| All land units | 0 |
| Fighter, Bomber | 5 |
| Battle Copter, Transport Copter | 2 |
| Battleship, Cruiser, Lander, surfaced Submarine | 1 |
| Submerged Submarine | 5 |

Embarked units and units on their own matching service property skip upkeep in
this routine. Eagle subtracts 2 from aircraft upkeep in all Power states, clamped
to zero. The catalog also records the air/naval unit flag that makes zero fuel
fatal in this routine. `turn_start_fuel` computes the debit from explicit cargo,
service-property, dive, and CO settings; it does not perform replenishment or
remove a unit. Existing controlled Bomber airport/turn-start observations support
these fields; the broader depletion/resupply ordering still needs live coverage.
See [fuel/repair evidence](AW2-MAP-RESEARCH.org).

## Verification and reproduction

The ROM unit table is `0x085D5ABC`, stride `0x5C`. Relevant fields:

| Offset | Meaning |
|---|---|
| +0x06 u16 × 10 | Base cost |
| +0x0A / +0x0B / +0x0C | Movement / main ammo / vision |
| +0x0E / +0x0F / +0x10 | Minimum range / maximum range / fuel |
| +0x18 / +0x19 | CO unit group / movement type |
| +0x1E / +0x38 | Primary / secondary target columns (26 each) |

The scalar getters `0x080433B8`/`0x080433C8`, initialization `0x08025BE0`,
and weapon readers `0x08043070`/`0x080433F8` establish these interpretations.
The per-terrain upkeep pointer is +0x58; these original tables are constant across
terrain indices. Upkeep routine `0x080253B0` handles cargo, owned service properties,
submerged state, and the zero-fuel loss flags. `0x08042C68` applies the aircraft
fuel discount from CO flag 0x80.

The CO table starts at `0x085D3DD0`, stride `0x104`; each Power block advances
`0x44`. Weather movement pointers are at +0x50/+0x54/+0x58. Modifier pointers
start at +0x5C. Signed movement/range changes are +4/+6 within the pointed row;
combine the unit group and direct/indirect/transport category as implemented
by `0x08043190`/`0x08043200` (the Infantry/Mech group uses only its own row).

Run the exhaustive audit against a local supported ROM:

```sh
python -m aw2_lab.unit_rules_audit --rom /local/path/aw2.gba
AW2_RUN_RULES_ROM_TESTS=1 AW2_ROM_PATH=/local/path/aw2.gba \
  pytest -q tests/test_aw2_unit_profiles.py
```

On 2026-10-30 the audit passed **40,147 comparisons**: all scalar fields, weapon
eligibility columns, 32 terrain indices across seven movement types and 57 CO/Power
states in all three weather conditions, plus effective movement/range limits,
upkeep tables, and CO fuel discounts.
The report contains only identity and counts; no ROM binary is exported.

ROM-independent tests cover movement/weather, transport terrain restrictions,
ammo fallback, target compatibility, indirect movement restrictions, numeric-ID
regressions, Grit stacking, Olaf/Drake/Lash costs, and fuel-upkeep exceptions.

### Controlled live checks, 2026-10-30

The pinned headless mGBA executable identity was
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`.
All runs used the supported ROM identified above, isolated config/save directories,
and original save states without gameplay RAM writes.

The existing three MoveAttack cases and the MoveWait integration case passed:
a Tank attack destroying an Infantry, target cycling and counterattack, a two-tile
Mech move then attack, and an Infantry moving from (11,2) to (12,2) then Wait.
The checkpoints are the already documented `red-ready.ss0` (SHA-256
`e34dddc4216fef3a84390796a0b188f76ff51f123983f0dc4da423fe970b36d0`) and
`red-capture-ready.ss0` (SHA-256
`d4aa58c9907e5586c38fefc2018c4177b577608357a9347b0a895203ddff622c`).

A separate original `power-settled.ss0` checkpoint (SHA-256
`b95b9c3cc5a15b67834364e4a66b5096e7106f4c552b2e72ffa14c19c4111d0f`)
provided Rockets reference 21 (type 11) at (10,5), with 6 ammo and 40 fuel.
It starts at frame 129616; cursor-only preparation reached frame 129662.
Each case independently restored the prepared state:

| Case | Observation |
|---|---|
| Stationary action menu | Recognized Fire and Wait choices. |
| Move through (9,5) to (9,6) | Screenshot showed only Wait, although enemy (13,6) remained within range 4. |
| Confirm Wait after the two-tile move | Unit reached (9,6), used; road class 5 plus plain class 1 cost 1 + 2 = 3 fuel, observed 40 → 37; ammo stayed 6. |
| Earlier one-road-tile check | Reached (9,5), used; road cost 1 fuel, observed 40 → 39; ammo stayed 6. |
| Stationary attack on enemy Mech (13,6) | Ammo 6 → 5, fuel stayed 40; target health 82 → destroyed; returned used at frame 129774. |

The original run inspected only the first UI process slot, whose selector object
was 0. Inspection of all three 0x60-byte slots found the initialized action
selector in the second slot (`0x030014D0`): object `0x0848A42C`, table
`0x0849AE28`, one row with ID `0x0A` (Wait), selected row 0. The first slot held
a graphics process. The observer now searches all three slots for exactly one
matching action selector and retains the lifecycle, controller, selected-unit,
row-ID, and map-rule checks. Stale rows and ambiguous selectors cannot authorize
dispatch.

The updated live regression uses production navigation to recognize and choose
the one-choice Wait prompt, then restores the same checkpoint and repeats the
route through `MoveWaitActionExecutor`. It checks the reached position `(9,6)`,
used status, fuel 40 → 37, unchanged ammo, and preserved lifetime identity.

The 2026-10-30 headless verification passed, including the subsequent stationary
attack. Its build identity was
`sha256:2428496c7cf6efaa59aa9536ede44790f02960df5f39afdbef3c3f4fe0a37f22`;
ROM and original checkpoint hashes are unchanged from the evidence above.
Artifacts are under
`/tmp/aw2-wait-selector-complete/test_rockets_movement_fire_and0/`;
`evidence.json` SHA-256 is
`45aefd22fdea1dc8532ecfe4af4a27f0046f855105237c4359170905ff02fef3`.
Windowed verification also passed on 2026-10-30 using build identity
`sha256:46703b12dc6ba566874b9283d2e3c2ce7c79771b642695a1fe24744c42871810`.
The production navigator and full MoveWait executor produced the same Rockets
position, used status, fuel, ammo, and identity results as headless mode; the
subsequent stationary attack also passed and ended at the same frame 129774.
Artifacts are under
`/tmp/aw2-wait-windowed-verification/test_rockets_movement_fire_and0/`;
`evidence.json` SHA-256 is
`c148f8d6f92cd596cc8deee2336a3f0b757f2e3e1ecbd3f022d7f11fbd453e5e`.

The opt-in regression is `tests/test_unit_rules_integration.py`:

```sh
AW2_RUN_RULES_LIVE_TESTS=1 AW2_ROM_PATH=/local/path/aw2.gba \
AW2_RULES_CHECKPOINT=/local/path/power-settled.ss0 \
  pytest -s tests/test_unit_rules_integration.py
```

Set `AW2_RULES_MODE=windowed` to repeat with the visible mGBA frontend;
the default is `headless`. The evidence JSON records the selected mode.

Evidence remains outside Git under `/tmp/aw2-unit-terrain-rules/`. The
`controlled-live-terrain-cost/test_rockets_movement_fire_and0/` directory contains
`evidence.json`, `stationary-fire.png`, `moved-no-fire.png`, and the temporary
prepared state. The exhaustive audit report is `audit.json`. Earlier attempts
recorded the watchdog/selector limitation; the final controlled regression passed.
The earlier one-road-tile pass is retained under `controlled-live-complete/`.
The archived checkpoint needs larger cursor-approach limits (600 frames/60 seconds)
than the default short-route examples; production navigation defaults were unchanged.

## Remaining limits

- The executor now rejects permanently incompatible targets and terrain before input.
  Full exact-budget/fuel preflight still needs the CO-effects and fuel-consumption
  options in the observation; fog can shorten the route, and the Fire target list
  remains the final authority at the actual reached tile.
- The catalog is not a damage simulator and does not predict random outcomes.
- Campaign structure names and all individual modifier/terrain combinations have
  static ROM evidence, but have not all been demonstrated through live play.
- Upkeep tables and the zero-fuel loss flags are ROM-audited. Resupply/depletion
  ordering and all individual zero-fuel cases still need broader live coverage.
