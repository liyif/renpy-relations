"""Run the demo's real-engine tests and collect Ren'Py's completed report.

Ren'Py 8.5.3 can keep spinning after test_run_end. Treat its explicit test
report as the outcome and reap the isolated process group after that report.
No SDK source files are patched. This runner currently targets Linux SDKs.
"""

import argparse
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    launcher = parser.add_mutually_exclusive_group(required=True)
    launcher.add_argument("--sdk", type=Path)
    launcher.add_argument("--launcher", type=Path, help="Test with a standalone game's own launcher")
    parser.add_argument("--mode", choices=("cached", "live", "materialized"), default="cached")
    parser.add_argument("--backend", choices=("sqlite", "duckdb"), default="sqlite")
    parser.add_argument("--game", type=Path, default=Path(__file__).resolve().parent / "examples" / "palace",
                        help="Ren'Py project directory (default: examples/palace)")
    parser.add_argument("--suite", default="relations", help="Test suite or testcase selector")
    parser.add_argument("--headless", action="store_true", help="Use xvfb-run and software rendering")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    executable = args.launcher.resolve() if args.launcher else args.sdk.resolve() / "renpy.sh"
    if not executable.is_file():
        parser.error("Launcher must exist (--sdk/renpy.sh or --launcher)")
    game = args.game.resolve()
    if not (game / "game").is_dir():
        parser.error("--game must point to a Ren'Py project containing game/")
    command = [str(executable), str(game), "test", args.suite, "--report-detailed"]
    if args.headless:
        command = ["xvfb-run", "-a", *command]
    environment = dict(os.environ, RELATIONS_MODE=args.mode, RELATIONS_BACKEND=args.backend,
                       SDL_AUDIODRIVER="dummy")
    if args.headless:
        environment.update(SDL_VIDEODRIVER="x11", LIBGL_ALWAYS_SOFTWARE="1")
    lines = queue.Queue()
    with tempfile.TemporaryDirectory(prefix="renpy-relations-saves-") as saves:
        environment["RENPY_PATH_TO_SAVES"] = saves
        process = subprocess.Popen(
            command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", start_new_session=True,
        )

        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        status = None
        try:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=min(0.2, max(0.001, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if line is None:
                    break
                print(line, end="", flush=True)
                plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
                match = re.search(r"\[rpytest\]\s+Status:\s+(\w+)", plain)
                if match:
                    status = match.group(1)
                    break
            if status is None:
                print("No completed test report received; test run failed.", flush=True)
        finally:
            # Reap the SDK and virtual display, including failed/hung runs.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdout.close()
        return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
