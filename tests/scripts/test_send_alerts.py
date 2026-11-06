from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_send_alerts_help_imports_the_application_package() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "tests")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "send_alerts.py"), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "weekly" in result.stdout
    assert "urgent" in result.stdout
    assert "status" in result.stdout


def test_alerts_workflow_installs_the_sunday_clock() -> None:
    text = (ROOT / ".github" / "workflows" / "alerts.yml").read_text()
    assert 'cron: "0 16,17,18 * * 0"' in text
    assert "scripts/send_alerts.py weekly" in text
