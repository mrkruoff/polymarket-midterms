# Does Polymarket really call elections a month out?

Personal research project. Polymarket's ad claims ~95% accuracy a month before
election day. This records their 2026 midterm race prices (Senate, House,
governor) before Nov 3 and scores them against how the markets resolved.
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
| After resolve | `python backfill_history.py` then `python analyze.py` | Scores hit rate, Brier, and calibration at every days-out horizon. Writes `data/results.json` for the site. |

Daily cron (Linux/mac): `0 12 * * * cd /path/to/polymarket-midterms && .venv/bin/python snapshot.py >> snapshot.log 2>&1`

After election day, run `python snapshot.py --include-closed` once so events that
closed on Nov 3 still get a final-day snapshot.

## How scoring works

- A **race** = one Polymarket event (e.g. "Georgia Senate Election Winner") with one
  YES/NO market per candidate. The **favorite** is the highest-priced candidate.
- **Hit rate** = share of races where the favorite won. This is what the ad is
  measuring, and it's a weak test: most midterm races are safe seats.
  `share_favorites_over_95` and `hit_rate_competitive_under_80` are there so you
  can see how much of the headline number is foregone conclusions.
- **Brier** = multi-outcome Brier score per race, averaged. Lower is better.
- **Calibration** = candidate-level: of markets priced 0.60–0.80, how often did
  that candidate win? Well-calibrated markets sit on the diagonal.

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

## Not yet built

- A baseline ("incumbent party wins" or Cook ratings) to compare the hit rate
  against. Needs an external data file; the API doesn't know incumbency.
- The static site. `data/results.json` is the intended feed.
