"""Trusted local storage configuration for durable match data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_storage_root(environ: dict[str, str] | None = None) -> Path:
    """Return the platform's per-user data directory for aw2-lab."""
    environment = os.environ if environ is None else environ
    if sys.platform == "win32":
        base = environment.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = environment.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base).expanduser() / "aw2-lab"


def resolve_storage_root(path: Path | str | None = None) -> Path:
    """Resolve a trusted root, rejecting the source checkout and immutable Nix store."""
    root = Path(path).expanduser() if path is not None else default_storage_root()
    root = root.resolve()
    repository = Path(__file__).resolve().parents[2]
    nix_store = Path("/nix/store")
    if root == repository or repository in root.parents:
        raise ValueError("Storage directory must be outside the aw2-lab source checkout")
    if root == nix_store or nix_store in root.parents:
        raise ValueError("Storage directory must be outside the Nix store")
    return root
