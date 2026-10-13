import os
from pathlib import Path
import subprocess
import sys

import pytest


RUNNER = Path(__file__).resolve().parents[1] / "check_renpy.py"


@pytest.mark.parametrize("status,expected", [("PASSED", 0), ("FAILED", 1), (None, 1), ("COLORED", 0)])
def test_runner_uses_completed_report_and_reaps_unresponsive_sdk(tmp_path, status, expected):
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    pidfile = tmp_path / "sdk.pid"
    script = sdk / "renpy.sh"
    report = "\x1b[32mStatus:\x1b[0m \x1b[32mPASSED\x1b[0m" if status == "COLORED" else f"Status: {status}"
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        + (f"print({'[rpytest] ' + report!r}, flush=True)\n" if status else "")
        + "while True: time.sleep(1)\n"
    )
    script.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--sdk", str(sdk), "--timeout", "1"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
