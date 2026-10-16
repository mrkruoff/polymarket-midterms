#!/usr/bin/env python3
"""After election day: re-poll every market in data/universe.json and record how
its venue resolved it. Safe to re-run; unresolved markets just stay unresolved
until the next run (close races can take days).

Writes data/resolutions.csv. A market counts as resolved when:
  polymarket  it is closed and outcomePrices has collapsed to 1/0
  kalshi      status == "settled" or result is "yes"/"no"; yes_won = result == "yes".
              Settled markets eventually move to /historical/markets/{ticker};
              kalshi_common.get_market() falls back to it on a 404.
"""
import csv
import json
import sys
from datetime import datetime, timezone

from kalshi_common import dollars, get_market
from pm_common import GAMMA, RESOLUTIONS, get, jlist, load_universe, yes_price

FIELDS = ["market_id", "event_id", "event_title", "race_type", "candidate", "checked_at",
          "closed", "resolved", "yes_won", "final_yes_price", "uma_statuses", "end_date", "error",
          "venue"]


def resolve_polymarket(mid):
    m = get(f"{GAMMA}/markets/{mid}")
    p = yes_price(m)
    is_resolved = bool(m.get("closed")) and p is not None and p in (0.0, 1.0)
    return {
        "closed": m.get("closed"),
        "resolved": is_resolved,
        "yes_won": (p == 1.0) if is_resolved else None,
        "final_yes_price": p,
        "uma_statuses": json.dumps(jlist(m.get("umaResolutionStatuses"))),
        "end_date": m.get("endDate"),
    }


def resolve_kalshi(mid):
    m = get_market(mid)
    result = m.get("result") or ""
    is_resolved = m.get("status") == "settled" or result in ("yes", "no")
    return {
        "closed": m.get("status") != "active",
        "resolved": is_resolved,
        "yes_won": (result == "yes") if is_resolved else None,
        "final_yes_price": dollars(m.get("last_price_dollars")),
        "uma_statuses": "",
        "end_date": m.get("close_time"),
    }


RESOLVERS = {"polymarket": resolve_polymarket, "kalshi": resolve_kalshi}


def main():
    universe = load_universe()
    if not universe:
        sys.exit("no data/universe.json — run snapshot.py first")
    universe = universe["markets"]
    now = datetime.now(timezone.utc).isoformat()

    rows, resolved = [], 0
    for mid, meta in universe.items():
        base = {"market_id": mid, "event_id": meta["event_id"], "event_title": meta["event_title"],
                "race_type": meta["race_type"], "candidate": meta["candidate"], "checked_at": now,
                "venue": meta["venue"], "error": ""}
        try:
            r = RESOLVERS[meta["venue"]](mid)
        except Exception as e:  # keep going; record the failure
            rows.append({**base, "error": str(e)})
            continue
        resolved += r["resolved"]
        rows.append({**base, **r})

    with open(RESOLUTIONS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{resolved}/{len(rows)} markets resolved -> {RESOLUTIONS}")


if __name__ == "__main__":
    main()
