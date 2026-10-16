#!/usr/bin/env python3
"""Snapshot current Polymarket prices for 2026 midterm races.

Run daily (cron) from now through election day. Each run writes:
  data/raw/<date>.json          full event+market objects, unfiltered (keep everything)
  data/snapshots/<date>.csv     one row per candidate-market in a senate/house/governor race
  data/universe.json            frozen list of markets to score; created on first run,
                                extended (never shrunk) on later runs

Usage: python snapshot.py [--include-closed]
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone

from pm_common import (GAMMA, RAW, SNAPS, UNIVERSE, TAG_LABEL_PATTERNS, classify_event, get,
                       is_placeholder_market, jlist, yes_price, yes_token_id)


def find_tag_ids():
    # /tags caps each page at 100 regardless of limit, so paginate.
    found, offset = {}, 0
    while True:
        tags = get(f"{GAMMA}/tags", limit=100, offset=offset)
        if not tags:
            break
        for t in tags:
            label = (t.get("label") or "")
            if any(re.search(p, label, re.I) for p in TAG_LABEL_PATTERNS):
                found[t["id"]] = label
        if len(tags) < 100:
            break
        offset += 100
    return found


def fetch_events(tag_id, include_closed):
    events, offset = [], 0
    while True:
        params = dict(tag_id=tag_id, limit=100, offset=offset, order="id", ascending="false")
        if not include_closed:
            params["closed"] = "false"
        page = get(f"{GAMMA}/events", **params)
        if not page:
            break
        events.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return events


HOUSE_INDIV = re.compile(r"^([A-Z]{2}-(?:AL|\d{1,2})) House Election Winner \((?:by )?individual\)$", re.I)
HOUSE_PLAIN = re.compile(r"^([A-Z]{2}-(?:AL|\d{1,2})) House Election Winner$", re.I)


def build_rows(events, now_iso):
    """Flat candidate-market rows for every scoreable race in `events`."""
    # A few CA districts have a duplicate "(Individual)" winner event alongside
    # the party-level one; keep it only where it's the sole event for the seat
    # (CA-40's R-vs-R race has no party-level market at all).
    plain_districts = {m.group(1).upper() for ev in events
                       if (m := HOUSE_PLAIN.match((ev.get("title") or "").strip()))}
    rows = []
    for ev in events:
        title = (ev.get("title") or "").strip()
        race_type = classify_event(title)
        if race_type not in ("senate", "governor", "house"):
            continue
        indiv = HOUSE_INDIV.match(title)
        if indiv and indiv.group(1).upper() in plain_districts:
            continue
        for m in ev.get("markets", []):
            if is_placeholder_market(m):
                continue
            rows.append({
                "snapshot_at": now_iso,
                "event_id": ev["id"],
                "event_slug": ev.get("slug"),
                "event_title": ev.get("title"),
                "race_type": race_type,
                "market_id": m["id"],
                "candidate": m.get("groupItemTitle") or m.get("question"),
                "question": m.get("question"),
                "yes_price": yes_price(m),
                "best_bid": m.get("bestBid"),
                "best_ask": m.get("bestAsk"),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
                "end_date": m.get("endDate"),
                "closed": m.get("closed"),
                "neg_risk": ev.get("negRisk"),
                "condition_id": m.get("conditionId"),
                "yes_token_id": yes_token_id(m),
            })
    return rows


def write_outputs(rows, stamp, now_iso):
    """Write the day's CSV and extend the universe; returns the summary line."""
    if not rows:
        sys.exit("no race rows produced — check classify_event() against data/raw")
    with open(SNAPS / f"{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    # universe: the set of markets we commit to scoring. Append-only so a market
    # that disappears from the listing later is still tracked.
    universe = json.loads(UNIVERSE.read_text()) if UNIVERSE.exists() else {"created": now_iso, "markets": {}}
    added = 0
    for r in rows:
        if r["market_id"] not in universe["markets"]:
            universe["markets"][r["market_id"]] = {
                "event_id": r["event_id"], "event_title": r["event_title"],
                "race_type": r["race_type"], "candidate": r["candidate"],
                "first_seen": stamp, "yes_token_id": r["yes_token_id"],
            }
            added += 1
    UNIVERSE.write_text(json.dumps(universe, indent=1))

    counts = {}
    for r in rows:
        counts[r["race_type"]] = counts.get(r["race_type"], 0) + 1
    return f"{stamp}: {len(rows)} candidate markets {counts}; universe +{added} -> {len(universe['markets'])}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-closed", action="store_true",
                    help="also pull closed events (use after election day)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")

    tag_ids = find_tag_ids()
    print(f"tags: {tag_ids}", file=sys.stderr)

    by_id = {}
    for tid in tag_ids:
        for ev in fetch_events(tid, args.include_closed):
            by_id[ev["id"]] = ev
    events = list(by_id.values())
    print(f"{len(events)} unique events", file=sys.stderr)

    # raw dump — everything, so the filter can be changed later without re-fetching
    (RAW / f"{stamp}.json").write_text(json.dumps(
        {"fetched_at": now.isoformat(), "tag_ids": tag_ids, "events": events}))

    rows = build_rows(events, now.isoformat())
    print(write_outputs(rows, stamp, now.isoformat()))


if __name__ == "__main__":
    main()
