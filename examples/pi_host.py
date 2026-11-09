"""Prepare or launch an isolated local Pi host for one AW2 player."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", type=UUID, required=True)
    parser.add_argument("--slot", choices=("slot_1", "slot_2"), required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:43127/mcp/")
    parser.add_argument("--model", help="Pi provider/model identifier; otherwise choose in Pi")
    parser.add_argument("--pi-bin", default="pi", help="Pi executable (version 1.5.0 verified)")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Discover MCP tools without a model call"
    )
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path.rstrip("/") != "/mcp"
    ):
        parser.error("--url must be a loopback HTTP /mcp endpoint without credentials or query")
    try:
        if args.token_file.stat().st_mode & 0o077:
            parser.error("player token file must be private (chmod 600)")
        token = args.token_file.read_text().strip()
    except OSError:
        parser.error("cannot read player token file")
    if not 32 <= len(token) <= 128 or any(c.isspace() for c in token):
        parser.error("player token must contain 32–128 non-whitespace characters")

    run_dir = ROOT / ".local" / "aw2-pi" / str(args.match_id) / args.slot
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    agent_dir = run_dir / "agent"
    agent_dir.mkdir(exist_ok=True, mode=0o700)
    config = json.loads((ROOT / "examples" / "pi-host" / "mcp.json").read_text())
    config["mcpServers"]["aw2"]["url"] = args.url
    (agent_dir / "mcp.json").write_text(json.dumps(config, indent=2) + "\n")
    # Share provider login/custom model definitions, but no global MCP servers,
    # extensions, settings, context files, or session histories.
    global_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent"))
    for name in ("auth.json", "models.json"):
        source = global_dir / name
        target = agent_dir / name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(source.resolve())
    if args.prepare_only:
        print(f"Prepared Pi host: {run_dir}")
        return 0
    executable = shutil.which(args.pi_bin)
    if executable is None:
        parser.error("Pi executable not found; install Pi or pass --pi-bin")
    try:
        identity_url = f"http://{url.netloc}/v1/matches/{args.match_id}/identity"
        response = httpx.get(identity_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        response.raise_for_status()
        identity = response.json()
    except httpx.HTTPError, ValueError:
        parser.error("cannot verify player identity; check server, match ID, and token file")
    if (
        identity.get("role") != "player"
        or identity.get("match_id") != str(args.match_id)
        or identity.get("player_slot") != args.slot
    ):
        parser.error("token does not identify the assigned match/player slot")
    env = dict(os.environ, PI_CODING_AGENT_DIR=str(agent_dir), AW2_PLAYER_TOKEN=token)
    if args.check:
        return subprocess.run(
            [executable, "mcp", "list", "--json"], cwd=run_dir, env=env, check=False, timeout=120
        ).returncode
    prompt = (ROOT / "examples" / "pi-host" / "system.md").read_text()
    prompt += f"\nYour match ID is {args.match_id}. Your player slot is {args.slot}.\n"
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
        str(run_dir / "sessions"),
        "--system-prompt",
        prompt,
    ]
    if args.model:
        command.extend(["--model", args.model])
    os.chdir(run_dir)
    os.execvpe(executable, command, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
