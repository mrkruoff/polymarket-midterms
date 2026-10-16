#!/usr/bin/env python3
"""Pull daily price history for every market in the universe from the CLOB.

This is what lets you score 'a month before' (Oct 4) even though snapshots
started Oct 15, and it gives accuracy-vs-days-out for free. Run once now and
once after resolution to top it up.

Writes the venue=polymarket rows of data/history.csv: market_id, date, yes_price
(Polymarket's displayed price at the day's last sample; see README on midpoints).
"""
import sys
import time
from datetime import datetime, timezone

from pm_common import CLOB, HISTORY, get, load_universe, write_history

START = datetime(2026, 9, 1, tzinfo=timezone.utc)  # earlier than any sane "days out" window


def main():
    universe = load_universe()
    if not universe:
        sys.exit("no data/universe.json — run snapshot.py first")
    universe = {mid: m for mid, m in universe["markets"].items() if m["venue"] == "polymarket"}

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
            rows.append({"market_id": mid, "date": d, "yes_price": p, "venue": "polymarket"})
        if i % 50 == 0:
            print(f"{i}/{len(universe)}", file=sys.stderr)
            time.sleep(1)

    write_history(rows, "polymarket")  # Kalshi rows in history.csv are left alone
    print(f"{len(rows)} daily points across {len({r['market_id'] for r in rows})} markets -> {HISTORY}")


if __name__ == "__main__":
    main()
