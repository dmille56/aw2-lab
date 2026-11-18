"""Isolated Pi configuration shared by the example host and match launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from aw2_lab.match_contract import PlayerSlot


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
        "mcp__aw2__*",
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
