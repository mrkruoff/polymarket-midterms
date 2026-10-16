#!/usr/bin/env python3
"""Condense universe + history + snapshots (+ results.json when it exists) into
docs/data.json, the feed for the static dashboard in docs/. Run after snapshot.py;
the daily launchd job does both.

Size control: per race, only candidates whose price ever reached MIN_PEAK are
given a time series (capped at MAX_SERIES, always at least the top two), prices
rounded to 3 decimals, one shared date axis. Everything else stays reachable in
the data/ files; this is a view, not the record.

Venues: every race carries venue and race_key, and every candidate its market
id and party (data/candidates.csv). A race listed on both venues gets twin =
the other venue's race id, and each candidate twin = the other venue's market
for the same outcome (analyze.counterpart), so the site can overlay the two.
Volume units differ: Polymarket dollars, Kalshi contracts.
"""
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analyze import counterpart, load_prices
from pm_common import DATA, SNAPS, load_universe

DOCS = Path(__file__).resolve().parent / "docs"
ELECTION_DAY = "2026-11-03"
MIN_PEAK = 0.02   # a candidate that never traded above 2c is a noise line
MAX_SERIES = 4    # series cap per chart (dataviz: past 4, fold or facet)


def link_twins(races, cands):
    by_key = defaultdict(dict)
    for r in races:
        by_key[r["race_key"]][r["venue"]] = r
    for pair in by_key.values():
        pm, k = pair.get("polymarket"), pair.get("kalshi")
        if not (pm and k) or not cands:
            continue
        pm["twin"], k["twin"] = k["id"], pm["id"]
        k_ids = {c["id"] for c in k["candidates"]}
        for c in pm["candidates"]:
            if (t := counterpart(c["id"], k_ids, cands)):
                c["twin"] = t
                next(kc for kc in k["candidates"] if kc["id"] == t)["twin"] = c["id"]


def main():
    universe = load_universe()["markets"]
    cpath = DATA / "candidates.csv"
    cands = {r["market_id"]: r for r in csv.DictReader(open(cpath))} if cpath.exists() else {}
    prices = load_prices()  # {date: {market_id: yes_price}}, snapshots override history
    dates = sorted(prices)

    volume = {}  # latest snapshot per venue (a venue may have skipped today)
    for snap in sorted(SNAPS.glob("*.csv")):
        for r in csv.DictReader(open(snap)):
            volume[r["market_id"]] = float(r["volume"] or 0)

    by_event = defaultdict(list)
    for mid, meta in universe.items():
        by_event[meta["event_id"]].append((mid, meta))

    races = []
    for eid, markets in by_event.items():
        cands_ = []
        for mid, meta in markets:
            series = [prices[d].get(mid) for d in dates]
            cur = next((v for v in reversed(series) if v is not None), None)
            peak = max((v for v in series if v is not None), default=0.0)
            cands_.append({
                "id": mid,
                "name": meta["candidate"],
                "party": cands.get(mid, {}).get("party") or None,
                "price": round(cur, 3) if cur is not None else None,
                "volume": round(volume.get(mid, 0)),
                "peak": peak,
                "series": [round(v, 3) if v is not None else None for v in series],
            })
        cands_.sort(key=lambda c: -(c["price"] or 0))
        kept = [c for c in cands_ if c["peak"] >= MIN_PEAK][:MAX_SERIES]
        if len(kept) < 2:
            kept = cands_[:2]
        for c in kept:
            del c["peak"]
        meta0 = markets[0][1]
        races.append({
            "id": eid,
            "title": meta0["event_title"].strip(),
            "type": meta0["race_type"],
            "venue": meta0["venue"],
            "race_key": meta0["race_key"],
            "n_candidates": len(markets),
            "volume": round(sum(volume.get(mid, 0) for mid, _ in markets)),
            "candidates": kept,
        })
    races.sort(key=lambda r: -r["volume"])
    link_twins(races, cands)

    results_path = DATA / "results.json"
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "election_day": ELECTION_DAY,
        "venues": ["polymarket", "kalshi"],
        "dates": dates,
        "races": races,
        "results": json.loads(results_path.read_text()) if results_path.exists() else None,
    }
    DOCS.mkdir(exist_ok=True)
    path = DOCS / "data.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(races)} races, {len(dates)} dates -> {path} ({path.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
