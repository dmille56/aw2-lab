"""Run twice with separate slots and private credentials to play the same match."""

import argparse
import asyncio
import json
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

from manage_match import private_file
from pydantic import SecretStr, TypeAdapter

from aw2_lab.match_contract import GameplayAction, MatchLifecycle, PlayerSlot
from aw2_lab.sdk import AsyncAW2Client, SDKError


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slot", choices=[slot.value for slot in PlayerSlot])
    parser.add_argument("--url", default="http://127.0.0.1:43127")
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".local/state/aw2-lab/sdk-demo"
    )
    parser.add_argument(
        "--join", action="store_true", help="claim using the private invitation file"
    )
    args = parser.parse_args()
    directory, slot = args.directory, PlayerSlot(args.slot)
    match_id = UUID((directory / "match-id").read_text().strip())
    token_file = directory / f"{slot.value}.token"
    if not token_file.exists():
        private_file(token_file, token_urlsafe(32))
    credential = SecretStr(token_file.read_text().strip())
    async with AsyncAW2Client(args.url, credential=credential) as client:
        if args.join:
            invitation = SecretStr((directory / f"{slot.value}.invitation").read_text().strip())
            await client.join(match_id, slot, invitation, slot.value)
            print("Joined. The operator can start once both slots are claimed.")
        print("Enter a gameplay action as JSON, save, or quit. Waiting for your turn…")
        while True:
            state = await client.wait_for_turn(match_id, slot, timeout=3600)
            if state.summary.lifecycle is not MatchLifecycle.PLAYABLE:
                print("Match:", state.summary.lifecycle.value)
                return
            print(json.dumps(state.model_dump(mode="json"), indent=2))
            text = await asyncio.to_thread(input, f"{slot.value}> ")
            if text == "quit":
                return
            try:
                if text == "save":
                    receipt = await client.create_checkpoint(match_id, state.summary.revision)
                else:
                    action = TypeAdapter(GameplayAction).validate_json(text)
                    receipt = await client.submit(match_id, state.summary.revision, action)
                print("Accepted command:", receipt.command_id)
                result = await client.wait_for_command(match_id, receipt.command_id, timeout=120)
                print(json.dumps(result.model_dump(mode="json"), indent=2))
            except (SDKError, ValueError) as error:
                print(type(error).__name__, str(error))


if __name__ == "__main__":
    asyncio.run(main())
