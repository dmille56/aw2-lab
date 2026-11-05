"""Run reproducible client gates from the repository root using aw2-client-check."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 600) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=timeout)


def native_smoke(repo: Path, frontend: Path, env: dict[str, str]) -> None:
    # The fixture server, never an emulator, owns this port only for the smoke test.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 43127))
    built = (
        subprocess.check_output(
            ["nix", "build", "--no-link", "--print-out-paths", f"{repo}#client-prototype"],
            cwd=repo,
            env=env,
            text=True,
        )
        .strip()
        .splitlines()[-1]
    )
    command = ["xvfb-run", "-a", str(Path(built) / "bin/aw2-client-prototype")]
    fixture_env = {**env, "AW2_CLIENT_FIXTURE_ID": uuid4().hex}
    smoke_env = {**fixture_env, "AW2_CLIENT_SMOKE_TEST": "1", "GDK_BACKEND": "x11"}
    with subprocess.Popen(
        ["python", "tests/server.py", "--port", "43127"],
        cwd=frontend,
        env=fixture_env,
    ) as server:
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Synthetic native fixture server exited")
                try:
                    with urlopen("http://127.0.0.1:43127/health", timeout=1) as response:
                        if (
                            json.load(response).get("fixture_id")
                            == fixture_env["AW2_CLIENT_FIXTURE_ID"]
                        ):
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Synthetic native fixture server did not become ready")
            run(command, cwd=repo, env=smoke_env, timeout=30)
        finally:
            server.terminate()
            server.wait(timeout=10)
    # Missing-server behavior is part of the native smoke contract too.
    failed = subprocess.run(command, cwd=repo, env=smoke_env, timeout=30, check=False)
    if failed.returncode != 1:
        raise RuntimeError(f"Offline native smoke should exit 1, got {failed.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--fast", action="store_true", help="pre-commit checks without browsers/native build"
    )
    parser.add_argument(
        "--update-snapshots", action="store_true", help="explicitly update browser visual baselines"
    )
    args = parser.parse_args()
    if args.fast and args.update_snapshots:
        parser.error("--update-snapshots requires the full browser checks")
    repo = args.repo.resolve()
    client = repo / "prototypes/client"
    modules = os.environ.get("AW2_CLIENT_NODE_MODULES")
    lock = os.environ.get("AW2_CLIENT_LOCK")
    if not modules or not lock:
        parser.error("Use aw2-client-check from the Nix shell (or nix run .#check-client)")
    if Path(lock).read_bytes() != (client / "package-lock.json").read_bytes():
        parser.error("Client dependency lock changed; rebuild/re-enter the Nix check environment")
    with tempfile.TemporaryDirectory(prefix="aw2-client-check-") as directory:
        frontend = Path(directory) / "client"
        shutil.copytree(
            client,
            frontend,
            ignore=shutil.ignore_patterns(
                "node_modules",
                "target",
                "gen",
                "coverage",
                "test-results",
                "playwright-report",
                "__pycache__",
            ),
        )
        # Tool packages stay immutable; Vite/Vitest may create sibling cache directories.
        node_modules = frontend / "node_modules"
        node_modules.mkdir()
        for package in Path(modules).iterdir():
            (node_modules / package.name).symlink_to(package, target_is_directory=package.is_dir())
        env = {
            **os.environ,
            "PYTHONPATH": str(repo / "src"),
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        }
        run(["npm", "run", "check"], cwd=frontend, env=env)
        run(["python", "prototypes/client/generate_catalog.py", "--check"], cwd=repo, env=env)
        run(["ruff", "check", "prototypes/client"], cwd=repo, env=env)
        run(["ruff", "format", "--check", "prototypes/client"], cwd=repo, env=env)
        run(["mypy", "--config-file", "pyproject.toml"], cwd=repo, env=env)
        run(["python", "-m", "pytest", "tests/test_client_prototype.py"], cwd=repo, env=env)
        run(
            [
                "cargo",
                "fmt",
                "--manifest-path",
                "prototypes/client/Cargo.toml",
                "--all",
                "--",
                "--check",
            ],
            cwd=repo,
            env=env,
        )
        if not args.fast:
            browser = ["npm", "run", "test:browser", "--"]
            if args.update_snapshots:
                browser.append("--update-snapshots")
            try:
                run(browser, cwd=frontend, env=env)
                if args.update_snapshots:
                    for path in (frontend / "tests/browser").rglob("*.png"):
                        destination = client / path.relative_to(frontend)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, destination)
                native_smoke(repo, frontend, env)
            finally:
                output = client / "test-results"
                output.mkdir(exist_ok=True)
                for name in ("test-results", "coverage"):
                    source = frontend / name
                    if source.exists():
                        shutil.copytree(
                            source,
                            output / ("browser" if name == "test-results" else name),
                            dirs_exist_ok=True,
                        )
        print("\nClient checks passed.", flush=True)


if __name__ == "__main__":
    main()
