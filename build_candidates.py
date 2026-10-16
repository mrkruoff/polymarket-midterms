#!/usr/bin/env python3
"""Build data/candidates.csv: one row per universe market with its party.

Party comes only from what a venue states, never from what a name suggests:
  kalshi_suffix     Kalshi ticker ends -D/-R/-DEM/-GOP/-I/-IND
  polymarket_label  Polymarket's own label: "Mike Carey (R)", "Republican Party", "Independent"
  name_match        no label on this venue, but the same name in the same race_key
                    has one on the other venue
Anything else stays blank and is printed so it can be filled by hand. Hand
edits survive re-runs: a non-blank party with party_source=manual is kept.

resolves_on is "party" when the market pays on a party winning the seat
(Kalshi -D/-R tickers; Polymarket "Will the Republican Party win ...?", which
is most of Polymarket too, despite the candidate label) and "person" when it
pays on a named candidate. analyze.py needs it to spot races where one venue's
party market bundles several of the other venue's candidates.

match_market_id links a market to the same-named market on the other venue
(analyze.py uses it to line up favorites). Party disagreements between two
matched markets are printed and left as each venue labels them.

Usage: python build_candidates.py
"""
import csv
import re
import unicodedata
from collections import defaultdict

from kalshi_common import party_from_ticker
from kalshi_common import PARTY_SUFFIX
from pm_common import DATA, SNAPS, load_universe

OUT = DATA / "candidates.csv"
FIELDS = ["race_key", "venue", "market_id", "candidate", "party", "party_source", "match_market_id",
          "resolves_on"]

PM_TAG = re.compile(r"\((D|R|I)\)\s*$")
PM_PARTY_NAME = {"democrat": "D", "democratic party": "D", "democratic": "D",
                 "republican": "R", "republican party": "R", "independent": "I"}


def polymarket_label(name):
    if m := PM_TAG.search(name or ""):
        return m[1]
    return PM_PARTY_NAME.get((name or "").strip().lower())


# Polymarket question shapes that pay on a party: "Will the Republican Party win
# the OH-15 House seat?", "Will the Democrats win ...", "Will an independent
# win ...", "Will the Democratic
# candidate win the 2026 ... gubernatorial election?"
PM_PARTY_Q = re.compile(r"^Will (the (Republican|Democratic) (Party( candidate)?|candidate)|the (Republicans|Democrats)|an independent|a third.party) win", re.I)


def resolves_on(venue, market_id, question):
    if venue == "kalshi":
        return "party" if market_id.rsplit("-", 1)[-1].upper() in PARTY_SUFFIX else "person"
    return "party" if PM_PARTY_Q.match(question or "") else "person"


def latest_questions():
    """market_id -> question from the most recent snapshot that has it."""
    q = {}
    for snap in sorted(SNAPS.glob("*.csv")):
        for r in csv.DictReader(open(snap)):
            if r.get("question"):
                q[r["market_id"]] = r["question"]
    return q


def norm(name):
    """'John E. Sununu (R)' -> 'john sununu'; accents, punctuation, middle
    initials and Jr./Sr./II/III dropped. Generic party labels never match."""
    n = PM_TAG.sub("", name or "")
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z\s-]", " ", n.replace("’", "").replace("'", ""))
    words = [w for w in n.split() if len(w) > 1 and w not in ("jr", "sr", "ii", "iii", "iv")]
    n = " ".join(words)
    return None if n in PM_PARTY_NAME or n in ("democratic party", "republican party") else n or None


def main():
    universe = load_universe()["markets"]
    manual = {}
    if OUT.exists():
        manual = {r["market_id"]: r["party"] for r in csv.DictReader(open(OUT))
                  if r["party_source"] == "manual" and r["party"]}

    questions = latest_questions()
    rows = {}
    for mid, m in universe.items():
        if m["venue"] == "kalshi":
            party, src = party_from_ticker(mid), "kalshi_suffix"
        else:
            party, src = polymarket_label(m["candidate"]), "polymarket_label"
        rows[mid] = {"race_key": m["race_key"], "venue": m["venue"], "market_id": mid,
                     "candidate": m["candidate"], "party": party or "",
                     "party_source": src if party else "", "match_market_id": "",
                     "resolves_on": resolves_on(m["venue"], mid, questions.get(mid))}

    # cross-venue name matching within a race
    by_race = defaultdict(lambda: defaultdict(list))
    for r in rows.values():
        if (k := norm(r["candidate"])):
            by_race[r["race_key"]][k].append(r)
    conflicts = []
    for race, names in by_race.items():
        for key, rs in names.items():
            pm = [r for r in rs if r["venue"] == "polymarket"]
            ks = [r for r in rs if r["venue"] == "kalshi"]
            if len(pm) != 1 or len(ks) != 1:
                continue  # unmatched, or ambiguous (same name twice on a venue)
            a, b = pm[0], ks[0]
            a["match_market_id"], b["match_market_id"] = b["market_id"], a["market_id"]
            if a["party"] and b["party"] and a["party"] != b["party"]:
                conflicts.append((race, a, b))
            elif a["party"] and not b["party"]:
                b["party"], b["party_source"] = a["party"], "name_match"
            elif b["party"] and not a["party"]:
                a["party"], a["party_source"] = b["party"], "name_match"

    for mid, party in manual.items():
        if mid in rows:
            rows[mid]["party"], rows[mid]["party_source"] = party, "manual"

    out = sorted(rows.values(), key=lambda r: (r["race_key"], r["venue"], r["market_id"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    blank = [r for r in out if not r["party"]]
    src = defaultdict(int)
    for r in out:
        src[r["party_source"] or "blank"] += 1
    kinds = defaultdict(int)
    for r in out:
        kinds[(r["venue"], r["resolves_on"])] += 1
    print(f"{len(out)} markets -> {OUT}; party source: {dict(src)}")
    print(f"resolves on: {dict(kinds)}; cross-venue name matches: {sum(bool(r['match_market_id']) for r in out) // 2}")
    for race, a, b in conflicts:
        print(f"  CONFLICT {race}: polymarket {a['candidate']!r}={a['party']} vs kalshi {b['market_id']}={b['party']}")
    print(f"{len(blank)} markets with no party (fill by hand, set party_source=manual):")
    for r in blank:
        print(f"  {r['race_key']:<16} {r['venue']:<10} {r['market_id']:<24} {r['candidate']}")


if __name__ == "__main__":
    main()
