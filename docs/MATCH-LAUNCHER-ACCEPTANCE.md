# Match launcher live acceptance

Verified on Linux/NixOS on 2026-11-17 (PST), using the packaged launcher from
`d715256`, Pi 1.5.2, and `openai/gpt-6-luna` with low thinking. These were
user-approved external-model calls against fresh, isolated matches.

Both matches used Bean Island, Andy/Max, external player controls, clear weather,
fog off, 1,000 income per property, powers enabled, and a 30-day limit. The
emulator ran headlessly. Existing player-vs-player acceptance had already checked
both authenticated browser tabs and a completed human turn change.

| Scenario | Live AI turns | Browser check | Result |
| --- | ---: | --- | --- |
| AI vs human, human in slot 2 | 1, slot 1 | Human tab authenticated as Player 2; launch fragment removed | Passed |
| AI vs AI | 2, one per slot | Read-only watch tab authenticated; End turn disabled; gameplay POST rejected with HTTP 403 | Passed |

Each of the three real model hosts called `get_capabilities`, `get_state`,
`get_observation`, `end_turn`, and `wait_for_command`. The model ended its turn
and waited for the command's terminal result before exiting. No tool executions
or assistant messages reported errors. Both helper processes exited with status
0, and the supervisor verified that the authoritative turn had advanced.

The two command journals contain five completed commands in total: two match
starts and three end-turn commands. There are no rejected, rolled-back, or
recovery-required terminal results. Separate slot directories, credentials, and
session histories were used for the two AI hosts.

After the bounded runs, both API ports and both Lua bridge ports were closed.
Both durable checkpoint stores retained their `CURRENT` pointers. The existing
Rainy Haven playtest remained running and was not targeted by these tests.

Raw provider transcripts, game observations, authorization files, launch links,
and native checkpoints remain in private local run directories outside Git and
the Nix store. This report includes no credentials or extracted artwork.

This verifies model-host startup, authenticated observation, turn handoff,
receipt tracking, browser access, watch restrictions, and owned-process cleanup.
The three turns contained end-turn actions only. It does not establish strategic
quality, unit-action planning, full-match completion, victory, sustained model
reliability, or acceptance on other platforms or emulator frontends.
