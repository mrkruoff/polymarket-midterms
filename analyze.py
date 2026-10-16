#!/usr/bin/env python3
"""Score Polymarket's midterm race markets against how they resolved.

Inputs:  data/universe.json, data/resolutions.csv, data/history.csv (and/or data/snapshots/*.csv)
Output:  data/results.json (feed for the static site) + a console summary

Metrics, computed at every available 'days before election' horizon:
  hit rate     did the highest-priced candidate win?  (this is roughly what the ad claims)
  Brier        multi-outcome Brier per race, averaged. 0 = perfect, 0.5 = coin flip on a 2-way race
  calibration  candidate-level: of markets priced in bucket X, how often did YES win?
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import date

from pm_common import DATA, RESOLUTIONS, SNAPS, UNIVERSE

ELECTION_DAY = date(2026, 11, 3)
BUCKETS = [(0, .05), (.05, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .95), (.95, 1.01)]


def load_prices():
    """{date_str: {market_id: yes_price}} from history.csv, overridden by same-day snapshots."""
    prices = defaultdict(dict)
    hist = DATA / "history.csv"
    if hist.exists():
        for r in csv.DictReader(open(hist)):
            prices[r["date"]][r["market_id"]] = float(r["yes_price"])
    for snap in sorted(SNAPS.glob("*.csv")):
        for r in csv.DictReader(open(snap)):
            if r["yes_price"]:
                prices[snap.stem][r["market_id"]] = float(r["yes_price"])
    return prices


def main():
    if not RESOLUTIONS.exists():
        sys.exit("no data/resolutions.csv — run resolve.py first")
    universe = json.loads(UNIVERSE.read_text())["markets"]
    res = {r["market_id"]: r for r in csv.DictReader(open(RESOLUTIONS))}
    prices = load_prices()

    # group markets into races (events) and find each race's winner
    races = defaultdict(list)
    for mid, meta in universe.items():
        races[meta["event_id"]].append(mid)
    winners, unresolved = {}, []
    for eid, mids in races.items():
        won = [m for m in mids if res.get(m, {}).get("yes_won") == "True"]
        if len(won) == 1:
            winners[eid] = won[0]
        else:
            unresolved.append(eid)

    by_horizon = {}
    calib_points = []  # (days_out, price, won)
    race_table = []
    for d_str, pmap in sorted(prices.items()):
        d = date.fromisoformat(d_str)
        days_out = (ELECTION_DAY - d).days
        if days_out < 0:
            continue
        hits, briers, fav_prices = [], [], []
        for eid, mids in races.items():
            if eid not in winners:
                continue
            cand = {m: pmap[m] for m in mids if m in pmap}
            if len(cand) < 2 and not (len(cand) == 1 and len(mids) == 1):
                continue  # need the full field priced on this day
            fav = max(cand, key=cand.get)
            hit = fav == winners[eid]
            brier = sum((p - (1.0 if m == winners[eid] else 0.0)) ** 2 for m, p in cand.items())
            hits.append(hit)
            briers.append(brier)
            fav_prices.append(cand[fav])
            for m, p in cand.items():
                calib_points.append((days_out, p, m == winners[eid]))
            if days_out in (30, 19, 7, 1, 0):
                race_table.append({
                    "days_out": days_out, "event": universe[mids[0]]["event_title"],
                    "race_type": universe[mids[0]]["race_type"],
                    "favorite": universe[fav]["candidate"], "favorite_price": round(cand[fav], 3),
                    "winner": universe[winners[eid]]["candidate"], "hit": hit, "brier": round(brier, 4),
                })
        if hits:
            by_horizon[days_out] = {
                "date": d_str, "n_races": len(hits),
                "hit_rate": round(sum(hits) / len(hits), 4),
                "brier": round(sum(briers) / len(briers), 4),
                # context for the hit rate: how many races were foregone conclusions?
                "share_favorites_over_95": round(sum(p >= .95 for p in fav_prices) / len(hits), 4),
                "hit_rate_competitive_under_80": (
                    round(sum(h for h, p in zip(hits, fav_prices) if p < .8) / max(1, sum(p < .8 for p in fav_prices)), 4)
                    if any(p < .8 for p in fav_prices) else None),
            }

    # calibration at the horizon closest to 30 days out from below (i.e. the
    # largest available days_out <= 30), falling back to the earliest we have
    horizons = sorted(by_horizon)
    target = next((h for h in sorted(horizons, reverse=True) if h <= 30), horizons[-1] if horizons else None)
    calib = []
    if target is not None:
        pts = [(p, w) for h, p, w in calib_points if h == target]
        for lo, hi in BUCKETS:
            b = [(p, w) for p, w in pts if lo <= p < hi]
            if b:
                calib.append({"bucket": f"{lo:.2f}-{min(hi,1):.2f}", "n": len(b),
                              "mean_price": round(sum(p for p, _ in b) / len(b), 3),
                              "win_rate": round(sum(w for _, w in b) / len(b), 3)})

    out = {
        "election_day": ELECTION_DAY.isoformat(),
        "n_races_total": len(races), "n_resolved": len(winners), "n_unresolved": len(unresolved),
        "by_days_out": {str(k): by_horizon[k] for k in sorted(by_horizon, reverse=True)},
        "calibration_days_out": target, "calibration": calib,
        "races": race_table,
    }
    (DATA / "results.json").write_text(json.dumps(out, indent=1))

    print(f"races: {len(races)}  resolved: {len(winners)}  unresolved: {len(unresolved)}")
    print(f"{'days out':>8} {'date':>11} {'n':>5} {'hit rate':>9} {'brier':>7}")
    for h in sorted(by_horizon, reverse=True):
        r = by_horizon[h]
        print(f"{h:>8} {r['date']:>11} {r['n_races']:>5} {r['hit_rate']:>9.1%} {r['brier']:>7.3f}")
    if calib:
        print(f"\ncalibration at {target} days out (candidate-level):")
        for c in calib:
            print(f"  {c['bucket']:>10}  n={c['n']:>4}  priced {c['mean_price']:.2f}  won {c['win_rate']:.1%}")


if __name__ == "__main__":
    main()
