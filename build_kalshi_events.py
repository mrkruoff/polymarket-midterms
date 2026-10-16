#!/usr/bin/env python3
"""Build data/kalshi_events.json, the curated list of Kalshi 2026 winner events.

Input is data/kalshi_scraped.txt (event tickers linked from Kalshi's
Senate/governor/House category pages). Each is fetched from the API and kept
only if it is a mutually exclusive 2026 general-election winner event whose
title maps to a race_key. Re-run after editing the scraped list; the snapshot
scripts only ever read the JSON this writes.

Usage: python build_kalshi_events.py
"""
import json
import re
import sys
from collections import Counter

import requests

from kalshi_common import KALSHI_EVENTS, KALSHI_SCRAPED, kget
from pm_common import race_key

# Kalshi's own winner-event titles: "Texas Senate winner?", "Ohio Governor
# winner?", "California Governor winner? (Person)", "MN-05 House winner?".
# Props on the same pages ("Will anyone win ... outright?", "Which House races
# will be won outright?") fail this and are also not mutually_exclusive.
WINNER_TITLE = re.compile(r"^.+ (Senate|Governor|House) winner\?( \((Person|Party)\))?$")
# Year lives in the ticker: SENATETX-26, KXHOUSERACE-MN05-26, KXSENATELA-26NOV,
# KXCAELECTION-2607 (CA-07). sub_title isn't reliable ("In 2026" vs "MN-05").
CYCLE_2026 = re.compile(r"-26(?:NOV|\d\d)?$")
RACE_TYPE = {"Senate": "senate", "Governor": "governor", "House": "house"}

# Races Kalshi lists twice. Keep the per-candidate event so the comparison with
# Polymarket (also per candidate) is like-for-like; the party event is a
# coarser view of the same race.
PREFERRED = {
    "gov-CA": "KXGOVCA-26",   # vs GOVPARTYCA-26 (D/R)
    "gov-AK": "KXGOVAK-26",   # vs KXGOVPARTYAK-26 (D/R); 16 named candidates
}


def main():
    scraped = []
    for line in KALSHI_SCRAPED.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            page, ticker = line.split()
            scraped.append((page, ticker))

    kept, dropped = {}, []
    for page, ticker in scraped:
        try:
            ev = kget(f"/events/{ticker}", with_nested_markets="true")["event"]
        except requests.HTTPError as e:
            dropped.append((ticker, f"HTTP {e.response.status_code}"))
            continue
        title = (ev.get("title") or "").strip()
        m = WINNER_TITLE.match(title)
        key = race_key(title)
        if not ev.get("mutually_exclusive"):
            dropped.append((ticker, f"not mutually exclusive: {title}"))
        elif not m or not key:
            dropped.append((ticker, f"not a winner event: {title}"))
        elif not CYCLE_2026.search(ticker):
            dropped.append((ticker, "not the 2026 cycle"))
        elif not ev.get("markets"):
            dropped.append((ticker, "no markets"))
        else:
            kept.setdefault(key, []).append({
                "event_ticker": ev["event_ticker"], "series_ticker": ev["series_ticker"],
                "race_type": RACE_TYPE[m[1]], "race_key": key, "title": title,
                "n_markets": len(ev["markets"]),
            })

    events = []
    for key, evs in sorted(kept.items()):
        if len(evs) > 1:
            pick = PREFERRED.get(key)
            if pick not in {e["event_ticker"] for e in evs}:
                sys.exit(f"{key} listed twice with no preference: {[e['event_ticker'] for e in evs]}")
            for e in evs:
                if e["event_ticker"] != pick:
                    dropped.append((e["event_ticker"], f"duplicate of {pick} for {key}"))
            evs = [e for e in evs if e["event_ticker"] == pick]
        events.append(evs[0])

    KALSHI_EVENTS.write_text(json.dumps(events, indent=1))
    for t, why in dropped:
        print(f"  dropped {t}: {why}")
    for e in events:
        print(f"  {e['race_key']:<18} {e['event_ticker']:<22} {e['n_markets']} mkts  {e['title']}")
    counts = Counter(e["race_type"] for e in events)
    print(f"{len(events)} events {dict(counts)} -> {KALSHI_EVENTS}")


if __name__ == "__main__":
    main()
