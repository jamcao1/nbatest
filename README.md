# Courtside — NBA simulation lab

A weekly NBA dashboard and command-line model that runs **1,000 Monte Carlo simulations per game**. Each matchup includes a favored team, win probability, average projected final score, 80% margin/total ranges, a score-margin distribution, and an explanation of its team-strength and rest inputs. Optional odds CSVs add spread/total probabilities, pushes, no-vig moneyline comparisons, and movement between uploaded snapshots.

## Run

Requires Python **3.11+** with the IANA timezone database (available in the prepared cloud environment). The application uses only the Python standard library: no pip packages, database, or API key is required.

```bash
cd /workspace/nbatest
python -m nbasim.app --port 8000
```

The local dashboard defaults to an explicitly labeled historical replay of April 6–12, 2015. Select **Live week** to fetch the next seven days of scheduled NBA games. Change the start date and seed, then run the simulations. Select a game to see its distribution, assumptions, and optional market comparisons. Team search accepts the abbreviations in the selected dataset. **Export results** downloads the full JSON report. **Dataset template** downloads the current inputs, which can be edited and imported.

The server binds to loopback by default. It is a local development server, not an authenticated public deployment. Do not expose it to the public Internet unchanged.

### Live data

HTTPS access to `site.api.espn.com` is working in the managed cloud environment. A real fetch on October 18, 2026 produced 36 upcoming matchups for October 18–24 and 486 completed training games. The latest training result was June 13, 2026, so this opening-week forecast uses the prior season and explicitly warns that roster changes are not modeled. Live fetching and all 1,000 simulations per matchup have been verified. The network setting must remain available in any new environment.

ESPN's NBA scoreboard accepts individual dates, not date ranges. The adapter reads the season calendars at both ends of the requested window, then fetches game days individually, with at most four concurrent requests. If calendar metadata is unavailable, it scans individual dates instead. HTTP feed errors and connection failures are reported separately. Historical results are never substituted for a failed live request.

The public ESPN scoreboard is an undocumented feed and can change. Only scheduled, unstarted regular-season and playoff games are selected; preseason, All-Star, postponed, and in-progress games are excluded. Final results from the preceding 240 days provide training data. No injuries or live betting odds affect the production predictions. The separate roster research panel displays source-provided injury snapshots without treating them as confirmed game availability. Empty upcoming slates are valid and produce an empty report; insufficient training data is an explicit error. Freshness is shown in the source and generation timestamps. Live responses are fetched anew on each run.

## Player scoring atlas

Open **Player scoring & shot maps** (`players.html`) or follow the link from a matchup. The page selects each team's **projected scoring leader**—highest expected points among its current, sufficiently observed roster members, not best overall player—and lets you inspect other players. It includes expected points, made/missed field goals, free throws, an interactive half-court zone view, actual historical made/missed shot locations, recent scoring, a minutes scenario slider, opponent/pace factors, venue splits, and sourced opening/latest game-line movement.

The estimate covers **regulation only, conditional on playing the selected minutes**. It is not interchangeable with a sportsbook prop that includes overtime. Out players receive zero minutes and are excluded from leader selection. Other injury statuses remain conditional. A player needs three prior appearances and 60 historical minutes to be rated. Unknown players receive an eight-minute allocation weight when distributing the team's 240 minutes but no invented shooting profile. Rotations use up to ten observed appearances and are not coach-confirmed.

Shooting uses up to twenty earlier appearances, a 45-day decay relative to the latest appearance, and twenty league-prior attempts per zone. Opponent zone accuracy is shrunk with fifty league-prior attempts and bounded to a ±10% adjustment. Matchup pace changes volume by at most ±10%. Home/away usage differences use 300 prior minutes and a ±5% cap. Exact-venue results are descriptive; they do not establish an arena effect. Player identity follows stable IDs across team changes, but new roles, particular defenders, shot quality, and offseason skill changes are not modeled.

