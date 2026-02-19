"""Run Playwright smoke tests from Python tooling."""

from __future__ import annotations

import subprocess
import sys
import shutil
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    extra_args = sys.argv[1:]
    npm_executable = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_executable:
        print("[ERROR] npm is not installed or not on PATH.")
        return 1

    cmd = [npm_executable, "run", "test:e2e"]
    if extra_args:
        cmd.extend(["--", *extra_args])

    completed = subprocess.run(cmd, cwd=repo_root, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
