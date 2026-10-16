#!/usr/bin/env python3
"""Score Polymarket's and Kalshi's midterm race markets against how they resolved.

Inputs:  data/universe.json, data/resolutions.csv, data/history.csv (and/or data/snapshots/*.csv),
         data/candidates.csv (party + cross-venue name matches, for the overlap section)
Output:  data/results.json (feed for the static site) + a console summary

Metrics, computed per venue at every available 'days before election' horizon:
  hit rate     did the highest-priced outcome win?  (this is roughly what the ad claims)
  Brier        multi-outcome Brier per race, averaged. 0 = perfect, 0.5 = coin flip on a 2-way race
  Brier 2-way  favorite vs the field, same 0-2 scale: 2*(p_fav - hit)^2. Independent of how
               many outcomes a venue lists, so it's the like-for-like number across venues
  calibration  market-level: of markets priced in bucket X, how often did YES win?

results.json keeps the original top-level keys for Polymarket (so existing readers
and the site's scorecard don't change meaning), plus:
  by_venue     {polymarket: {...}, kalshi: {...}} with the same metrics each
  overlap      races (race_keys) on both venues, scored head-to-head; see score_overlap()
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import date

from pm_common import DATA, HISTORY, RESOLUTIONS, SNAPS, load_universe

ELECTION_DAY = date(2026, 11, 3)
BUCKETS = [(0, .05), (.05, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .95), (.95, 1.01)]
VENUES = ("polymarket", "kalshi")
TABLE_HORIZONS = (30, 19, 7, 1, 0)
MATERIAL = 0.05  # a candidate who never traded above 5c can't swing a favorite comparison


def load_prices():
    """{date_str: {market_id: yes_price}} from history.csv, overridden by same-day snapshots.
    Market ids are unique across venues (numeric vs ticker), so one map holds both."""
    prices = defaultdict(dict)
    if HISTORY.exists():
        for r in csv.DictReader(open(HISTORY)):
            prices[r["date"]][r["market_id"]] = float(r["yes_price"])
    for snap in sorted(SNAPS.glob("*.csv")):
        for r in csv.DictReader(open(snap)):
            if r["yes_price"]:
                prices[snap.stem][r["market_id"]] = float(r["yes_price"])
    return prices


def priced_field(mids, pmap):
    """The race's prices on one day, or None unless the field is priced (a lone
    market is fine only if it's the race's only market)."""
    cand = {m: pmap[m] for m in mids if m in pmap}
    if len(cand) < 2 and not (len(cand) == 1 and len(mids) == 1):
        return None
    return cand


def brier(cand, winner):
    return sum((p - (1.0 if m == winner else 0.0)) ** 2 for m, p in cand.items())


def brier_2way(p_fav, hit):
    return 2 * (p_fav - (1.0 if hit else 0.0)) ** 2


def race_winners(races, res):
    """{race_id: winning market_id} for races with exactly one YES; plus the unresolved ids."""
    winners, unresolved = {}, []
    for rid, mids in races.items():
        won = [m for m in mids if res.get(m, {}).get("yes_won") == "True"]
        if len(won) == 1:
            winners[rid] = won[0]
        else:
            unresolved.append(rid)
    return winners, unresolved


def score_venue(universe, res, prices):
    """The original single-venue scorecard, for whichever markets are in `universe`."""
    races = defaultdict(list)
    for mid, meta in universe.items():
        races[meta["event_id"]].append(mid)
    winners, unresolved = race_winners(races, res)

    by_horizon = {}
    calib_points = []  # (days_out, price, won)
    race_table = []
    for d_str, pmap in sorted(prices.items()):
        days_out = (ELECTION_DAY - date.fromisoformat(d_str)).days
        if days_out < 0:
            continue
        hits, briers, briers2, fav_prices = [], [], [], []
        for eid, mids in races.items():
            if eid not in winners:
                continue
            cand = priced_field(mids, pmap)
            if cand is None:
                continue
            fav = max(cand, key=cand.get)
            hit = fav == winners[eid]
            b = brier(cand, winners[eid])
            hits.append(hit)
            briers.append(b)
            briers2.append(brier_2way(cand[fav], hit))
            fav_prices.append(cand[fav])
            for m, p in cand.items():
                calib_points.append((days_out, p, m == winners[eid]))
            if days_out in TABLE_HORIZONS:
                meta0 = universe[mids[0]]
                race_table.append({
                    "days_out": days_out, "event": meta0["event_title"], "race_type": meta0["race_type"],
                    "race_key": meta0["race_key"], "venue": meta0["venue"],
                    "favorite": universe[fav]["candidate"], "favorite_price": round(cand[fav], 3),
                    "winner": universe[winners[eid]]["candidate"], "hit": hit, "brier": round(b, 4),
                })
        if hits:
            by_horizon[days_out] = {
                "date": d_str, "n_races": len(hits),
                "hit_rate": round(sum(hits) / len(hits), 4),
                "brier": round(sum(briers) / len(briers), 4),
                "brier_2way": round(sum(briers2) / len(briers2), 4),
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

    return {
        "n_races_total": len(races), "n_resolved": len(winners), "n_unresolved": len(unresolved),
        "by_days_out": {str(k): by_horizon[k] for k in sorted(by_horizon, reverse=True)},
        "calibration_days_out": target, "calibration": calib,
        "races": race_table,
    }


def load_candidates():
    path = DATA / "candidates.csv"
    if not path.exists():
        sys.exit("no data/candidates.csv — run build_candidates.py first")
    return {r["market_id"]: r for r in csv.DictReader(open(path))}


def bundling_problem(person_mids, other_mids, cands, peak, other_venue):
    """Why this race can't be scored head-to-head, or None.

    The one structural mismatch that biases a hit-rate comparison: a party-level
    market on one venue that covers two or more live candidates the other venue
    prices separately (D-vs-D top-two races, an R incumbent and an R write-in).
    The party market then 'wins' no matter which of them wins, a free hit the
    per-candidate venue doesn't get. A live candidate with no known party and
    no name-matched market of their own on the other venue is treated the same
    way, since we can't rule it out."""
    other_parties = {cands[m]["party"] for m in other_mids
                     if cands[m]["resolves_on"] == "party" and cands[m]["party"]}
    if not other_parties:
        return None
    live = defaultdict(list)
    for m in person_mids:
        c = cands[m]
        if c["resolves_on"] != "person" or peak.get(m, 0) < MATERIAL:
            continue
        if c["match_market_id"] in other_mids:
            continue  # priced as their own outcome on both venues

        if not c["party"]:
            return f"live candidate {c['candidate']!r} ({m}) has no party in candidates.csv, so it can't be lined up with {other_venue}'s party markets"
        live[c["party"]].append(c["candidate"])
    for party, names in live.items():
        if len(names) > 1 and party in other_parties:
            return f"{other_venue} prices one {party} market for {len(names)} live {party} candidates: {', '.join(names)}"
    return None


