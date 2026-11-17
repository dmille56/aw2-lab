# AW2 attack damage preview

The client shows a percentage forecast and a possible damage interval before
final Attack submission. Selecting an enemy from explicit targeting also opens
this preview, so mouse, touch, and keyboard users can read it before committing.
Movement and missile-launch flows retain their existing behavior.

Research references supplied by the user:

- [Damage Formula](https://advancewars.fandom.com/wiki/Damage_Formula)
- [Damage chart](https://advancewars.fandom.com/wiki/Damage)

Direct wiki fetches were blocked; indexed formula text was available. The
supported US revision-0 cartridge is the verification source for the implemented
chart, modifiers, weapon choice, and rounding. Committed numeric tables contain
factual game mechanics. ROMs, generated states, screenshots, and artwork remain
outside Git and the Nix store.

The implementation follows these native routines/tables:

- Unit matchup percentages: `0x085D5ABC`, stride `0x5C`, weapon rows `+0x1E/+0x38`.
- CO modifiers/luck: `0x085D3DD0`, stride `0x104`, power stride `0x44`.
- Terrain stars: `0x085D583C`, stride 20, value `+16`.
- Weapon choice/class firepower: `0x08024ABC`, `0x08043070`, `0x080430B0`.
- Terrain/global modifiers and luck: `0x08024C58`, `0x08043120`, `0x08043304`.
- Forecast and actual rounding: `0x08024DDC`, `0x08024E60`.

The effective available weapon is selected by its damage, including secondary
weapons when primary ammunition is empty or the secondary matchup is stronger.
Class firepower is truncated before universal/Lash firepower is applied. The
forecast applies defense before displayed attacker HP; actual damage applies
HP before defense and includes luck. Those integer steps can differ by one
percentage point even without luck. Percentages describe maximum unit health,
so a lethal forecast can exceed the target's remaining health.

Optional `PlayerState.attack_bonus` and `defense_bonus` observations read signed
player-record fields `+0x26/+0x28`, used by `0x08024C58`. Their defaults are
unknown, preserving old snapshots. Missing observations, unknown CO settings,
unverified terrain/modifiers, and counter-first defense powers produce an
explicit unavailable reason. The client does not guess unseen modifiers or RNG.
The server remains authoritative for action execution; previewing sends no
emulator input.

Verification (2026-11-16):

- An opt-in ROM audit compared all committed combat facts with the supported ROM.
- Eleven controlled savestate cases ran through a private bridge and the native
  Fire-target forecast, then resolved combat. Every forecast matched and every
  observed health loss fell within the calculated interval (capped by remaining
  target health): infantry, partial infantry, partial Mech rounding, Tank weapon
  choice, Max Tank, Kanbei Infantry, Lash terrain firepower, forest defense,
  aircraft ignoring mountain cover, Flak luck, and Lash Super Power defense.
- Original ROM and source checkpoint bytes were unchanged. Fixtures and the
  comparison report remain external; this is controlled-state evidence rather
  than naturally played setup sequences.
- Unit/browser checks cover rounding, HP, weapons/ammo, CO/global modifiers,
  terrain, uncertainty, legacy snapshots, explicit confirmation, and small UI.

Human visual review remains pending.
