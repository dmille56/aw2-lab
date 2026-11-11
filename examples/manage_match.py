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
    parser.add_argument("--map-id", help="select an advertised map ID when creating a match")
    parser.add_argument(
        "--co-ids",
        metavar="CO1,CO2",
        help="select one advertised CO for each player, for example sami,nell",
    )
    parser.add_argument(
        "--income-per-property",
        type=int,
        help="select an advertised income amount when creating a match",
    )
    parser.add_argument("--day-limit", help="select an advertised day limit or 'off'")
    parser.add_argument("--capture-limit", help="select an advertised capture limit or 'off'")
    parser.add_argument("--weather", help="select an advertised starting weather")
    parser.add_argument("--co-powers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--checkpoint", type=UUID)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    async with AsyncAW2Client(
        args.url, credential=SecretStr(args.token_file.read_text().strip())
    ) as client:
        directory = args.directory
        if args.operation == "create":
            capabilities = await client.capabilities()
            profile_id = f"{args.map_id}_v1" if args.map_id else capabilities.default_profile_id
            profile = next(
                (p for p in capabilities.configuration_profiles if p.profile_id == profile_id),
                None,
            )
            if profile is None:
                parser.error("map ID is not advertised by this server")
            configuration = profile.configuration
            if args.co_ids:
                co_ids = tuple(co_id.strip() for co_id in args.co_ids.split(","))
                if len(co_ids) != 2 or any(
                    co_id not in capabilities.configuration_options.co_ids for co_id in co_ids
                ):
                    parser.error("--co-ids must contain two CO IDs advertised by this server")
                players = tuple(
                    player.model_copy(update={"co_id": co_id})
                    for player, co_id in zip(configuration.players, co_ids, strict=True)
                )
                configuration = configuration.model_copy(update={"players": players})
            rules = configuration.rules
            rule_options = capabilities.configuration_options.rule_options
            rule_updates = {}
            if args.income_per_property is not None:
                if args.income_per_property not in rule_options.income_per_property:
                    parser.error("income is not advertised by this server")
                rule_updates["income_per_property"] = args.income_per_property
            if args.day_limit is not None:
                try:
                    day_limit = None if args.day_limit.lower() == "off" else int(args.day_limit)
                except ValueError:
                    parser.error("--day-limit must be an integer or 'off'")
                if day_limit not in rule_options.day_limit:
                    parser.error("day limit is not advertised by this server")
                rule_updates["day_limit"] = day_limit
            if args.capture_limit is not None:
                try:
                    capture_limit = (
                        None if args.capture_limit.lower() == "off" else int(args.capture_limit)
                    )
                except ValueError:
                    parser.error("--capture-limit must be an integer or 'off'")
                if capture_limit not in rule_options.capture_limit:
                    parser.error("capture limit is not advertised by this server")
                rule_updates["capture_limit"] = capture_limit
            if args.weather is not None:
                if args.weather not in rule_options.weather:
                    parser.error("starting weather is not advertised by this server")
                rule_updates["weather"] = args.weather
            if args.co_powers is not None:
                if args.co_powers not in rule_options.co_powers:
                    parser.error("CO-power setting is not advertised by this server")
                rule_updates["co_powers"] = args.co_powers
            if rule_updates:
                configuration = configuration.model_copy(
                    update={"rules": rules.model_copy(update=rule_updates)}
                )
            directory.mkdir(mode=0o700, parents=True)
            match = await client.create_match(configuration)
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
