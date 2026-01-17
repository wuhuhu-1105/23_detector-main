from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], *, label: str) -> bool:
    print(f"[SMOKE] {label}: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        print(f"[SMOKE] {label} FAIL (exit={exc.returncode})")
        return False
    print(f"[SMOKE] {label} PASS")
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_video = repo_root / "outputs" / "smoke_short.mp4"
    source = os.environ.get("SMOKE_VIDEO", str(default_video))

    python = sys.executable
    ok = True

    ok &= _run([python, "tools/check_service_imports.py"], label="guard")
    ok &= _run([python, "-m", "src.app_qt", "--headless", "--source", source, "--end-sec", "1"], label="A")
    ok &= _run([python, "-m", "src.cli.report_gen", "--source", source, "--format", "json"], label="B")

    if ok:
        print("[SMOKE] ALL PASS")
        return 0
    print("[SMOKE] FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