`data/player_shots_2026.json.gz` contains **466 validated games from February 22–June 13, 2026**, with five excluded summaries recorded explicitly. There are **77,368 mapped field-goal attempts out of 82,117**. ESPN coordinates use feet relative to the hoop at `(25, 0)`. Coordinates outside plausible bounds or inconsistent with stated distance are unlocated. A player's play-by-play must reconcile with their box-score two- and three-point totals; otherwise all their game locations are withheld while the box-score scoring remains available. The court shows up to 150 recent recorded locations; the table covers the full player sample. Expected-zone markers are schematic, not fabricated future shots.

The model's 1,500 deterministic scoring draws use Poisson attempts, shared shot-volume variation, and binomial makes. The displayed 80% ranges are **uncalibrated** and exclude availability and minutes uncertainty. A chronological development replay on the last **40 archived games / 80 pregame-selected leaders** had **7.27 points mean absolute error**, versus **6.95** for a last-ten scoring-average baseline evaluated on the same selected players. Target-game participants and statistics do not enter the predictions. Historical rosters use each team's last earlier box score; overtime outcomes are normalized to 48 minutes. This experiment **did not beat the simpler baseline** and does not validate current trades, future scoring, prediction ranges, or profitability.

Current roster membership/injuries and venue/game-line context are fetched during each report build. A failed context produces an unavailable matchup; a failed overall research job produces an explicitly unavailable player page without interrupting the other dashboards. Opening/latest quotes are dated retrieval snapshots, not a complete betting trend or betting-volume feed. Player prop prices are not supplied or invented. Stale dates remain visible. Shared player histories are stored once to reduce page payload; changing a chart or minutes scenario does not fetch new data.

```bash
python -m nbasim.players --input reports/inputs.json --rosters reports/rosters.json --output reports/players.json
python -m nbasim.players --evaluate --output reports/player-evaluation.json
python -m nbasim.site --report reports/weekly.json --rosters reports/rosters.json --pace reports/pace-priors.json --players reports/players.json --output site
node --test tests/test_player_model.mjs
# After serving the static site under /nbatest/:
NBATEST_BASE_URL=http://127.0.0.1:8002/nbatest/ python tests/browser_players.py
```

## Live pace and totals

Open **Live pace & quarter totals** on the dashboard, or `live.html` in the Python app. The page fetches ESPN's current scoreboard and game summaries directly, refreshing the selected game every 30 seconds while visible. It pauses monitoring when the page is closed or hidden; it does not operate as a background alert service. The public feed can be delayed, corrected, or unavailable. No API key is required.

The page waits for the first recorded play and pauses comparisons at quarter breaks, halftime, delays, and active overtime. A failed game-list refresh does not interrupt a working selected-game feed. Failed summaries clear the prior analysis, and refreshing retries an initial historical-data failure. The historical-data date and any stale-history restriction are visible before tipoff.

Select the current quarter or the full game, then enter the **actual combined points line and both American prices**. Confirm the line when observed; changing games, quarters, or replay clocks clears it, and editing prices requires reconfirmation. No sportsbook feed is connected, and no line is invented. Full-game totals include simulated overtime; quarter totals exclude other quarters. Overtime already in progress is not supported. The historical replay is explicitly labeled and cannot produce a live watch signal.

The model separates estimated possessions from scoring efficiency. Possessions use the average of `FGA + 0.44 * FTA - individual ORB + total TO` for the two teams, normalized to 48 minutes. This is a box-score approximation, not official tracking pace. Dead-ball team rebounds are excluded to align with the box-score formula. The recent three-minute panel exposes attempts, makes, turnovers, estimated possessions, and time since each team's last score. Low possession counts indicate slowing play; missed attempts at normal tempo indicate a different cause of a scoring drought. Neither condition proves what will happen next, and points are never considered “due.”

