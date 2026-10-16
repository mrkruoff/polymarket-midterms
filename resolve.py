#!/usr/bin/env python3
"""After election day: re-poll every market in data/universe.json and record how
Polymarket resolved it. Safe to re-run; unresolved markets just stay unresolved
until the next run (close races can take days).

Writes data/resolutions.csv. A market counts as resolved when it is closed and
outcomePrices has collapsed to 1/0.
"""
import csv
import json
import sys
from datetime import datetime, timezone

from pm_common import GAMMA, RESOLUTIONS, UNIVERSE, get, jlist, yes_price


def main():
    if not UNIVERSE.exists():
        sys.exit("no data/universe.json — run snapshot.py first")
    universe = json.loads(UNIVERSE.read_text())["markets"]
    now = datetime.now(timezone.utc).isoformat()

    rows, resolved = [], 0
    for mid, meta in universe.items():
        try:
            m = get(f"{GAMMA}/markets/{mid}")
        except Exception as e:  # keep going; record the failure
            rows.append({"market_id": mid, "error": str(e), **meta})
            continue
        p = yes_price(m)
        is_resolved = bool(m.get("closed")) and p is not None and p in (0.0, 1.0)
        resolved += is_resolved
        rows.append({
            "market_id": mid,
            "event_id": meta["event_id"],
            "event_title": meta["event_title"],
            "race_type": meta["race_type"],
            "candidate": meta["candidate"],
            "checked_at": now,
            "closed": m.get("closed"),
            "resolved": is_resolved,
            "yes_won": (p == 1.0) if is_resolved else None,
            "final_yes_price": p,
            "uma_statuses": json.dumps(jlist(m.get("umaResolutionStatuses"))),
            "end_date": m.get("endDate"),
            "error": "",
        })

    fields = ["market_id", "event_id", "event_title", "race_type", "candidate", "checked_at",
              "closed", "resolved", "yes_won", "final_yes_price", "uma_statuses", "end_date", "error"]
    with open(RESOLUTIONS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{resolved}/{len(rows)} markets resolved -> {RESOLUTIONS}")


if __name__ == "__main__":
    main()
