"""Operator setup, startup, checkpoint archive transfer, recovery, and closure."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

from pydantic import SecretStr

from aw2_lab.match_contract import PlayerSlot
from aw2_lab.sdk import AsyncAW2Client


def private_file(path: Path, value: str | bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(value.encode() if isinstance(value, str) else value)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("create", "start", "save", "export", "import", "restore", "close")
    )
    parser.add_argument("--url", default="http://127.0.0.1:43127")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".local/state/aw2-lab/sdk-demo"
    )
    parser.add_argument("--checkpoint", type=UUID)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    async with AsyncAW2Client(
        args.url, credential=SecretStr(args.token_file.read_text().strip())
    ) as client:
        directory = args.directory
        if args.operation == "create":
            directory.mkdir(mode=0o700, parents=True)
            capabilities = await client.capabilities()
            profile = next(
                p
                for p in capabilities.configuration_profiles
                if p.profile_id == capabilities.default_profile_id
            )
            match = await client.create_match(profile.configuration)
            private_file(directory / "match-id", str(match.match_id))
            for slot in PlayerSlot:
                invitation = SecretStr(token_urlsafe(32))
                await client.invite(match.match_id, slot, invitation)
                private_file(directory / f"{slot.value}.invitation", invitation.get_secret_value())
            print("Match:", match.match_id, "— join both slots, then run start")
            return
        match_id = UUID((directory / "match-id").read_text().strip())
        state = await client.state(match_id)
        revision = state.summary.revision
        receipt = None
        if args.operation == "start":
            receipt = await client.start(match_id, revision)
        elif args.operation == "save":
            receipt = await client.create_checkpoint(match_id, revision)
        elif args.operation == "close":
            receipt = await client.close(match_id)
        elif args.operation == "restore":
            if args.checkpoint is None:
                parser.error("restore requires --checkpoint")
            receipt = await client.restore_checkpoint(match_id, args.checkpoint, revision)
        elif args.operation == "export":
            if args.checkpoint is None or args.archive is None:
                parser.error("export requires --checkpoint and --archive")
            private_file(args.archive, await client.export_checkpoint(match_id, args.checkpoint))
        elif args.operation == "import":
            if args.archive is None:
                parser.error("import requires --archive")
            reference = await client.import_checkpoint(match_id, args.archive.read_bytes())
            print("Imported checkpoint:", reference.checkpoint_id)
        if receipt:
            print("Accepted command:", receipt.command_id)
            result = await client.wait_for_command(match_id, receipt.command_id, timeout=120)
            print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