Team/opponent pace and points-per-possession priors are shrunk toward league averages. Observed pace is blended with twelve minutes of prior pace, and efficiency with thirty possessions of prior scoring. Two thousand seeded draws estimate remaining points, with shared pace uncertainty, team efficiency uncertainty, and scoring variance. Tied full-game draws continue through simulated overtime. This is an **experimental model**, not a possession-by-possession tactical simulator. It omits shot quality, current lineups, injuries, substitutions, and intentional late fouling.

The market comparison shows over/under/push probabilities, break-even probabilities, and model-implied return per unit risked. These are calculations under model assumptions, **not validated betting returns**. Research watches require a five-percentage-point conditional probability difference and positive model-implied return. Missing/delayed feed timestamps, retrievals over 90 seconds old, market prices over 60 seconds old, fewer than three elapsed minutes or five estimated possessions, team priors over 30 days old, fewer than five recent prior games for either team, missing team priors, a 20-point lead in the second half, the final minute of a quarter, late fourth-quarter fouling, or feed/box-score discrepancies suppress watches. A freshly fetched old prior is still old. Opening-week roster uncertainty therefore prevents the current historical priors from generating watch signals. When the summary has no official ticking clock, the display explicitly follows the last recorded play instead.

**Archived Miami/Denver research:** in the available 401-game regular-season sample from February 20–April 12, 2026 (26 games for each team), Miami averaged **104.69 estimated possessions per 48 minutes, rank 3**, and Denver **102.30, rank 13**, versus a league average **101.75**. Denver ranked **1st in points per possession (1.212)**; Miami ranked **5th (1.181)**. Miami exceeded the league sample's average pace in 73.1% of its games and Denver in 53.8%. High scoring and fast pace are distinct, and “fast regardless of opponent” is not supported. These are partial historical sample rankings, not current-season or official NBA tracking rankings. This research is retained here; the live page focuses on the selected game.

**Replay evaluation:** the last 60 regular-season games in the archived sample were selected chronologically before inspecting model results. One game failed quarter-score reconciliation; 59 were usable. At three, six, and nine elapsed minutes of each quarter, mean absolute final-quarter error was **6.16 / 4.88 / 3.53 points**, versus **10.53 / 6.42 / 3.93** for straight scoring-rate extrapolation and **5.99 / 4.84 / 3.53** for observed points plus historical-rate remaining points. The model improves on naive extrapolation but does **not** consistently beat the stronger historical-rate baseline. Reported 80% interval coverage ranged from 79.7% to 94.9% across checkpoints. No historical in-play market prices were available, so profitability, sportsbook-price calibration, and actual live-feed latency are untested. The page reports all checkpoints and does not claim an accuracy improvement over the historical baseline.

Reproduce the research from the dated public source archive without network access:

```bash
python -m nbasim.pace_data --archive data/pace_history_2026.json.gz --prepare-replay-cases reports/pace-cases.json
node tests/evaluate_pace.mjs reports/pace-cases.json reports/pace-evaluation.json
node --test tests/test_live_model.mjs
```

`data/pace_history_2026.json.gz` contains 482 validated completed-game summaries (four unavailable summaries are recorded as exclusions). The evaluation's SHA-256 identifies this archive. Per-game priors use only earlier New York calendar dates; held-out final scores, box-score totals, and future plays are not inputs to projections. The public historical logs may nevertheless contain retrospective corrections, so this is a development replay rather than an independent prospective test. Weekly builds reuse matching archived historical results, fetch new games, and publish dated priors; current live play-by-play is fetched separately in the browser. Node.js 18+ is needed for the additional model tests; the local server still has no Python package dependencies.

## Current rosters and experimental rotations

The published site's **Roster changes & research** section and each matchup's details now show current ESPN roster membership, changes relative to the team's last observed box-score roster, player points per game from the available history, provisional minutes, and dated injury status snapshots. Roster comparisons are **not a verified transaction log**: a player absent from a box score may have been on the team already. Roster data are refreshed with each weekly build, not continuously. A roster failure produces an explicit unavailable panel; it does not silently reuse an older snapshot or block the baseline report.

