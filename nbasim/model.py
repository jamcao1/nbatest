"""Score-based, opponent-adjusted Monte Carlo baseline. No betting inputs in fitting."""
import hashlib
import math
import random
import statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .data import day, parse_odds, validate_dataset

VERSION = 'score-ridge-v1'
SIMULATIONS = 1000


def mean(xs):
    return statistics.fmean(xs) if xs else 0.0


def fit(history, cutoff):
    cutoff = day(cutoff)
    rows = [g for g in history if 0 < (cutoff - day(g['date'])).days <= 365]
    if len(rows) < 30:
        raise ValueError('Need at least 30 completed games in the year before the forecast.')
    teams = sorted({g[t] for g in rows for t in ('home', 'away')})
    weights = [math.exp(-(cutoff - day(g['date'])).days / 60) for g in rows]
    weight = sum(weights)
    league = sum(w * (g['home_score'] + g['away_score']) for g, w in zip(rows, weights)) / (2 * weight)
    # Shrink noisy observed home margin toward a 2.5-point prior.
    nonneutral = [(g, w) for g, w in zip(rows, weights) if not g.get('neutral', False)]
    home_edge = (sum(w * (g['home_score'] - g['away_score']) for g, w in nonneutral) + 100 * 2.5) / (sum(w for _, w in nonneutral) + 100)
    home_edge = max(0, min(5, home_edge))
    attack = dict.fromkeys(teams, 0.0)
    concede = dict.fromkeys(teams, 0.0)
    observations = []
    for g, w in zip(rows, weights):
        edge = 0 if g.get('neutral', False) else home_edge
        observations.extend([(g['home'], g['away'], g['home_score'] - edge / 2, w),
                             (g['away'], g['home'], g['away_score'] + edge / 2, w)])
    # Alternating ridge regressions: score = league + team offense + opponent defense.
    # Positive defense means more points conceded (a weaker defense).
    for _ in range(35):
        numerator = dict.fromkeys(teams, 0.0)
        denominator = dict.fromkeys(teams, 12.0)
        for team, opp, score, w in observations:
            numerator[team] += w * (score - league - concede[opp])
            denominator[team] += w
        attack = {t: numerator[t] / denominator[t] for t in teams}
        center = mean(list(attack.values()))
        attack = {t: v - center for t, v in attack.items()}
        numerator = dict.fromkeys(teams, 0.0)
        denominator = dict.fromkeys(teams, 12.0)
        for team, opp, score, w in observations:
            numerator[opp] += w * (score - league - attack[team])
            denominator[opp] += w
        concede = {t: numerator[t] / denominator[t] for t in teams}
        center = mean(list(concede.values()))
        concede = {t: v - center for t, v in concede.items()}
    residuals, products = [], []
    for g, w in zip(rows, weights):
        h, a = g['home'], g['away']
        edge = 0 if g.get('neutral', False) else home_edge
        rh = g['home_score'] - (league + attack[h] + concede[a] + edge / 2)
        ra = g['away_score'] - (league + attack[a] + concede[h] - edge / 2)
        residuals.extend([(rh * rh, w), (ra * ra, w)])
        products.append((rh * ra, w))
    variance = sum(x * w for x, w in residuals) / (2 * weight)
    sigma = max(9, min(18, math.sqrt(variance)))
    rho = max(-0.25, min(0.5, sum(x * w for x, w in products) / weight / (sigma * sigma)))
    profiles = {}
    for team in teams:
        played = [g for g in rows if team in (g['home'], g['away'])]
        recent = played[-10:]
        margins = [g['home_score'] - g['away_score'] if g['home'] == team
                   else g['away_score'] - g['home_score'] for g in recent]
        profiles[team] = {'games': len(played), 'last_played': played[-1]['date'],
                          'last_10_wins': sum(m > 0 for m in margins),
                          'last_10_games': len(recent), 'last_10_margin': round(mean(margins), 1),
                          'attack': round(attack[team], 2), 'concede': round(concede[team], 2)}
    return {'league': league, 'home_edge': home_edge, 'attack': attack, 'concede': concede,
            'sigma': sigma, 'rho': rho, 'profiles': profiles, 'games': len(rows),
            'last_result': max(g['date'] for g in rows)}


def quantile(xs, p):
    ordered = sorted(xs)
    index = (len(ordered) - 1) * p
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def wilson(wins, n):
    p = wins / n
    z = 1.96
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(center - half, 4), round(center + half, 4)]


def implied(line):
    return -line / (-line + 100) if line < 0 else 100 / (line + 100)


