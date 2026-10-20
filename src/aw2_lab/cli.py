"""Command-line entry point for the local backend."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="aw2-lab")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", default=43127, type=int, help="HTTP port (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run("aw2_lab.api.app:app", host=args.host, port=args.port)