The minute estimator uses each player's last five box-score appearances, including DNPs, scales each team's allocation to 240 minutes, and caps individuals at 48. Players with no history receive an eight-minute allocation prior before normalization. Displayed PPG excludes DNPs. These are **historical-role estimates, not confirmed or medically adjusted rotations**; rookies, role changes, injured players, and small samples remain major limitations. Current rosters include training-camp/two-way players as listed by the provider. Source timestamps and unknown-history minute shares are displayed.

An experimental net-strength model fits final game margins to player minute shares using ridge regression (penalty 12, 60-day recency decay). Overtime minute shares are normalized to regulation length. For each team it compares the estimated current rotation with its historical weighted rotation; a proposed net-strength delta is split equally between offense and defense. These coefficients measure game-level associations, not isolated causal player impact. This experiment is **not applied to production predictions**.

In six chronological holdouts from **March 9–April 19, 2026**, the candidate performed worse on both metrics:

| Metric (lower is better) | Team baseline | Roster candidate |
|---|---:|---:|
| Brier probability error | 0.1845 | 0.1877 |
| Mean absolute margin error | 12.23 points | 12.37 points |

The comparison includes 277 held-out games. Both models use the same validated box-score subset. Of 486 fetched historical games, 470 reconciled player totals with final scores; 16 records with missing minutes or unavailable summaries were excluded and recorded. Historical rotations use only the last roster and player minutes observed **before** each weekly cutoff; current rosters and held-out participants/minutes never enter the fit or projections. These holdouts cover a partial season and do not validate offseason transactions or future performance. Reliable game-specific expected minutes and archived pregame injury/transaction data remain necessary for a stronger evaluation. No accuracy improvement is claimed.

The normalized historical inputs, source retrieval date, exclusions, and SHA-256 are retained in `data/player_boxscores_2026.json.gz` and `data/lineup_evaluation_2026.json`. Reproduce the evaluation without network access:

```bash
python -m nbasim.lineups --backtest-input data/player_boxscores_2026.json.gz --output reports/lineup-evaluation.json
```

Refresh roster context and build the site:

```bash
python -m nbasim simulate --live --output reports/weekly.json --dataset-output reports/inputs.json
python -m nbasim.lineups --input reports/inputs.json --output reports/rosters.json --evaluation-file data/lineup_evaluation_2026.json
python -m nbasim.site --report reports/weekly.json --rosters reports/rosters.json --output site
```

The optional local `.cache/player-boxes` stores normalized completed box scores. GitHub's weekly run starts with a fresh cache and attempts fresh retrieval. If a historical box score is temporarily unavailable, the bundled dated archive can supply it only when its game ID, date, teams, venue flag, and final scores match the freshly retrieved scoreboard. Each fallback and its archive retrieval time is disclosed in the roster JSON and panel. New games and current rosters still require live retrieval. Remove the local cache and pass `--no-archive-fallback` to require fresh historical box scores exclusively. At least 95% of requested game boxes must be usable. `--allow-unavailable` writes an explicit unavailable result on a source failure and is used by the scheduled workflow. Current roster snapshots are never attached to a historical forecast date.

## Reports and weekly automation

### Public website on GitHub Pages

The same dashboard can be published as a static website. It opens the most recently generated live-data report, with team search, matchup details, score distributions, JSON downloads, readable analysis, and historical backtest results. The page shows when the report was generated and flags an expired forecast. It is a weekly snapshot, not a live scoreboard. New simulations and dataset/odds imports remain available in the Python app.

Setup steps for this repository:

1. Open **Settings → Pages** in `jamcao1/nbatest`.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open **Actions → Weekly NBA simulations → Run workflow**, select `main`, and run it.
4. Wait for both `simulate` and `deploy` jobs to finish successfully.
5. Use the site URL shown in the `github-pages` deployment or the Pages settings page.

After setup, the existing Monday workflow generates and publishes the next weekly report automatically. Pushes to `main` and manual runs also refresh it. A failed build does not replace the last successful deployment; the published date remains visible so stale data are not presented as current. Reports are generated in GitHub Actions; Pages needs no Python server or API credentials.