def simulate(game, model, schedule, seed=42, odds=None):
    h, a = game['home'], game['away']
    warnings = []
    rests = {}
    for t in (h, a):
        previous = [day(g['date']) for g in schedule if t in (g['home'], g['away']) and day(g['date']) < day(game['date'])]
        profile = model['profiles'].get(t)
        if profile:
            previous.append(day(profile['last_played']))
            if profile['games'] < 15:
                warnings.append(f'{t}: only {profile["games"]} training games; rating is strongly shrunk.')
            if (day(game['date']) - day(profile['last_played'])).days > 30:
                warnings.append(f'{t}: training results are over 30 days old; roster changes are not modeled.')
        else:
            warnings.append(f'{t}: no training games; using league-average strength.')
        rests[t] = max(0, (day(game['date']) - max(previous)).days - 1) if previous else None
    home_edge = 0 if game.get('neutral', False) else model['home_edge']
    rest_adjustment = (-1.25 if rests[h] == 0 else 0) - (-1.25 if rests[a] == 0 else 0)
    home_mean = model['league'] + model['attack'].get(h, 0) + model['concede'].get(a, 0) + home_edge / 2 + rest_adjustment / 2
    away_mean = model['league'] + model['attack'].get(a, 0) + model['concede'].get(h, 0) - home_edge / 2 - rest_adjustment / 2
    digest = hashlib.sha256(f'{VERSION}:{seed}:{game["id"]}'.encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], 'big'))
    scores = []
    for _ in range(SIMULATIONS):
        z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1)
        hs = max(0, round(home_mean + model['sigma'] * z1))
        as_ = max(0, round(away_mean + model['sigma'] * (model['rho'] * z1 + math.sqrt(1 - model['rho'] ** 2) * z2)))
        # Training scores include overtime; resolve rounded ties with a one-point
        # symmetric tiebreak to avoid adding overtime twice to this final-score model.
        if hs == as_:
            if rng.random() < 0.5:
                hs += 1
            else:
                as_ += 1
        scores.append((hs, as_))
    margins = [hs - as_ for hs, as_ in scores]
    totals = [hs + as_ for hs, as_ in scores]
    home_wins = sum(m > 0 for m in margins)
    p = home_wins / SIMULATIONS
    predicted_h = mean([x[0] for x in scores])
    predicted_a = mean([x[1] for x in scores])
    bins = []
    for lo, hi, label in [(-math.inf, -20, 'Away 21+'), (-20, -10, 'Away 11–20'),
                           (-10, 0, 'Away 1–10'), (0, 10, 'Home 1–10'),
                           (10, 20, 'Home 11–20'), (20, math.inf, 'Home 21+')]:
        bins.append({'label': label, 'count': sum(lo < m <= hi for m in margins)})
    result = {**game, 'simulations': SIMULATIONS, 'home_wins': home_wins,
              'away_wins': SIMULATIONS - home_wins, 'home_win_probability': p,
              'favorite': h if p > 0.5 else a if p < 0.5 else 'Even',
              'favorite_probability': max(p, 1 - p), 'projected_home_score': round(predicted_h, 1),
              'projected_away_score': round(predicted_a, 1),
              'projected_margin': round(mean(margins), 1), 'projected_total': round(mean(totals), 1),
              'margin_80_interval': [round(quantile(margins, q), 1) for q in (0.1, 0.9)],
              'total_80_interval': [round(quantile(totals, q), 1) for q in (0.1, 0.9)],
              'home_probability_mc_95_interval': wilson(home_wins, SIMULATIONS),
              'margin_distribution': bins, 'warnings': warnings,
              'factors': {'home_court_points': round(home_edge, 2), 'rest_margin_points': rest_adjustment,
                          'home_rest_days': rests[h], 'away_rest_days': rests[a],
                          'home': model['profiles'].get(h), 'away': model['profiles'].get(a)}}
    if odds:
        market = dict(odds)
        if 'home_spread' in odds:
            shifted = [m + odds['home_spread'] for m in margins]
            market.update(home_cover_probability=sum(v > 0 for v in shifted) / SIMULATIONS,
                          away_cover_probability=sum(v < 0 for v in shifted) / SIMULATIONS,
                          spread_push_probability=sum(v == 0 for v in shifted) / SIMULATIONS)
        if 'total' in odds:
            market.update(over_probability=sum(v > odds['total'] for v in totals) / SIMULATIONS,
                          under_probability=sum(v < odds['total'] for v in totals) / SIMULATIONS,
                          total_push_probability=sum(v == odds['total'] for v in totals) / SIMULATIONS)
        if 'home_moneyline' in odds:
            hp, ap = implied(odds['home_moneyline']), implied(odds['away_moneyline'])
            market['home_no_vig_probability'] = hp / (hp + ap)
            market['home_model_market_difference'] = p - market['home_no_vig_probability']
        result['market'] = market
    return result


