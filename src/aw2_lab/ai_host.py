"""Isolated Pi configuration shared by the example host and match launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from aw2_lab.match_contract import PlayerSlot
from aw2_lab.turn_brief import BriefFormat

COMPACT_AI_TOOLS = (
    "get_turn_brief",
    "play_action",
    "wait_for_command",
    "get_command",
    "get_state",
    "get_observation",
    "get_capabilities",
    "get_screenshot",
)
COMPACT_AI_INSTRUCTIONS = """
Pass `format: "compact"` to get_turn_brief and play_action. Compact briefs use
unit rows [unit_id, unit_type, tile, hp], purchase rows [unit_type, cost], and
movement rows [destination, path, can_capture]. Each purchase menu applies to
every tile in its facility group. A missing reachable_tiles means no verified
movement data; an empty list means no destinations. A missing turn_brief means
the action reply has no new brief.

Tiles in compact replies are [x, y]. For action arguments, use the tool schema's
{"x": x, "y": y} objects. Copy every step in the path, excluding the starting
tile. Use the same action payload and request ID when retrying.
"""


def prepare_pi(
    directory: Path,
    *,
    url: str,
    token: str,
    match_id: UUID,
    slot: PlayerSlot,
    executable: str,
    model: str | None,
    prompt: str,
    thinking: str | None = None,
    mcp_profile: BriefFormat = "standard",
) -> tuple[list[str], dict[str, str]]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    agent = directory / "agent"
    agent.mkdir(exist_ok=True, mode=0o700)
    (agent / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "aw2": {
                        "url": url,
                        "headers": {"Authorization": "Bearer ${AW2_PLAYER_TOKEN}"},
                        "exposure": "direct",
                        "description": "Play your assigned AW2 match",
                    }
                }
            }
        )
        + "\n"
    )
    provider = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent"))
    for name in ("auth.json", "models.json"):
        source, target = provider / name, agent / name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(source.resolve())
    environment = dict(os.environ, PI_CODING_AGENT_DIR=str(agent), AW2_PLAYER_TOKEN=token)
    tools = "mcp__aw2__*"
    if mcp_profile == "compact":
        tools = ",".join(f"mcp__aw2__{name}" for name in COMPACT_AI_TOOLS)
        prompt += COMPACT_AI_INSTRUCTIONS
    command = [
        executable,
        "--no-extensions",
        "--extension",
        "builtin:mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--no-themes",
        "--no-builtin-tools",
        "--tools",
        tools,
        "--session-dir",
        str(directory / "sessions"),
        "--system-prompt",
        prompt + f"\nYour match ID is {match_id}. Your player slot is {slot.value}.\n",
    ]
    if model:
        command += ["--model", model]
    if thinking:
        command += ["--thinking", thinking]
    return command, environment