Build the same site locally:

```bash
python -m nbasim.site --report reports/weekly.json --output site
```

Only the generated `site/` directory is published. It contains HTML, CSS, JavaScript, the weekly JSON/Markdown reports, and historical backtest results. Local configuration and credentials are not included.

### Generate reports

```bash
# Real historical replay, with outcomes from the target week withheld
python -m nbasim simulate --output reports/demo.json

# Current seven-day slate (requires network access)
python -m nbasim simulate --live --output reports/weekly.json --markdown reports/weekly.md

# Explicit start date, reproducible seed
python -m nbasim simulate --live --week 2026-10-26 --seed 42 --output reports/weekly.json

# Your dataset plus optional odds
python -m nbasim simulate --input data/my-week.json --odds data/my-odds.csv --output reports/my-week.json

# Six chronological historical holdout weeks
python -m nbasim backtest --output reports/backtest.json
```

`.github/workflows/weekly.yml` runs tests and creates downloadable JSON and readable Markdown reports every Monday at **12:00 UTC** (8 a.m. New York during daylight time, 7 a.m. during standard time), and supports manual dispatch. Scheduled runs require this file on the repository's default branch with GitHub Actions enabled. The workflow does not place bets, send messages, or modify the repository. GitHub may delay scheduled runs; the workflow retains each report artifact for 30 days. A failed feed request fails the workflow instead of publishing stale predictions. The local CLI runs the same report command; no always-on cloud process is assumed. Find runs and downloadable reports in the repository's **Actions → Weekly NBA simulations** page.

## Import data

Use a JSON object with `week_start`, `history`, and `schedule`. History needs at least 30 completed games before the start date, ideally several hundred spanning all teams. Only the most recent year is fitted. Schedule must fit within the seven-day window. Use identical team codes in both inputs. IDs must be unique. Future/history rows on or after the start date are excluded, even if scores are supplied. Schedule scores are stripped.

```json
{
  "week_start": "2026-10-26",
  "source": "Your data provider and retrieval time",
  "history": [
    {"id":"past-1","date":"2026-10-20","home":"BOS","away":"NYK","home_score":110,"away_score":102,"neutral":false}
  ],
  "schedule": [
    {"id":"next-1","date":"2026-10-26","home":"BOS","away":"NYK","neutral":false}
  ]
}
```

This abbreviated example illustrates the shape; one historical game is insufficient. Download **Dataset template** for a complete working input with real historical data. Game dates use the **America/New_York** calendar. `neutral` is optional and defaults to false. Missing team history is disclosed and uses league-average strength.

CSV conversion is also available:

```bash
python -m nbasim import-csv --history history.csv --schedule schedule.csv --week 2026-10-26 --output data/my-week.json
```

History columns: `id,date,home,away,home_score,away_score,neutral`.
Schedule columns: `id,date,home,away,neutral`. Neutral values may be `true`, `false`, or empty.

### Optional odds CSV

```csv
game_id,observed_at,home_spread,total,home_moneyline,away_moneyline
next-1,2026-10-25T12:00:00-04:00,-3.5,221.5,-160,140
next-1,2026-10-25T18:00:00-04:00,-4.5,222.5,-175,150
```

These numbers illustrate the format and are **not real market lines**. Match `game_id` to a scheduled game. A negative home spread means the home team is favored. Moneylines use American notation. Both moneylines are required for no-vig comparison, but spread and total can be supplied independently. Each row needs a timezone-aware observation timestamp and at least one market value. The latest observation is used; multiple observations expose changes in the uploaded spread/total, not a complete account of betting activity. Stale odds remain visible through their observation timestamp; no current-market claim is made.

Historical replays accept only odds known by midnight New York time at the forecast start. Current/future forecasts accept odds known by the run time. No future-dated odds are accepted. Both times are recorded in the report. For spread/total probabilities, win/loss/push probabilities sum to one. A push is not a win; no implied betting return or recommendation is calculated.

