# Cruiser cargo

Cruisers (unit type 22) carry up to two Battle Copters (19), Transport Copters
(20), or one of each. Existing APC, Transport Copter, and Lander cargo rules
remain in the shared transport rules. Load preflight rejects incompatible cargo
and full carriers before sending controller input.

The client offers Load on a compatible allied Cruiser, shows the existing cargo
badge and passenger names, and previews separate adjacent aerial drop tiles.
Sea tiles are valid copter destinations. The server preserves cargo identity and
observed passenger order, validates the route and fuel, and checks the final
carrier and passenger positions, usage flags, links, and identities before
committing a command. Existing command recovery applies to failed actions.

A full Cruiser can show Fire / Drop / Drop / Wait when an enemy is in range;
that four-row menu is recognized without allowing arbitrary larger menus.

The native Cruiser continuation differs from the first action menu. After the
first Drop, its Drop/Wait selector uses input state 5. A moved Cruiser can allocate
its second drop cursor in the fourth UI slot. Movement overlays likewise use any
of the four slots: the observer requires a unique movement selector with its
initialization counter complete, rather than assuming the first slot.

The drop helper's +0x20 field is a target index (0 through 3). Its previous menu
row bytes are unused and can retain arbitrary values, including the 5-row/row-4
values observed during the Rainy Haven human playtest. Cursor recognition uses
the native process signature, bounded target index, selected carrier/cargo, and
control state. Stale menu rows do not block an otherwise verified cursor.

Battle data remains unavailable during an unresolved engine phase. The executor
accepts only the recognized continuation with valid raw structures, then verifies
every requested drop at the final settled boundary. It never publishes an
intermediate battle or commits a partially checked result.

ROM-independent checks cover compatibility and capacity, both copter classes,
full/incompatible loading before input, cargo decoding, continuation recognition,
sequential drop planning and execution, and existing carrier regressions. Browser
coverage exercises a mixed two-copter sea-drop preview and the final command.

Isolated supported-cartridge checks (2026-11-16) loaded a Battle Copter and a
Transport Copter sequentially into an empty Cruiser. Both mixed-cargo drops then
passed through the actual executor, over sea, in place and after a one-tile
carrier move. Final cargo links, destinations, usage flags, and stable identities
passed executor postconditions. The input ROM and source checkpoint were unchanged;
all modified checkpoints and screenshots stayed outside Git and the Nix store.

A follow-up replay used an unmodified copy of the actual Rainy Haven playtest
checkpoint, with one loaded Battle Copter. The original implementation reproduced
the selection timeout in UI slot 1 and the stale-row drop timeout. After the
observer fixes, the real executors passed north/east Move & Wait routes and both
reported move-and-unload routes: Cruiser (2,14) to (2,8), copter to (1,8), and
Cruiser to (2,9), copter to (2,10). Final positions, cargo links, and identities
passed executor checks. The source checkpoint was byte-identical afterward.

Human playtest acceptance remains open.
