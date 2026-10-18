"""Experimental player-minute model and dated roster context, separate from production forecasts.

Game-level ridge coefficients are associations, not causal player impact estimates.
Historical projections use only the latest box-score roster available before the
forecast cutoff. They never use the target game's participants or minutes.
"""
import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import day, validate_dataset
from .model import fit, mean, simulate
from .provider import EASTERN

BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'


def fetch_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Courtside-NBA-Lab/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(10_000_001)
    if raw[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            raw = compressed.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError('Player data response exceeded the size limit.')
    return json.loads(raw)


def parse_boxscore(payload, game):
    header = payload['header']
    comp = header['competitions'][0]
    played = datetime.fromisoformat(comp['date'].replace('Z', '+00:00'))
    if str(header['id']) != game['id'] or played.astimezone(EASTERN).date().isoformat() != game['date']:
        raise ValueError('Box score identity/date differs from the training game.')
    if not comp.get('status', {}).get('type', {}).get('completed'):
        raise ValueError('Player training requires a completed game.')
    teams, unidentified_dnp = {}, []
    for team in payload['boxscore']['players']:
        code = team['team']['abbreviation']
        block = team['statistics'][0]
        names = block['labels']
        players = []
        for row in block['athletes']:
            stats = dict(zip(names, row.get('stats', [])))
            minutes = stats.get('MIN', '0') if not row.get('didNotPlay') else '0'
            if ':' in minutes:
                minutes, seconds = minutes.split(':')
                minutes = float(minutes) + float(seconds) / 60
            else:
                minutes = float(minutes or 0)
            points = int(stats.get('PTS', 0) or 0)
            if not math.isfinite(minutes) or not 0 <= minutes <= 80 or points < 0:
                raise ValueError('Invalid player minutes or points.')
            if not row['athlete'].get('id'):
                if minutes == 0 and points == 0 and row.get('didNotPlay'):
                    unidentified_dnp.append({'team': code, 'name': row['athlete'].get('shortName', 'Unknown')})
                    continue
                raise ValueError('A participating player has no stable identifier.')
            players.append({'id': str(row['athlete']['id']), 'name': row['athlete'].get('displayName', row['athlete'].get('shortName', 'Unknown')),
                            'minutes': minutes, 'points': points})
        if len({p['id'] for p in players}) != len(players):
            raise ValueError('Duplicate player in box score.')
        side = 'home' if code == game['home'] else 'away' if code == game['away'] else None
        if side is None or sum(p['points'] for p in players) != game[side + '_score']:
            raise ValueError('Player points/teams disagree with the final score.')
        total = sum(p['minutes'] for p in players)
        # ESPN may round individual minutes; overtime adds 25 team-minutes.
        if not any(abs(total - (240 + 25 * overtime)) <= 6 for overtime in range(7)):
            raise ValueError('Incomplete player-minute totals.')
        teams[code] = players
    if set(teams) != {game['home'], game['away']}:
        raise ValueError('Both teams need complete box scores.')
    return {**game, 'players': teams, 'unidentified_dnp': unidentified_dnp}


def collect_boxes(history, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    def get(game):
        if not game['id'].isdigit():
            raise ValueError('ESPN game IDs must be numeric.')
        path = cache / (game['id'] + '.json')
        if path.exists():
            cached = json.loads(path.read_text())
            if all(cached.get(k) == v for k, v in game.items()):
                return cached
        parsed = parse_boxscore(fetch_json(BASE + '/summary?event=' + game['id']), game)
        path.write_text(json.dumps(parsed, allow_nan=False))
        return parsed
    def checked(game):
        try:
            return get(game), None
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return None, {'id': game['id'], 'date': game['date'], 'reason': str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(checked, history))
    rejected = [error for _, error in results if error]
    (cache / 'rejected.json').write_text(json.dumps(rejected, indent=2))
    accepted = [game for game, _ in results if game]
    print(f'Player box-score coverage: {len(accepted)}/{len(history)}; {len(rejected)} rejected incomplete records.', flush=True)
    if len(accepted) < .95 * len(history):
        raise ValueError('Fewer than 95% of training games have usable player box scores; inspect rejected.json.')
    return sorted(accepted, key=lambda g: (g['date'], g['id']))


def current_rosters():
    payload = fetch_json(BASE + '/teams?limit=100')
    teams = payload['sports'][0]['leagues'][0]['teams']
    def get(item):
        team = item['team']
        url = BASE + '/teams/' + team['id'] + '/roster'
        data = fetch_json(url)
        stamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Roster timestamp has no timezone.')
        age = datetime.now(timezone.utc) - stamp
        if not timedelta(minutes=-5) <= age <= timedelta(days=1):
            raise ValueError('Roster timestamp is stale or invalid for ' + team['abbreviation'])
        players = [{'id': str(p['id']), 'name': p['displayName'],
                    'injuries': [{'status': i.get('status', 'Unknown'), 'date': i.get('date')}
                                 for i in p.get('injuries', [])]}
                   for p in data.get('athletes', [])]
        if not players or len({p['id'] for p in players}) != len(players):
            raise ValueError('Empty or duplicate current roster for ' + team['abbreviation'])
        return team['abbreviation'], {'players': players, 'source': url,
                                      'provider_timestamp': data.get('timestamp'),
                                      'season': data.get('season', {}).get('displayName')}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result = dict(pool.map(get, teams))
    if len(result) != 30:
        raise ValueError('Expected all 30 NBA rosters.')
    ids = [p['id'] for roster in result.values() for p in roster['players']]
    if len(ids) != len(set(ids)):
        raise ValueError('A player appears on multiple current rosters; provider update may be incomplete.')
    return result


def before(boxes, cutoff):
    return sorted((g for g in boxes if 0 < (day(cutoff) - day(g['date'])).days <= 365),
                  key=lambda g: (g['date'], g['id']))


def player_model(boxes, cutoff, home_edge, ridge=12.0):
    """Fit regularized game-margin associations with player minutes / 48.

    Normalize overtime to 240 team-minutes. Fixed penalty and decay are selected
    before evaluation, not tuned to the holdout scores.
    """
    rows = before(boxes, cutoff)
    observations, columns, baseline = [], {}, {}
    for g in rows:
        weight = math.exp(-(day(cutoff) - day(g['date'])).days / 60)
        features = {}
        for side, sign in (('home', 1), ('away', -1)):
            team = g[side]
            players = g['players'][team]
            total = sum(p['minutes'] for p in players)
            aggregate = baseline.setdefault(team, {'weight': 0, 'shares': {}})
            aggregate['weight'] += weight
            for p in players:
                share = 5 * p['minutes'] / total
                features[p['id']] = features.get(p['id'], 0) + sign * share
                aggregate['shares'][p['id']] = aggregate['shares'].get(p['id'], 0) + weight * share
        target = g['home_score'] - g['away_score'] - (0 if g.get('neutral') else home_edge)
        index = len(observations)
        observations.append([target, weight])
        for pid, share in features.items():
            if share:
                columns.setdefault(pid, []).append((index, share))
    coefficients = dict.fromkeys(columns, 0.0)
    residual = [r[0] for r in observations]
    for _ in range(150):
        largest = 0
        for pid in sorted(columns):
            entries = columns[pid]
            old = coefficients[pid]
            denominator = ridge + sum(observations[i][1] * x * x for i, x in entries)
            new = sum(observations[i][1] * x * (residual[i] + old * x) for i, x in entries) / denominator
            delta = new - old
            coefficients[pid] = new
            for i, x in entries:
                residual[i] -= delta * x
            largest = max(largest, abs(delta))
        if largest < 1e-7:
            break
    strength = {t: sum(coefficients.get(pid, 0) * value / agg['weight']
                       for pid, value in agg['shares'].items()) for t, agg in baseline.items()}
    return {'coefficients': coefficients, 'baseline_strength': strength}


def project_minutes(roster, boxes, cutoff):
    """Last five box-score appearances (including DNPs), capped at 48, total 240.

    Unknown players receive an explicit eight-minute allocation prior. No claim
    of a coach-confirmed rotation or current-game medical availability is made.
    """
    rows = before(boxes, cutoff)
    samples = {}
    for g in rows:
        for players in g['players'].values():
            total = sum(p['minutes'] for p in players)
            for p in players:
                samples.setdefault(p['id'], []).append((g['date'], p['minutes'] * 240 / total, p['points']))
    projected = []
    for p in roster:
        observed = samples.get(p['id'], [])
        played = [x for x in observed if x[1] > 0]
        weight = mean([x[1] for x in observed[-5:]]) if observed else 8.0
        projected.append({**p, 'allocation_weight': weight, 'minutes': 0.0,
                          'history_games': len(observed),
                          'history_minutes': round(sum(x[1] for x in observed), 1),
                          'latest_result': observed[-1][0] if observed else None,
                          'games_played': len(played),
                          'points_per_game': round(mean([x[2] for x in played]), 1) if played else None,
                          'unknown_player_prior': not bool(observed)})
    if len(projected) < 5:
        raise ValueError('A rotation requires at least five players.')
    remaining = 240.0
    active = list(projected)
    while active:
        total = sum(p['allocation_weight'] for p in active)
        allocations = [remaining * p['allocation_weight'] / total if total else remaining / len(active) for p in active]
        capped = [(p, value) for p, value in zip(active, allocations) if value > 48]
        if not capped:
            for p, value in zip(active, allocations):
                p['minutes'] = value
            break
        for p, _ in capped:
            p['minutes'] = 48.0
            remaining -= 48
            active.remove(p)
    return sorted(projected, key=lambda p: (-p['minutes'], p['id']))


def roster_delta(rotation, model, team):
    strength = sum(model['coefficients'].get(p['id'], 0) * p['minutes'] / 48 for p in rotation)
    return strength - model['baseline_strength'].get(team, 0)


def adjusted_team_model(model, deltas):
    # Net strength changes split equally between points scored and conceded;
    # this keeps the projected game total unchanged before rounding.
    result = {**model, 'attack': dict(model['attack']), 'concede': dict(model['concede'])}
    for team, delta in deltas.items():
        result['attack'][team] = result['attack'].get(team, 0) + delta / 2
        result['concede'][team] = result['concede'].get(team, 0) - delta / 2
    return result


def evaluate(boxes, start='2026-03-09', weeks=6, seed=42):
    folds, outcomes = [], []
    for week in range(weeks):
        cutoff = (day(start) + timedelta(days=7 * week)).isoformat()
        training = before(boxes, cutoff)
        target = [g for g in boxes if 0 <= (day(g['date']) - day(cutoff)).days < 7]
        if len(training) < 30 or not target:
            raise ValueError('Insufficient chronological data for the requested evaluation.')
        team_model = fit(training, cutoff)
        players = player_model(training, cutoff, team_model['home_edge'])
        rosters = {}
        for g in training:
            rosters.update(g['players'])
        rotations = {t: project_minutes(r, training, cutoff) for t, r in rosters.items()}
        deltas = {t: roster_delta(r, players, t) for t, r in rotations.items()}
        candidate = adjusted_team_model(team_model, deltas)
        # Scheduled teams/dates are known; held-out participants and minutes are not.
        schedule = [{k: g[k] for k in ('id', 'date', 'home', 'away', 'neutral')} for g in target]
        for game, actual in zip(schedule, target):
            base = simulate(game, team_model, schedule, seed)
            change = simulate(game, candidate, schedule, seed)
            margin = actual['home_score'] - actual['away_score']
            winner = int(margin > 0)
            outcomes.append({'id': game['id'], 'date': game['date'],
                             'baseline_brier': (base['home_win_probability'] - winner) ** 2,
                             'candidate_brier': (change['home_win_probability'] - winner) ** 2,
                             'baseline_margin_error': abs(base['projected_margin'] - margin),
                             'candidate_margin_error': abs(change['projected_margin'] - margin)})
        folds.append({'week_start': cutoff, 'training_games': len(training), 'test_games': len(target)})
    metrics = {key: mean([o[key] for o in outcomes]) for key in
               ('baseline_brier', 'candidate_brier', 'baseline_margin_error', 'candidate_margin_error')}
    return {'start': start, 'end': (day(start) + timedelta(days=7 * weeks - 1)).isoformat(),
            'games': len(outcomes), 'folds': folds, **metrics,
            'improved_both_metrics': metrics['candidate_brier'] < metrics['baseline_brier'] and
                                     metrics['candidate_margin_error'] < metrics['baseline_margin_error'],
            'note': 'Both models use the same complete-box-score subset. Development evaluation on one partial season. Historical rosters are inferred from the last '
                    'pre-cutoff box score; transactions and injury reports are unavailable. This does not validate '
                    'offseason trades, rookie projections, or future performance. Current rosters are never used in this backtest.'}


def analyze(dataset, boxes, rosters):
    cutoff = dataset['week_start']
    training = before(boxes, cutoff)
    baseline = fit(training, cutoff)
    player_fit = player_model(training, cutoff, baseline['home_edge'])
    old_rosters = {}
    for g in training:
        old_rosters.update(g['players'])
    teams = {}
    for team, roster in sorted(rosters.items()):
        rotation = project_minutes(roster['players'], training, cutoff)
        old_ids = {p['id'] for p in old_rosters.get(team, [])}
        current_ids = {p['id'] for p in rotation}
        teams[team] = {**roster, 'players': rotation,
                       'comparison_date': max((g['date'] for g in training if team in g['players']), default=None),
                       'added_since_last_box': [p['name'] for p in rotation if p['id'] not in old_ids],
                       'absent_since_last_box': [p['name'] for p in old_rosters.get(team, []) if p['id'] not in current_ids],
                       'unknown_minutes_share': sum(p['minutes'] for p in rotation if p['unknown_player_prior']) / 240,
                       'experimental_net_points': roster_delta(rotation, player_fit, team)}
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'week_start': cutoff,
            'source': BASE, 'training_games': len(training), 'latest_training_result': training[-1]['date'],
            'status': 'experimental_not_applied', 'teams': teams,
            'assumptions': [
                'Current roster membership is fetched from ESPN; changes are relative to the last observed box-score roster, not a verified transaction log.',
                'Minutes are estimates from the last five box-score appearances, including DNPs, normalized to 240 and capped at 48 per player.',
                'Players without observed history receive an eight-minute allocation prior and zero-centered strength prior; rookies are not individually rated.',
                'Injury statuses are source snapshots, not confirmed game availability, and do not change these experimental minutes.',
                'Player coefficients are regularized associations between minute shares and game margins; they do not isolate causal player impact.',
                'The experimental adjustment is not applied to the published score or win predictions.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Validated live dataset with completed history')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=Path('.cache/player-boxes'))
    parser.add_argument('--evaluation-start', default='2026-03-09')
    parser.add_argument('--backtest-input', type=Path, help='Archived .json.gz player boxes for an offline evaluation')
    parser.add_argument('--evaluation-file', type=Path, help='Previously computed evaluation to include with current rosters')
    parser.add_argument('--allow-unavailable', action='store_true', help='Write an explicit unavailable status on roster feed failure')
    args = parser.parse_args()
    if args.backtest_input:
        raw = args.backtest_input.read_bytes()
        archived = json.loads(gzip.decompress(raw))
        result = evaluate(archived['games'], args.evaluation_start)
        result.update(source=archived['source'], retrieved_at=archived['retrieved_at'],
                      archive_sha256=hashlib.sha256(raw).hexdigest(),
                      excluded_games=archived['rejected_boxes'])
    elif args.input:
        dataset = validate_dataset(json.loads(args.input.read_text()))
        try:
            if day(dataset['week_start']) < datetime.now(EASTERN).date():
                raise ValueError('Current roster snapshots cannot describe a historical forecast.')
            boxes = collect_boxes(dataset['history'], args.cache)
            print(f'Validated {len(boxes)} complete player box scores.', flush=True)
            result = analyze(dataset, boxes, current_rosters())
            result['rejected_boxes'] = json.loads((args.cache / 'rejected.json').read_text())
            result['requested_training_games'] = len(dataset['history'])
            if args.evaluation_file:
                result['evaluation'] = json.loads(args.evaluation_file.read_text())
            else:
                result['evaluation'] = evaluate(boxes, args.evaluation_start)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            if not args.allow_unavailable:
                raise
            result = {'status': 'unavailable', 'week_start': dataset['week_start'],
                      'generated_at': datetime.now(timezone.utc).isoformat(),
                      'reason': str(exc), 'teams': {}}
    else:
        parser.error('--input or --backtest-input is required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result.get('evaluation', {'status': result.get('status', 'evaluation complete')}), indent=2), flush=True)
    print(f'Saved {args.output}', flush=True)


if __name__ == '__main__':
    main()
