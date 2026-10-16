#!/bin/bash
# Daily job (launchd, noon): snapshot -> export -> commit the data -> push.
# Stages ONLY data paths so uncommitted code edits never ride along in an
# automated commit. Push failures are non-fatal: the commit waits locally and
# goes out with the next day's push.
set -e
cd "$(dirname "$0")"

.venv/bin/python snapshot.py
.venv/bin/python export_site.py

git add data/snapshots data/universe.json data/history.csv docs/data.json
if git diff --cached --quiet; then
    echo "no data changes to commit"
else
    git commit -m "Daily snapshot $(date +%F)"
    git push origin main || echo "WARNING: push failed (offline? auth?) — commit kept locally"
fi
