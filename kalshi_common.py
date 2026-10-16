"""Kalshi helpers: API access, price parsing, party from ticker suffix.

Verified against the live API on 2026-10-16 (public, no auth):
  GET /events/{event_ticker}?with_nested_markets=true   reliable; the only lookup we use
  GET /series/{series}/markets/{ticker}/candlesticks    daily OHLC (period_interval=1440)
  GET /historical/markets/{ticker}                      where settled markets end up
/events?series_ticker= and /markets?series_ticker= ignore the filter or come back
empty, so discovery is a curated list (data/kalshi_events.json), not a search.
Prices are 4-decimal dollar strings ("0.6300"), not cents.
"""
import time

import requests

from pm_common import DATA, RAW, get

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_EVENTS = DATA / "kalshi_events.json"
KALSHI_SCRAPED = DATA / "kalshi_scraped.txt"
KRAW = RAW / "kalshi"
KRAW.mkdir(parents=True, exist_ok=True)

PAUSE = 0.25  # Kalshi rate limits are tiered; stay well under the basic tier


def kget(path, **params):
    """GET a Kalshi endpoint; raises requests.HTTPError (e.g. 404) like pm_common.get."""
    time.sleep(PAUSE)
    return get(KALSHI + path, **params)


def is_not_found(exc):
    return isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 404


def get_market(ticker):
    """Live market, falling back to the historical endpoint once Kalshi archives it."""
    try:
        return kget(f"/markets/{ticker}")["market"]
    except requests.HTTPError as e:
        if not is_not_found(e):
            raise
    return kget(f"/historical/markets/{ticker}")["market"]


def dollars(value):
    """'0.6300' -> 0.63; None/'' -> None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def midpoint(bid, ask):
    """Bid/ask midpoint, or None when the book is one-sided or crossed.
    bid 0 with a live ask is a real (empty-bid) book and gives ask/2."""
    if bid is None or ask is None or ask <= 0 or ask < bid:
        return None
    return round((bid + ask) / 2, 4)


# Suffixes seen 2026-10-16: -D/-R almost everywhere, -DEM/-GOP (KXHOUSENC11),
# -I/-IND for independents. Anything else (-XBEC, -DOSB, -MD, ...) is a
# candidate code and says nothing about party.
PARTY_SUFFIX = {"D": "D", "DEM": "D", "R": "R", "GOP": "R", "I": "I", "IND": "I"}


def party_from_ticker(ticker):
    return PARTY_SUFFIX.get(ticker.rsplit("-", 1)[-1].upper())
