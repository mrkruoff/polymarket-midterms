#!/usr/bin/env python3
"""Daily launchd job: snapshot both venues -> export -> commit the data -> push.

Python (not shell) on purpose: under launchd, macOS TCC lets the venv
interpreter work inside ~/Documents but denies /bin/bash as the job's root
binary ("Operation not permitted"). Stages ONLY data paths so uncommitted code
edits never ride along in an automated commit. A failed push is non-fatal —
the commit stays local and goes out with the next day's push. So is a failed
Kalshi snapshot: Polymarket's data still gets exported and committed.
"""
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GIT = "/usr/bin/git"
DATA_PATHS = ["data/snapshots", "data/universe.json", "data/history.csv", "data/candidates.csv",
              "docs/data.json"]


def run(*cmd, check=True):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=check)


def main():
    py = str(ROOT / ".venv" / "bin" / "python")
    run(py, "snapshot.py")
    if run(py, "kalshi_snapshot.py", check=False).returncode != 0:
        print("WARNING: kalshi_snapshot.py failed — continuing with Polymarket only")
    run(py, "build_candidates.py")  # new markets get a party row; manual fills are kept
    run(py, "export_site.py")

    run(GIT, "add", "--", *DATA_PATHS)
    if run(GIT, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("no data changes to commit")
        return
    run(GIT, "commit", "-m", f"Daily snapshot {date.today()}")
    if run(GIT, "push", "origin", "main", check=False).returncode != 0:
        print("WARNING: push failed (offline? auth?) — commit kept locally")


if __name__ == "__main__":
    main()
