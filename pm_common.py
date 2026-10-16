"""Shared helpers: API access, race classification, paths."""
import json
import re
import time
from pathlib import Path

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SNAPS = DATA / "snapshots"
UNIVERSE = DATA / "universe.json"
RESOLUTIONS = DATA / "resolutions.csv"
for d in (RAW, SNAPS):
    d.mkdir(parents=True, exist_ok=True)

# Tag labels worth sweeping. Discovered by label at runtime so tag IDs
# don't have to be hardcoded. Verified against the live tag list on 2026-10-15:
# 102289=Midterms holds ~99% of events; 104093=Senate Elections, 104094=Governor
# Elections, 103899=House Elections, 100199=Senate and the per-state "<State>
# Midterm" tags fill the gaps (e.g. California Governor Election Winner is not
# under Midterms). Patterns are anchored to avoid junk like "House of the
# Dragon", "French Senate Elections", "Summer house".
TAG_LABEL_PATTERNS = [
    r"midterm",                                            # Midterms, 2026 Midterms, "<State> Midterm", ...
    r"^senate$",
    r"^(key |tossup )?(senate|governor|house) (elections|races)$",
    r"^gubernatorial$",
]

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "polymarket-midterms-accuracy-check/0.1 (personal research)"


def get(url, **params):
    """GET with light retry. Polymarket's public endpoints need no auth."""
    for attempt in range(4):
        r = SESSION.get(url, params=params, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def jlist(value):
    """Gamma returns some list fields as JSON-encoded strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return []


# --- race classification -----------------------------------------------------

# A scoreable race is exactly one of Polymarket's canonical "winner" events,
# verified against the 2026-10-15 raw dump:
#   "<State> Senate Election Winner", "<State> Governor Election Winner",
#   "XX-NN House Election Winner"  (district AL = at-large)
# Everything else under the midterm tags is derivative of a race, not a race:
# "... Margin of Victory", "...: <County> County Winner", "...: Turnout",
# "First Round Outright Winner in ...", "Senate and Governor Combo" parlays,
# "Closer/Closest ... Race" props, "... odds on <date>" markets, Lieutenant
# Governor, state legislatures ("Pennsylvania State Senate Winner"), leader
# elections. A few CA districts also have a duplicate "... House Election
# Winner (Individual)" event; snapshot.py keeps it only when the party-level
# event for the same district doesn't exist (e.g. CA-40's R-vs-R race).
RACE_PATTERNS = {
    "governor": re.compile(r"^(?!.*\blieutenant\b)[A-Za-z .'-]+ Governor Election Winner$", re.I),
    "senate": re.compile(r"^[A-Za-z .'-]+ Senate Election Winner$", re.I),
    "house": re.compile(r"^[A-Z]{2}-(?:AL|\d{1,2}) House Election Winner( \((?:by )?individual\))?$", re.I),
}
CHAMBER_CONTROL = re.compile(
    r"(which party|balance of power|control (the|of)|majority|seats?\b|net gain|flip"
    r"|(democrats|republicans|democratic party|republican party|gop) (win|keep|hold|take|retain) the (house|senate))", re.I
)
PRIMARY = re.compile(r"primary|runoff", re.I)


def classify_event(title: str) -> str:
    """Return one of: senate, governor, house, control, primary, other.

    Only senate/governor/house are 'races' for the accuracy test, and they are
    matched by anchored whole-title patterns so derivative markets can't leak
    in. Chamber-control and balance-of-power markets are kept in the raw dump
    but excluded from the scored set because they're not independent of the
    race-level outcomes.
    """
    t = (title or "").strip()
    for race_type, pat in RACE_PATTERNS.items():
        if pat.match(t):
            return race_type
    if CHAMBER_CONTROL.search(t):
        return "control"
    if PRIMARY.search(t):
        return "primary"
    return "other"


# Padding shapes seen in the 2026-10-15 dump: 'Other', bare letters 'A'..'E',
# 'Party A', 'Candidate A', 'Person A', 'Option F', 'Another Party'. Anchored
# full-match so a real candidate name can never be swallowed.
PLACEHOLDER = re.compile(
    r"(?:[A-Z]|Party [A-Z]|Candidate [A-Z]|Person [A-Z]|Option [A-Z]|Other|Another (?:Party|Candidate))", re.I)


def is_placeholder_market(market: dict) -> bool:
    """Polymarket pads multi-outcome events with placeholder slots that carry no
    volume. Drop them so they don't become phantom candidates. An 'Other' slot
    with real volume is kept — that's a live catch-all outcome, not padding."""
    name = (market.get("groupItemTitle") or market.get("question") or "").strip()
    vol = float(market.get("volume") or 0)
    if bool(PLACEHOLDER.fullmatch(name)) and vol == 0:
        return True
    # Some padding slots carry a mislabeled groupItemTitle (seen: "CA-22" whose
    # question is "Will B win..."), so also catch them by state: never traded,
    # not active, and no prices.
    return not market.get("active") and vol == 0 and not jlist(market.get("outcomePrices"))


def yes_price(market: dict):
    """Price of the YES outcome as a float in [0,1], or None."""
    outcomes = jlist(market.get("outcomes"))
    prices = jlist(market.get("outcomePrices"))
    if not outcomes or not prices:
        return None
    try:
        idx = outcomes.index("Yes")
    except ValueError:
        idx = 0
    try:
        return float(prices[idx])
    except (ValueError, IndexError, TypeError):
        return None


def yes_token_id(market: dict):
    outcomes = jlist(market.get("outcomes"))
    tokens = jlist(market.get("clobTokenIds"))
    if not tokens:
        return None
    try:
        return tokens[outcomes.index("Yes")]
    except (ValueError, IndexError):
        return tokens[0]
