#!/usr/bin/env python3
"""Pull daily price history for every market in the universe from the CLOB.

This is what lets you score 'a month before' (Oct 4) even though snapshots
started Oct 15, and it gives accuracy-vs-days-out for free. Run once now and
once after resolution to top it up.

Writes data/history.csv: market_id, date, yes_price (last trade price that day).
"""
import csv
import json
import sys
import time
from datetime import datetime, timezone

from pm_common import CLOB, DATA, UNIVERSE, get

START = datetime(2026, 9, 1, tzinfo=timezone.utc)  # earlier than any sane "days out" window
OUT = DATA / "history.csv"


def main():
    if not UNIVERSE.exists():
        sys.exit("no data/universe.json — run snapshot.py first")
    universe = json.loads(UNIVERSE.read_text())["markets"]

    rows = []
    for i, (mid, meta) in enumerate(universe.items(), 1):
        tok = meta.get("yes_token_id")
        if not tok:
            continue
        try:
            # NB: passing startTs AND endTs 400s with "interval is too long" for
            # spans over ~a month; startTs alone means "until now", which is what
            # we want. fidelity=1440 (minutes) gives one point per day.
            hist = get(f"{CLOB}/prices-history", market=tok,
                       startTs=int(START.timestamp()), fidelity=1440)
        except Exception as e:
            print(f"{mid}: {e}", file=sys.stderr)
            continue
        daily = {}
        for pt in hist.get("history", []):
            d = datetime.fromtimestamp(pt["t"], tz=timezone.utc).strftime("%Y-%m-%d")
            daily[d] = pt["p"]  # last point of the day wins
        for d, p in sorted(daily.items()):
            rows.append({"market_id": mid, "date": d, "yes_price": p})
        if i % 50 == 0:
            print(f"{i}/{len(universe)}", file=sys.stderr)
            time.sleep(1)

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["market_id", "date", "yes_price"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} daily points across {len({r['market_id'] for r in rows})} markets -> {OUT}")


if __name__ == "__main__":
    main()
