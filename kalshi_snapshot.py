#!/usr/bin/env python3
"""Snapshot current Kalshi prices for every event in data/kalshi_events.json.

The Kalshi twin of snapshot.py, writing to the same files with venue=kalshi:
  data/raw/kalshi/<date>.json   full event+market objects as returned (gitignored)
  data/snapshots/<date>.csv     one row per market; only venue=kalshi rows are replaced
  data/universe.json            Kalshi markets added (append-only), keyed by market ticker

yes_price follows Polymarket's displayed-price rule (kalshi_common.display_price):
bid/ask midpoint, or last trade when the spread is over 10c. Bid, ask and last
trade are recorded separately (best_bid, best_ask, last_price). volume is Kalshi's
volume_fp, a contract count, not dollars like Polymarket's.

Usage: python kalshi_snapshot.py
"""
import json
import sys
from datetime import datetime, timezone

import requests

from kalshi_common import KALSHI_EVENTS, KRAW, display_price, dollars, kget, party_from_ticker
from pm_common import load_universe, save_universe, write_snapshot


def build_rows(events, now_iso):
    rows = []
    for meta, ev in events:
        for m in ev.get("markets", []):
            bid, ask = dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars"))
            last = dollars(m.get("last_price_dollars"))
            rows.append({
                "snapshot_at": now_iso,
                "event_id": ev["event_ticker"],
                "event_title": (ev.get("title") or "").strip(),
                "race_type": meta["race_type"],
                "market_id": m["ticker"],
                "candidate": m.get("yes_sub_title"),
                "question": m.get("title"),
                "yes_price": display_price(bid, ask, last),
                "best_bid": bid,
                "best_ask": ask,
                "volume": m.get("volume_fp"),
                "end_date": m.get("close_time"),
                "closed": m.get("status") != "active",
                "venue": "kalshi",
                "race_key": meta["race_key"],
                "last_price": last,
                # universe-only fields (DictWriter ignores them)
                "series_ticker": meta["series_ticker"],
            })
    return rows


def main():
    if not KALSHI_EVENTS.exists():
        sys.exit("no data/kalshi_events.json — run build_kalshi_events.py first")
    curated = json.loads(KALSHI_EVENTS.read_text())
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")

    events, failed = [], []
    for meta in curated:
        try:
            ev = kget(f"/events/{meta['event_ticker']}", with_nested_markets="true")["event"]
        except requests.HTTPError as e:
            failed.append(f"{meta['event_ticker']}: {e}")
            continue
        events.append((meta, ev))
    for f in failed:
        print(f"WARNING {f}", file=sys.stderr)

    (KRAW / f"{stamp}.json").write_text(json.dumps(
        {"fetched_at": now.isoformat(), "events": [ev for _, ev in events]}))

    rows = build_rows(events, now.isoformat())
    if not rows:
        sys.exit("no Kalshi rows produced")
    write_snapshot(stamp, rows, "kalshi")

    universe = load_universe() or {"created": now.isoformat(), "markets": {}}
    added = 0
    for r in rows:
        if r["market_id"] not in universe["markets"]:
            universe["markets"][r["market_id"]] = {
                "event_id": r["event_id"], "event_title": r["event_title"],
                "race_type": r["race_type"], "candidate": r["candidate"], "first_seen": stamp,
                "venue": "kalshi", "race_key": r["race_key"],
                "series_ticker": r["series_ticker"], "event_ticker": r["event_id"],
                "party": party_from_ticker(r["market_id"]),
            }
            added += 1
    save_universe(universe)

    counts = {}
    for r in rows:
        counts[r["race_type"]] = counts.get(r["race_type"], 0) + 1
    n_k = sum(m["venue"] == "kalshi" for m in universe["markets"].values())
    print(f"{stamp}: {len(rows)} kalshi markets in {len(events)} events {counts}; "
          f"universe +{added} -> {n_k} kalshi" + (f"; {len(failed)} events FAILED" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