def counterpart(pm_mid, k_mids, cands):
    """Kalshi market for the same outcome as Polymarket market `pm_mid`: the
    name-matched market if there is one, else the unique same-party market."""
    c = cands.get(pm_mid, {})
    if c.get("match_market_id") in k_mids:
        return c["match_market_id"]
    if c.get("party"):
        same = [m for m in k_mids if cands[m]["party"] == c["party"]]
        if len(same) == 1:
            return same[0]
    return None


def mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def score_overlap(universe, res, prices, cands):
    """Head-to-head on race_keys listed by both venues.

    Favorites are compared at the race level (each venue's highest-priced
    market), so per-party vs per-candidate listing doesn't matter for hit rate,
    except in races excluded by bundling_problem(). Price gap and favorite
    agreement need the same outcome on both venues, found via counterpart();
    they don't need resolutions, so they're reported for every priced race.
    """
    by_key = {v: defaultdict(list) for v in VENUES}
    for mid, m in universe.items():
        by_key[m["venue"]][m["race_key"]].append(mid)
    pm, ks = by_key["polymarket"], by_key["kalshi"]
    shared = sorted(set(pm) & set(ks))

    peak = defaultdict(float)
    for pmap in prices.values():
        for m, p in pmap.items():
            peak[m] = max(peak[m], p)

    excluded = {}
    for rk in shared:
        why = (bundling_problem(pm[rk], ks[rk], cands, peak, "kalshi")
               or bundling_problem(ks[rk], pm[rk], cands, peak, "polymarket"))
        if why:
            excluded[rk] = why
    compared = [rk for rk in shared if rk not in excluded]

    win_pm, _ = race_winners({rk: pm[rk] for rk in compared}, res)
    win_k, _ = race_winners({rk: ks[rk] for rk in compared}, res)

    by_horizon, disagreements = {}, {}
    for d_str, pmap in sorted(prices.items()):
        days_out = (ELECTION_DAY - date.fromisoformat(d_str)).days
        if days_out < 0:
            continue
        gaps, n_priced, n_disagree, n_unmapped = [], 0, 0, 0
        hits = {v: [] for v in VENUES}
        briers = {v: [] for v in VENUES}
        briers2 = {v: [] for v in VENUES}
        for rk in compared:
            a, b = priced_field(pm[rk], pmap), priced_field(ks[rk], pmap)
            if a is None or b is None:
                continue
            n_priced += 1
            fa, fb = max(a, key=a.get), max(b, key=b.get)
            cp = counterpart(fa, ks[rk], cands)
            if cp is None:
                n_unmapped += 1
            else:
                if cp != fb:
                    n_disagree += 1
                    if days_out in TABLE_HORIZONS:
                        disagreements.setdefault(str(days_out), []).append({
                            "race_key": rk, "polymarket_favorite": universe[fa]["candidate"],
                            "polymarket_price": round(a[fa], 3), "kalshi_favorite": universe[fb]["candidate"],
                            "kalshi_price": round(b[fb], 3)})
                if cp in b:
                    gaps.append(abs(a[fa] - b[cp]))
            if rk in win_pm and rk in win_k:
                for v, cand, fav, winner in (("polymarket", a, fa, win_pm[rk]), ("kalshi", b, fb, win_k[rk])):
                    hit = fav == winner
                    hits[v].append(hit)
                    briers[v].append(brier(cand, winner))
                    briers2[v].append(brier_2way(cand[fav], hit))
        if n_priced:
            by_horizon[days_out] = {
                "date": d_str, "n_priced": n_priced,
                "n_favorite_disagree": n_disagree, "n_favorite_unmapped": n_unmapped,
                "mean_abs_favorite_price_gap": mean(gaps), "n_price_gap": len(gaps),
                "n_races": len(hits["polymarket"]),
                "hit_rate": {v: mean(hits[v]) for v in VENUES},
                "brier": {v: mean(briers[v]) for v in VENUES},
                "brier_2way": {v: mean(briers2[v]) for v in VENUES},
            }

    return {
        "n_shared_races": len(shared), "n_compared": len(compared),
        "n_resolved_both": len(set(win_pm) & set(win_k)),
        "excluded": excluded,
        "only_polymarket": sorted(set(pm) - set(ks)),
        "only_kalshi": sorted(set(ks) - set(pm)),
        "by_days_out": {str(k): by_horizon[k] for k in sorted(by_horizon, reverse=True)},
        "favorite_disagreements": disagreements,
    }