## Model and interpretation

This is an inspectable **score-based baseline**, not a player/possession simulator or a trained betting system.

1. Fit completed games strictly before the forecast start. Freeze ratings for the entire seven-day report, preventing actual within-week outcomes from leaking into predictions.
2. Weight results exponentially with a **60-day decay constant**. Fit opponent-adjusted offense and points-conceded effects using iterative ridge regression, with 12 equivalent games of shrinkage toward league average. Positive points-conceded effects mean weaker defense.
3. Estimate home court with a 100-game prior centered at a 2.5-point margin, bounded to 0–5 points. Neutral-site games get zero home advantage. A back-to-back produces a fixed 1.25-point margin penalty; this is an assumption, not an estimated player-fatigue effect. Rest within the week uses the known schedule, without future game outcomes.
4. Estimate shared score variance and score correlation from training residuals; bound score standard deviation to 9–18 points and correlation to −0.25–0.50. Draw 1,000 correlated Gaussian score pairs per matchup and round to integer scores. Training data include overtime; rounded ties use a symmetric one-point tiebreak, **not** an explicit overtime model.
5. Aggregate wins, means, score ranges, and market comparisons. Stable game-specific seeds make results reproducible and independent of slate order. The same dataset, seed, and model version produce identical simulations; generation timestamps vary.

The mean projected score is a summary, **not the most probable exact final score**. The favored team is the most frequent winner in the simulations. The 80% intervals describe simulated game variation; the separate 95% Wilson interval describes Monte Carlo sampling error only. Neither quantifies all uncertainty about model specification or missing roster information. At a 50% prediction, 1,000 simulations imply roughly ±3 percentage points of Monte Carlo error.

This version does not include injuries, rotations, player matchups, pace/possessions, travel, roster transactions, or live line feeds. It can be especially weak at season transitions and explicitly flags long breaks and thin team histories. Roster-aware models and more recent held-out seasons should be evaluated before relying on it for decisions. Increasing the simulation count does not fix model bias. Odds comparisons are independent descriptive differences, not demonstrated betting edges.

## Validation

```bash
python -m unittest discover -s tests -v
node --check nbasim/static/app.js  # optional frontend syntax check; Node is not a runtime dependency

# Optional UI integration checks, with the server already running.
# Uses the prepared machine's Playwright and /usr/bin/chromium.
python tests/browser_smoke.py
```

The tests cover probability accounting, deterministic seeds, home/neutral symmetry, stronger-offense effects, rest direction, no future-result leakage, spread sign and pushes, odds timestamps/movement, invalid inputs, feed parsing, and real HTTP requests against the application.

The default backtest uses six weekly holdouts from **March 2–April 12, 2015**, totaling **319 games**. Each week is fitted on earlier results only; actual held-out scores are used only for evaluation. The seed-42 development run produced:

| Measure | Result |
|---|---:|
| Winner accuracy (0.5 credit for exact probability ties) | 70.2% |
| Brier score (lower is better) | 0.200 |
| Training home-win-rate baseline Brier score | 0.240 |
| Mean absolute margin error | 9.8 points |
| Mean absolute total error | 14.2 points |
| Coverage of the nominal 80% margin range | 80.9% |

Calibration bins and fold sizes are included in the report. This single older season is a development evaluation, not independently verified performance on contemporary NBA games. There is no betting-return backtest. Live network access is verified locally; check the repository's Actions page for the outcome of each automated run.

## Historical data attribution

`data/season_2015.json` contains all 1,230 regular-season games from the 2014–15 NBA season, derived from [FiveThirtyEight's NBA Elo dataset](https://github.com/fivethirtyeight/data/tree/master/nba-elo), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Transformations: retain one row per game, normalize home/away/date fields, flag two neutral-site games, and keep only teams and final scores. Supplied Elo ratings and FiveThirtyEight forecasts are **not** used. Historical abbreviations (such as BRK and PHO) are retained. Do not mix them with a differently named provider without mapping team identities.
