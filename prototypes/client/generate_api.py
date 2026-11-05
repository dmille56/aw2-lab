"""Export ROM-independent v1 input/output schemas from the shared Python models."""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

from aw2_lab import api_contract
from aw2_lab.match_contract import CommandReceipt, CommandResult

SCHEMA_PATH = Path(__file__).parent / "schemas" / "api-v1.json"


def schema_text() -> str:
    models: list[type[BaseModel]] = [
        model
        for model in vars(api_contract).values()
        if isinstance(model, type)
        and issubclass(model, BaseModel)
        and model.__module__ == api_contract.__name__
    ]
    models.extend([CommandReceipt, CommandResult])
    models.sort(key=lambda model: model.__name__)
    modes: tuple[JsonSchemaMode, ...] = ("validation", "serialization")
    _, schema = models_json_schema(
        [(model, mode) for model in models for mode in modes],
        ref_template="#/components/schemas/{model}",
    )
    document = {
        "openapi": "3.1.0",
        "info": {"title": "AW2 shared v1 contracts", "version": "1"},
        "paths": {},
        "components": {"schemas": schema["$defs"]},
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = schema_text()
    if args.check:
        if not SCHEMA_PATH.is_file() or SCHEMA_PATH.read_text() != text:
            parser.exit(1, "API schemas are stale; run prototypes/client/generate_api.py\n")
    else:
        SCHEMA_PATH.write_text(text)


if __name__ == "__main__":
    main()