def print_venue(name, r):
    print(f"\n[{name}] races: {r['n_races_total']}  resolved: {r['n_resolved']}  unresolved: {r['n_unresolved']}")
    print(f"{'days out':>8} {'date':>11} {'n':>5} {'hit rate':>9} {'brier':>7} {'brier2':>7}")
    for h, row in r["by_days_out"].items():
        print(f"{h:>8} {row['date']:>11} {row['n_races']:>5} {row['hit_rate']:>9.1%} {row['brier']:>7.3f} {row['brier_2way']:>7.3f}")
    if r["calibration"]:
        print(f"calibration at {r['calibration_days_out']} days out (market-level):")
        for c in r["calibration"]:
            print(f"  {c['bucket']:>10}  n={c['n']:>4}  priced {c['mean_price']:.2f}  won {c['win_rate']:.1%}")


def print_overlap(o):
    print(f"\n[overlap] shared races: {o['n_shared_races']}  compared: {o['n_compared']}  "
          f"excluded: {len(o['excluded'])}  resolved on both: {o['n_resolved_both']}")
    print(f"  only polymarket ({len(o['only_polymarket'])}): {', '.join(o['only_polymarket'])}")
    print(f"  only kalshi ({len(o['only_kalshi'])}): {', '.join(o['only_kalshi'])}")
    for rk, why in o["excluded"].items():
        print(f"  excluded {rk}: {why}")
    print(f"{'days out':>8} {'priced':>6} {'disagree':>8} {'unmapped':>8} {'|gap|':>6} {'n':>4} "
          f"{'hit pm':>7} {'hit k':>7} {'b2 pm':>6} {'b2 k':>6}")
    f = lambda x, s: format(x, s) if x is not None else "-"
    for h, r in o["by_days_out"].items():
        print(f"{h:>8} {r['n_priced']:>6} {r['n_favorite_disagree']:>8} {r['n_favorite_unmapped']:>8} "
              f"{f(r['mean_abs_favorite_price_gap'], '.3f'):>6} {r['n_races']:>4} "
              f"{f(r['hit_rate']['polymarket'], '.1%'):>7} {f(r['hit_rate']['kalshi'], '.1%'):>7} "
              f"{f(r['brier_2way']['polymarket'], '.3f'):>6} {f(r['brier_2way']['kalshi'], '.3f'):>6}")


def main():
    if not RESOLUTIONS.exists():
        sys.exit("no data/resolutions.csv — run resolve.py first")
    universe = load_universe()["markets"]
    res = {r["market_id"]: r for r in csv.DictReader(open(RESOLUTIONS))}
    prices = load_prices()

    by_venue = {}
    for v in VENUES:
        sub = {mid: m for mid, m in universe.items() if m["venue"] == v}
        if sub:
            by_venue[v] = score_venue(sub, res, prices)
    overlap = score_overlap(universe, res, prices, load_candidates()) if len(by_venue) == 2 else None

    out = {"election_day": ELECTION_DAY.isoformat(), **by_venue.get("polymarket", {}),
           "by_venue": by_venue, "overlap": overlap}
    (DATA / "results.json").write_text(json.dumps(out, indent=1))

    for v, r in by_venue.items():
        print_venue(v, r)
    if overlap:
        print_overlap(overlap)


if __name__ == "__main__":
    main()
