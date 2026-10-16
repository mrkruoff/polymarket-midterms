#!/usr/bin/env python3
"""Pull daily Kalshi candlesticks from Sept 1 for every Kalshi market in the universe.

The Kalshi twin of backfill_history.py: replaces the venue=kalshi rows of
data/history.csv. yes_price follows Polymarket's displayed-price rule
(kalshi_common.display_price) on the candle's closing yes bid and ask: their
midpoint, or the last trade when the spread is over 10c. Bid, ask and last
trade are kept in their own columns. A candle with no
trades has no closing trade; last_price is then the most recent earlier one.

Dates: a daily candle ends at 04:00 UTC (midnight ET) and is labeled with the
UTC date of its end, matching Polymarket's ~00:00 UTC daily sample for the same
date. Kalshi emits no candle for a day on which neither the book nor trades
changed, so such gaps are forward-filled from the previous candle's close (the
book really was unchanged). Run once now and again after resolution to top it up.
"""
import sys
from datetime import date, datetime, timedelta, timezone

import requests

from kalshi_common import display_price, dollars, is_not_found, kget
from pm_common import HISTORY, load_universe, write_history

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def candles(series, ticker, start_ts, end_ts):
    params = dict(start_ts=start_ts, end_ts=end_ts, period_interval=1440)
    try:
        return kget(f"/series/{series}/markets/{ticker}/candlesticks", **params)["candlesticks"]
    except requests.HTTPError as e:
        if not is_not_found(e):
            raise
    # settled markets move to /historical; this path is a best guess from the
    # /historical/markets/{ticker} pattern and is unverified before Nov 3
    return kget(f"/historical/markets/{ticker}/candlesticks", **params)["candlesticks"]


def forward_fill(rows):
    """Fill each market's missing days, from its first candle through the latest
    date any market has, with its previous day's row."""
    if not rows:
        return rows
    last_day = date.fromisoformat(max(r["date"] for r in rows))
    by_market = {}
    for r in rows:
        by_market.setdefault(r["market_id"], {})[r["date"]] = r
    out = []
    for mid, days in by_market.items():
        d, prev = date.fromisoformat(min(days)), None
        while d <= last_day:
            key = d.isoformat()
            row = days.get(key)
            if row and row["last_price"] is None and prev:
                row["last_price"] = prev["last_price"]  # no trade that day: last trade stands
            prev = row or {**prev, "date": key}
            out.append(prev)
            d += timedelta(days=1)
    return out


def main():
    universe = load_universe()
    if not universe:
        sys.exit("no data/universe.json — run kalshi_snapshot.py first")
    markets = {mid: m for mid, m in universe["markets"].items() if m["venue"] == "kalshi"}
    if not markets:
        sys.exit("no Kalshi markets in the universe — run kalshi_snapshot.py first")
    start_ts, end_ts = int(START.timestamp()), int(datetime.now(timezone.utc).timestamp())

    rows, failed = [], []
    for i, (mid, meta) in enumerate(markets.items(), 1):
        try:
            cs = candles(meta["series_ticker"], mid, start_ts, end_ts)
        except Exception as e:
            failed.append(mid)
            print(f"{mid}: {e}", file=sys.stderr)
            continue
        for c in cs:
            d = datetime.fromtimestamp(c["end_period_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
            bid = dollars((c.get("yes_bid") or {}).get("close_dollars"))
            ask = dollars((c.get("yes_ask") or {}).get("close_dollars"))
            last = dollars((c.get("price") or {}).get("close_dollars"))
            rows.append({"market_id": mid, "date": d, "yes_price": None, "venue": "kalshi",
                         "yes_bid": bid, "yes_ask": ask, "last_price": last})
        if i % 100 == 0:
            print(f"{i}/{len(markets)}", file=sys.stderr)

    # price after filling, so a no-trade day's wide spread falls back to the
    # last trade from an earlier day
    rows = forward_fill(rows)
    for r in rows:
        r["yes_price"] = display_price(r["yes_bid"], r["yes_ask"], r["last_price"])
    rows = [r for r in rows if r["yes_price"] is not None]
    write_history(rows, "kalshi")
    print(f"{len(rows)} daily points across {len({r['market_id'] for r in rows})}/{len(markets)} "
          f"kalshi markets -> {HISTORY}" + (f"; {len(failed)} FAILED" if failed else ""))


if __name__ == "__main__":
    main()
