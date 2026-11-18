"""Run the real API with prototype assets and explicit native origins; needs a ROM."""

import argparse
import os
from pathlib import Path

import uvicorn

from aw2_lab.api.app import create_app
from aw2_lab.api.client_web import configure_client
from aw2_lab.emulator import EmulatorMode, EmulatorSettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom-path",
        default=os.environ.get("AW2_ROM_PATH"),
        metavar="PATH",
        help="path to your AW2 ROM (required; default: AW2_ROM_PATH)",
    )
    parser.add_argument(
        "--save-profile",
        default=os.environ.get("AW2_SAVE_PROFILE_PATH"),
        metavar="PATH",
        help="isolated starting save profile (.sps or .sav; default: AW2_SAVE_PROFILE_PATH)",
    )
    parser.add_argument("--sprite-pack", type=Path, help="external extracted sprite-pack directory")
    parser.add_argument("--operator-secret-file", type=Path)
    parser.add_argument("--storage-dir", type=Path)
    parser.add_argument("--emulator-mode", choices=list(EmulatorMode), default="headless")
    args = parser.parse_args()
    if not args.rom_path:
        parser.error("an AW2 ROM is required; provide --rom-path or set AW2_ROM_PATH")
    rom_path = Path(args.rom_path).expanduser()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    save_profile_path = None
    if args.save_profile:
        save_profile_path = Path(args.save_profile).expanduser()
        if not save_profile_path.is_file():
            parser.error(f"save profile path is not a file: {save_profile_path}")
        if save_profile_path.suffix.lower() not in {".sav", ".sps"}:
            parser.error("save profile must be an mGBA .sav or GameShark SP .sps file")
    options = {}
    if args.operator_secret_file is not None:
        options["operator_secret_file"] = args.operator_secret_file.expanduser()
    if args.storage_dir is not None:
        options["storage_root"] = args.storage_dir.expanduser()
    app = create_app(
        settings=EmulatorSettings(
            rom_path=rom_path.resolve(),
            save_profile_path=save_profile_path.resolve() if save_profile_path else None,
            mode=EmulatorMode(args.emulator_mode),
        ),
        **options,
    )
    configure_client(app, sprite_pack=args.sprite_pack)
    uvicorn.run(app, host="127.0.0.1", port=43127)


if __name__ == "__main__":
    main()
