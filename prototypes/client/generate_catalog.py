"""Generate the client's public rule labels; no ROM or emulator is required."""

import argparse
import json
from pathlib import Path

from aw2_lab.aw2_rules_data import TERRAIN_NAMES, VERIFIED_CO_NAMES
from aw2_lab.aw2_unit_profiles import UNIT_PROFILES

CATALOG_PATH = Path(__file__).parent / "web" / "catalog.json"


def catalog_text() -> str:
    catalog = {
        "schema_version": 1,
        "terrain": TERRAIN_NAMES,
        "cos": VERIFIED_CO_NAMES,
        "units": {
            key: {
                "name": profile.name,
                "movement": profile.movement,
                "movement_type": profile.movement_type.name,
                "minimum_range": profile.minimum_range,
                "maximum_range": profile.maximum_range,
                "fuel_capacity": profile.fuel_capacity,
                "ammo_capacity": profile.ammo_capacity,
                "cost": profile.cost,
            }
            for key, profile in UNIT_PROFILES.items()
        },
    }
    return json.dumps(catalog, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated data is stale")
    args = parser.parse_args()
    text = catalog_text()
    if args.check:
        if not CATALOG_PATH.is_file() or CATALOG_PATH.read_text() != text:
            parser.exit(1, "Client catalog is stale; run prototypes/client/generate_catalog.py\n")
    else:
        CATALOG_PATH.write_text(text)


if __name__ == "__main__":
    main()
