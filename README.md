# Does Polymarket really call elections a month out?

Personal research project. Polymarket's own accuracy page
(https://polymarket.com/accuracy) claims 90.4% accuracy a month before
election day. This records their 2026 midterm race prices (Senate, House,
governor) before Nov 3 and scores them against how the markets resolved, and
does the same for Kalshi so the two venues can be compared race by race.
No trading, no auth, public endpoints only.

## Setup

    python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
    pip install -r requirements.txt

## Workflow

| When | Command | What it does |
|---|---|---|
| Now, then daily until Nov 3 | `python snapshot.py` | Pulls every event tagged Midterms/Senate/House/Governor, saves raw JSON + a flat CSV, and grows `data/universe.json` (the frozen set of markets to score). |
| Once, now | `python backfill_history.py` | Pulls daily price history from Sept 1 for every market in the universe, so you can score "30 days out" (Oct 4) even though snapshots started Oct 15. |
| Nov 4 onward, re-run until all resolved | `python resolve.py` | Re-polls each market in the universe and records whether YES resolved 1 or 0. Close races take days. |
| Now, then daily until Nov 3 | `python kalshi_snapshot.py` | Same for Kalshi: every event in `data/kalshi_events.json`, raw JSON to `data/raw/kalshi/`, rows appended to the same snapshot CSV and universe with `venue=kalshi`. |
| Once, now | `python kalshi_backfill.py` | Daily Kalshi candlesticks from Sept 1 into the same `history.csv`. |
| Daily (launchd) | `python run_daily.py` | Both snapshots, `build_candidates.py`, `export_site.py`, then commits the data and pushes. A Kalshi failure doesn't block the Polymarket commit. |
| When Kalshi adds a race | edit `data/kalshi_scraped.txt`, `python build_kalshi_events.py` | Re-verifies the curated Kalshi event list (see below). |
| When parties are missing | edit `data/candidates.csv`, `python build_candidates.py` | Fill `party` and set `party_source=manual` for the rows it prints; manual rows survive re-runs. |
| Nov 4 onward, re-run until all resolved | `python resolve.py` | Handles both venues. Kalshi Senate markets nominally settle on who is *sworn in* (Jan 2027) with "accelerated determination" once media call the race, so a few may lag Polymarket. |
| After resolve | `python backfill_history.py`, `python kalshi_backfill.py`, then `python analyze.py` | Scores hit rate, Brier, and calibration at every days-out horizon, per venue and head-to-head. Writes `data/results.json` for the site. |

Daily cron (Linux/mac): `0 12 * * * cd /path/to/polymarket-midterms && .venv/bin/python snapshot.py >> snapshot.log 2>&1`

After election day, run `python snapshot.py --include-closed` once so events that
closed on Nov 3 still get a final-day snapshot.

## Kalshi

**Discovery is a curated list.** Kalshi's `/events?series_ticker=` and
`/markets?series_ticker=` ignore the filter, and ticker schemes are
inconsistent (`SENATETX-26`, `SENATEOHS-26`, `GOVPARTYFL-26`, `KXGOVCA-26`,
`KXHOUSERACE-MN05-26`, `HOUSENY17-26`, `KXCAELECTION-2607` for CA-07, and
`SENATELA-26` is *Kentucky* — Louisiana is `KXSENATELA-26NOV`). So
`data/kalshi_scraped.txt` holds the event tickers linked from Kalshi's
Senate/governor/House category pages (scraped 2026-10-16 in a real browser: the
pages sit behind a Vercel bot check that curl can't pass), and
`build_kalshi_events.py` verifies each against `GET /events/{ticker}` and keeps
only mutually exclusive 2026 winner events. race_key comes from the event
*title*, never the ticker. Where Kalshi lists a race both ways, the
per-candidate event wins (`KXGOVCA` over `GOVPARTYCA`, `KXGOVAK` over
`KXGOVPARTYAK`). Result on 2026-10-16: 503 events (35 Senate, 34 governor,
434 House), 1,035 markets.

**Coverage vs Polymarket.** 503 race_keys are on both venues. Polymarket-only:
gov-GU, gov-KS, gov-NH, house-CA-11 (Kalshi has a `KXHOUSERACE-CA11-26` event
with no markets yet). Kalshi-only: none.

**Prices.** Kalshi `yes_price` is the bid/ask midpoint, not last trade;
`best_bid`/`best_ask`/`last_price` (snapshots) and `yes_bid`/`yes_ask`/`last_price`
(history) are kept so other rules can be applied later. Polymarket's
`outcomePrices` (snapshots) and `prices-history` (history) are Polymarket's
displayed price, which is already the book midpoint, *except* that Polymarket
shows the last trade when the spread is wider than 10¢. So the two series match
whenever spreads are tight, which is nearly always here (7 of 1,035 Kalshi
markets had a spread over 5¢ on Oct 16). They diverge on thin books: on
2026-09-25 about 14 safe House markets on Kalshi closed the day with bids pulled
to ~62¢ against ~97¢ asks, so their midpoint dipped to ~80¢ for one day while
trades stayed ~95¢. Applying Polymarket's >10¢ rule to Kalshi would be the
strictly like-for-like choice; the columns to do so are in `history.csv`.

**Dates.** Kalshi's daily candle ends at 04:00 UTC (midnight ET) and is labeled
by that UTC date; Polymarket's daily point is ~00:00 UTC. Same label, 4h apart.
Kalshi skips a day's candle when nothing changed, so `kalshi_backfill.py`
forward-fills those gaps from the prior close.

**Volume units differ.** Polymarket `volume` is dollars; Kalshi `volume` is
`volume_fp`, a contract count (contracts pay $1, so it's an upper bound on
dollars). The site labels Kalshi volume "ct" and never sums the two.

## Parties (`data/candidates.csv`)

One row per market: `race_key, venue, market_id, candidate, party,
party_source, match_market_id, resolves_on`. Party only comes from what a
venue states: a Kalshi `-D/-R/-DEM/-GOP/-I/-IND` ticker suffix, Polymarket's own
label (`Mike Carey (R)`, `Republican Party`, `Independent`), or a same-name match
to a labeled market in the same race on the other venue. No party is guessed
from a name. ~100 rows stay blank (Alaska and California multi-candidate races,
CA top-two House races, a few independents); `build_candidates.py` prints them.

**Per-party vs per-candidate is mostly a non-issue.** Despite the candidate
labels, almost all of *both* venues' markets pay on a party: Polymarket's
House markets are "Will the Republican Party win the OH-15 House seat?" and its
Senate ones "Will the Democrats win ...". `resolves_on` records which: party
for 1,010 of 1,068 Polymarket and 988 of 1,035 Kalshi markets. The genuinely
per-person races are AK/CA governor (both venues), AK Senate (Polymarket only),
CA-40 and AK-AL (both), the CA top-two House races (Kalshi only), plus a few
independents.

## How scoring works

- A **race** = one Polymarket event (e.g. "Georgia Senate Election Winner") with one
  YES/NO market per candidate. The **favorite** is the highest-priced candidate.
- **Hit rate** = share of races where the favorite won. This is what the ad is
  measuring, and it's a weak test: most midterm races are safe seats.
  `share_favorites_over_95` and `hit_rate_competitive_under_80` are there so you
  can see how much of the headline number is foregone conclusions.
- **Brier** = multi-outcome Brier score per race, averaged. Lower is better.
- **Brier 2-way** = favorite vs the field, `2 * (p_fav - hit)^2`, same 0–2 scale.
  The multi-outcome Brier adds a `p^2` term for every listed long shot, so a
  venue that lists more outcomes for the same race (Polymarket's 23 California
  governor candidates vs Kalshi's 2) can score slightly worse for listing alone.
  The 2-way number doesn't depend on how many outcomes a venue lists; use it to
  compare venues.
- **Calibration** = candidate-level: of markets priced 0.60–0.80, how often did
  that candidate win? Well-calibrated markets sit on the diagonal.

`results.json` keeps its original top-level keys as Polymarket's scorecard and
adds `by_venue.{polymarket,kalshi}` (same metrics) and `overlap`:

- races (race_keys) on both venues, compared at every days_out: `n_races`
  resolved on both, `hit_rate`/`brier`/`brier_2way` per venue, `n_favorite_disagree`
  (venues' favorites are different outcomes), and `mean_abs_favorite_price_gap`
  (|Polymarket price of its favorite − Kalshi price of the same outcome|). The
  last two need no resolutions, so they're meaningful before Nov 3.
- Favorites are each venue's highest-priced market, so hit rate is race-level
  and doesn't care how a venue slices outcomes, with one exception that
  `overlap.excluded` removes: a race where one venue's *party* market covers two
  or more live candidates the other venue prices separately (a D-vs-D top-two
  race, an incumbent plus a same-party write-in). The party market "wins"
  whichever of them wins, a free hit. A live per-person candidate with no known
  party and no name-matched market is excluded the same way, since it can't be
  ruled out; filling parties in `candidates.csv` brings those races back. On
  2026-10-16 that's 14 races (mostly CA top-two districts and AK Senate).

Chamber-control, balance-of-power, and primary markets are kept in `data/raw/`
but excluded from scoring (they aren't independent of the race outcomes).

## Things to sanity-check once data is in

1. Open the first `data/snapshots/*.csv` and confirm `classify_event()` in
   `pm_common.py` isn't mislabeling races. Polymarket's tags don't separate
   race types cleanly, so it's title regexes. Expect to tweak.
2. Spot-check a few resolutions against AP results; Polymarket's resolution
   rules occasionally differ from the obvious outcome.
3. Thin markets (volume < ~$1k) are noise. Consider filtering on `volume` in
   `analyze.py` once you see the distribution.

## Dashboard

`docs/` is a static dashboard (GitHub Pages: Settings → Pages → deploy from
branch, `main` + `/docs`). `python export_site.py` condenses
universe/history/snapshots into `docs/data.json`; the daily launchd job runs it
after each snapshot. The scorecard section lights up automatically once
`data/results.json` exists. Preview locally with `python -m http.server -d docs`
(fetch() needs HTTP, not file://).

The venue toggle switches the table between Polymarket, Kalshi, and "On both"
(races listed on both). Each race's chart overlays the other venue's matching
outcomes as dashed lines, and the table has a column with the other venue's
price for the favorite.

`data/raw/` (including `data/raw/kalshi/`) is gitignored (~50MB/day); it stays on disk as re-filter insurance.

## Not yet built

- A baseline ("incumbent party wins" or Cook ratings) to compare the hit rate
  against. Needs an external data file; the API doesn't know incumbency.