def report(payload, seed=42, odds_csv=''):
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError('Seed must be an integer between 0 and 4294967295.')
    dataset = validate_dataset(payload)
    # Freeze the entire week's model at the start of that week: no within-week results.
    eastern = ZoneInfo('America/New_York')
    now = datetime.now(eastern)
    as_of = (now if day(dataset['week_start']) >= now.date() else
             datetime.fromisoformat(dataset['week_start']).replace(tzinfo=eastern))
    odds = parse_odds(odds_csv, dataset['schedule'], as_of)
    model = fit(dataset['history'], dataset['week_start'])
    results = [simulate(g, model, dataset['schedule'], seed, odds.get(g['id'])) for g in dataset['schedule']]
    return {'model_version': VERSION, 'seed': seed, 'simulations_per_game': SIMULATIONS,
            'week_start': dataset['week_start'], 'forecast_as_of': as_of.isoformat(),
            'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': dataset['mode'],
            'source': dataset['source'], 'training_games': model['games'],
            'latest_training_result': model['last_result'], 'games': results,
            'assumptions': ['Only results strictly before week_start are used; ratings are frozen for the week.',
                            '60-day exponential recency weighting; opponent-adjusted offense/defense with ridge shrinkage.',
                            'Home court is estimated with a prior; back-to-back rest adjustment is a fixed 1.25-point assumption.',
                            'Correlated Gaussian final scores; shared score variance is estimated from training residuals.',
                            'Final scores include overtime; rounded ties use a symmetric one-point tiebreak, not an overtime model.',
                            'No live injuries, lineups, player metrics, possessions, or roster adjustments are included.',
                            '80% ranges describe simulated outcomes. Monte Carlo intervals describe sampling error only, not model accuracy.',
                            'Market differences are comparisons, not validated betting edges. Odds must be observed by the forecast as-of time.']}


def backtest(all_games, start='2015-03-02', weeks=6, seed=42):
    """Weekly rolling holdout: every prediction is fit only on earlier dates."""
    from datetime import timedelta
    probabilities, actuals, errors, total_errors, covered = [], [], [], [], []
    baseline, fold_results = [], []
    for offset in range(weeks):
        begin = day(start) + timedelta(days=offset * 7)
        train = [g for g in all_games if day(g['date']) < begin]
        test = [g for g in all_games if 0 <= (day(g['date']) - begin).days < 7]
        if not test:
            continue
        model = fit(train, begin.isoformat())
        home_prior = mean([int(g['home_score'] > g['away_score']) for g in train])
        for game in test:
            clean = {k: game[k] for k in ('id', 'date', 'home', 'away', 'neutral') if k in game}
            prediction = simulate(clean, model, test, seed)
            actual = int(game['home_score'] > game['away_score'])
            probabilities.append(prediction['home_win_probability'])
            actuals.append(actual)
            baseline.append((home_prior - actual) ** 2)
            margin = game['home_score'] - game['away_score']
            errors.append(abs(prediction['projected_margin'] - margin))
            total_errors.append(abs(prediction['projected_total'] - game['home_score'] - game['away_score']))
            lo, hi = prediction['margin_80_interval']
            covered.append(lo <= margin <= hi)
        fold_results.append({'week_start': begin.isoformat(), 'training_games': len(train), 'test_games': len(test)})
    if not probabilities:
        raise ValueError('No held-out games in the selected backtest dates.')
    calibration = []
    for index in range(5):
        selected = [(p, y) for p, y in zip(probabilities, actuals) if min(int(p * 5), 4) == index]
        calibration.append({'bin': f'{index * 20}–{(index + 1) * 20}%', 'games': len(selected),
                            'mean_home_probability': mean([p for p, _ in selected]) if selected else None,
                            'actual_home_win_rate': mean([y for _, y in selected]) if selected else None})
    return {'model_version': VERSION, 'games': len(actuals), 'folds': fold_results,
            'winner_accuracy': mean([int((p > 0.5) == bool(y)) if p != 0.5 else 0.5 for p, y in zip(probabilities, actuals)]),
            'brier_score': mean([(p - y) ** 2 for p, y in zip(probabilities, actuals)]),
            'home_rate_baseline_brier': mean(baseline), 'margin_mae': mean(errors),
            'total_mae': mean(total_errors), 'margin_80_coverage': mean(covered),
            'calibration': calibration,
            'note': 'Historical development evaluation, not independent proof of future performance. No betting returns evaluated.'}
