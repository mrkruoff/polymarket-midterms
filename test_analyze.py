#!/usr/bin/env python3
"""Smoke test: fake a resolutions.csv from the current universe and check that
analyze.py runs end-to-end on the real snapshot/history data.

The fake resolution marks each race's currently highest-priced candidate as the
winner, so expect hit_rate ~1.0 and tiny Briers — that only proves the plumbing,
not the markets. Both data/resolutions.csv and data/results.json are DELETED at
the end (even on failure) so fake outputs can't be mistaken for real data.

Refuses to run if data/resolutions.csv already exists (don't clobber real
resolutions after election day).
"""
import csv
import json
import subprocess
import sys
from collections import defaultdict

from pm_common import DATA, RESOLUTIONS, SNAPS, UNIVERSE, load_universe

RESULTS = DATA / "results.json"


def main():
    if RESOLUTIONS.exists():
        sys.exit("data/resolutions.csv already exists — refusing to overwrite it with fake data")
    if not UNIVERSE.exists():
        sys.exit("no data/universe.json — run snapshot.py first")

    universe = load_universe()["markets"]

    # latest snapshot gives each market's current price; favorite = fake winner
    latest = sorted(SNAPS.glob("*.csv"))[-1]
    price = {r["market_id"]: float(r["yes_price"] or 0) for r in csv.DictReader(open(latest))}
    by_event = defaultdict(list)
    for mid, meta in universe.items():
        by_event[meta["event_id"]].append(mid)
    fake_winner = {eid: max(mids, key=lambda m: price.get(m, 0.0)) for eid, mids in by_event.items()}

    fields = ["market_id", "event_id", "event_title", "race_type", "candidate", "checked_at",
              "closed", "resolved", "yes_won", "final_yes_price", "uma_statuses", "end_date", "error",
              "venue"]
    try:
        with open(RESOLUTIONS, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for mid, meta in universe.items():
                won = mid == fake_winner[meta["event_id"]]
                w.writerow({"market_id": mid, "event_id": meta["event_id"],
                            "event_title": meta["event_title"], "race_type": meta["race_type"],
                            "candidate": meta["candidate"], "checked_at": "FAKE", "closed": True,
                            "resolved": True, "yes_won": won,
                            "final_yes_price": 1.0 if won else 0.0, "uma_statuses": "[]",
                            "end_date": "", "error": "", "venue": meta["venue"]})

        proc = subprocess.run([sys.executable, "analyze.py"], capture_output=True, text=True)
        print(proc.stdout)
        if proc.returncode != 0:
            sys.exit(f"analyze.py failed:\n{proc.stderr}")

        out = json.loads(RESULTS.read_text())
        for venue, r in out["by_venue"].items():
            n_events = len({m["event_id"] for m in universe.values() if m["venue"] == venue})
            assert r["n_resolved"] == n_events, (venue, r["n_resolved"], n_events)
            assert r["n_unresolved"] == 0, venue
            assert r["by_days_out"], f"{venue}: no horizons scored — is history.csv/snapshots empty?"
            assert r["calibration"], f"{venue}: no calibration buckets"
            for h, row in r["by_days_out"].items():
                assert 0 <= row["hit_rate"] <= 1 and 0 <= row["brier"] <= 2, (venue, h, row)
                assert 0 <= row["brier_2way"] <= 2, (venue, h, row)
            print(f"OK {venue}: {r['n_resolved']} fake-resolved races scored across "
                  f"{len(r['by_days_out'])} horizons (fake favorite-always-wins data)")
        # top level is still Polymarket's scorecard, for existing readers
        assert out["n_resolved"] == out["by_venue"]["polymarket"]["n_resolved"]
        if "kalshi" in out["by_venue"]:
            o = out["overlap"]
            assert o and o["by_days_out"] and o["n_compared"] > 0, "overlap empty"
            for h, row in o["by_days_out"].items():
                assert row["n_favorite_disagree"] + row["n_favorite_unmapped"] <= row["n_priced"], (h, row)
            print(f"OK overlap: {o['n_compared']}/{o['n_shared_races']} shared races compared, "
                  f"{len(o['excluded'])} excluded")
    finally:
        RESOLUTIONS.unlink(missing_ok=True)
        RESULTS.unlink(missing_ok=True)
        print("cleaned up fake data/resolutions.csv and data/results.json")


if __name__ == "__main__":
    main()
