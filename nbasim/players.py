"""Dated player scoring and shot-location research. No paid feed or invented shots."""
import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT, day
from .lineups import BASE, fetch_json
from .provider import EASTERN

ZONES = {'rim': ('At the rim', 2), 'paint': ('Paint · outside rim', 2),
         'mid': ('Mid-range', 2), 'corner3': ('Corner three', 3),
         'arc3': ('Above-break three', 3), 'unknown2': ('Unlocated two', 2),
         'unknown3': ('Unlocated three', 3), 'ft': ('Free throws', 1)}


def zone_for(play):
    """ESPN coordinates are feet from a hoop at (25, 0), not from the baseline."""
    worth = int(play['pointsAttempted'])
    xy = play.get('coordinate', {})
    x, y = xy.get('x'), xy.get('y')
    valid = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y))
    valid = valid and 0 <= x <= 50 and -5.25 <= y <= 88.75
    distance = math.hypot(x-25, y) if valid else None
    stated = re.search(r'(\d+)-foot', play.get('text', ''))
    if stated and valid and abs(distance-int(stated[1])) > 6:
        valid = False
    if not valid:
        return 'unknown'+str(worth), None
    if worth == 3:
        zone = 'corner3' if abs(x-25) >= 22 and y <= 9 else 'arc3'
    else:
        zone = 'rim' if distance < 4 else 'paint' if 17 <= x <= 33 and y <= 13.75 else 'mid'
    return zone, [x, y, int(play.get('scoringPlay', False)), worth]


def pair(value):
    made, attempts = map(int, value.split('-'))
    if not 0 <= made <= attempts <= 180:
        raise ValueError('Invalid made/attempted box score.')
    return made, attempts


def parse_game(raw, game):
    comp = raw['header']['competitions'][0]
    stamp = datetime.fromisoformat(comp['date'].replace('Z', '+00:00'))
    if str(raw['header']['id']) != game['id'] or stamp.astimezone(EASTERN).date().isoformat() != game['date']:
        raise ValueError('Player summary identity/date mismatch.')
    if not comp['status']['type'].get('completed'):
        raise ValueError('Player training requires a completed game.')
    duration = 48+5*(max(len(t['linescores']) for t in comp['competitors'])-4)
    if duration < 48:
        raise ValueError('Incomplete game periods.')
    players = {}
    for team in raw['boxscore']['players']:
        code = team['team']['abbreviation']
        if code not in (game['home'], game['away']):
            raise ValueError('Unexpected player team.')
        block = team['statistics'][0]
        for row in block['athletes']:
            stats = dict(zip(block['labels'], row.get('stats', [])))
            mins = stats.get('MIN', '0') if not row.get('didNotPlay') else '0'
            if mins in ('', '--') and stats.get('PTS') in (None, '', '--', '0'):
                continue
            minutes = sum(float(v)*f for v, f in zip(mins.split(':'), (1, 1/60))) if ':' in mins else float(mins or 0)
            if minutes == 0:
                continue
            pid = str(row['athlete']['id'])
            if pid in players or not 0 < minutes <= duration:
                raise ValueError('Duplicate player or invalid minutes.')
            fg, fga = pair(stats['FG']); three, tpa = pair(stats['3PT']); ft, fta = pair(stats['FT'])
            points = int(stats['PTS'])
            if three > fg or tpa > fga or 2*fg+three+ft != points:
                raise ValueError('Player points do not reconcile with baskets.')
            players[pid] = {'id': pid, 'name': row['athlete'].get('displayName', row['athlete'].get('shortName')),
                            'team': code, 'minutes': minutes, 'points': points,
                            'fgm': fg, 'fga': fga, 'threem': three, 'threea': tpa,
                            'ftm': ft, 'fta': fta, 'zones': {z: [0, 0] for z in ZONES}, 'shots': []}
    for side in ('home', 'away'):
        team_players = [p for p in players.values() if p['team'] == game[side]]
        if sum(p['points'] for p in team_players) != game[side+'_score']:
            raise ValueError('Player scoring does not reconcile with the team result.')
        if abs(sum(p['minutes'] for p in team_players)-5*duration) > 6:
            raise ValueError('Incomplete player-minute coverage.')
    seen = set()
    for play in raw.get('plays', []):
        if not play.get('shootingPlay') or play.get('pointsAttempted') not in (2, 3):
            continue
        if play['id'] in seen:
            raise ValueError('Duplicate shot event.')
        seen.add(play['id'])
        participants = play.get('participants', [])
        pid = str(participants[0]['athlete']['id']) if participants else ''
        if pid not in players:
            continue
        zone, xy = zone_for(play)
        players[pid]['zones'][zone][0] += int(play.get('scoringPlay', False))
        players[pid]['zones'][zone][1] += 1
        if xy is not None:
            players[pid]['shots'].append(xy)
    for p in players.values():
        counts = {v: [sum(p['zones'][z][i] for z in ZONES if ZONES[z][1] == v) for i in (0, 1)] for v in (2, 3)}
        reconciled = counts[2] == [p['fgm']-p['threem'], p['fga']-p['threea']] and counts[3] == [p['threem'], p['threea']]
        p['locations_reconciled'] = reconciled
        if not reconciled:
            p['zones'] = {z: [0, 0] for z in ZONES}
            p['zones']['unknown2'] = [p['fgm']-p['threem'], p['fga']-p['threea']]
            p['zones']['unknown3'] = [p['threem'], p['threea']]
            p['shots'] = []
        p['zones']['ft'] = [p['ftm'], p['fta']]
    possessions = []
    for t in raw['boxscore']['teams']:
        s = {x['name']: x['displayValue'] for x in t['statistics']}
        possessions.append(pair(s['fieldGoalsMade-fieldGoalsAttempted'])[1]+.44*pair(s['freeThrowsMade-freeThrowsAttempted'])[1]
                           -int(s['offensiveRebounds'])+int(s['totalTurnovers']))
    pace = statistics.mean(possessions)*48/duration
    if not 60 <= pace <= 140:
        raise ValueError('Implausible game pace.')
    venue = raw.get('gameInfo', {}).get('venue', {})
    return {**game, 'start': comp['date'], 'pace': pace, 'duration': duration, 'players': players,
            'venue': {'id': str(venue.get('id', '')), 'name': venue.get('fullName', 'Venue unavailable')}}


def collect(history, archive=None, cache=ROOT/'.cache/player-shots'):
    indexed = {g['id']: g for g in archive.get('games', [])} if archive else {}
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    def matches(row, g):
        return all(row.get(k) == g.get(k) for k in ('id', 'date', 'home', 'away', 'home_score', 'away_score'))
    def one(g):
        try:
            old = indexed.get(g['id'])
            if old and matches(old, g):
                return old, None
            path = cache/(g['id']+'.json')
            old = json.loads(path.read_text()) if path.exists() else None
            if old and matches(old, g):
                return old, None
            parsed = parse_game(fetch_json(BASE+'/summary?event='+g['id']), g)
            path.write_text(json.dumps(parsed, separators=(',', ':'), allow_nan=False))
            return parsed, None
        except (KeyError, ValueError, TypeError, OSError) as exc:
            return None, {'id': g['id'], 'reason': str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, history))
    games = sorted([g for g, _ in results if g], key=lambda g: (g['date'], g['id']))
    if not games or len(games) < .9*len(history):
        raise ValueError(f'Only {len(games)}/{len(history)} complete player summaries available.')
    print(f'Player shot research: {len(games)}/{len(history)} complete games.', flush=True)
    return {'source': BASE+'/summary', 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'games': games, 'excluded': [e for _, e in results if e]}


def fit_history(games, cutoff):
    """Every model input predates the forecast's New York calendar date."""
    rows = [g for g in games if 0 < (day(cutoff)-day(g['date'])).days <= 365]
    if not rows:
        raise ValueError('No prior player games available.')
    histories, teams, allowed = {}, {}, {}
    league = {z: [0., 0.] for z in ZONES}
    for g in rows:
        for code in (g['home'], g['away']):
            teams.setdefault(code, []).append(g)
        for pid, p in g['players'].items():
            opponent = g['away'] if p['team'] == g['home'] else g['home']
            histories.setdefault(pid, []).append((g, p))
            defense = allowed.setdefault(opponent, {z: [0., 0.] for z in ZONES})
            for z, values in p['zones'].items():
                for i in (0, 1):
                    league[z][i] += values[i]; defense[z][i] += values[i]
    for z, (_, worth) in ZONES.items():
        if league[z][1] == 0:
            same = [v for k, v in league.items() if ZONES[k][1] == worth]
            league[z] = [sum(v[0] for v in same), sum(v[1] for v in same)]
    return {'rows': rows, 'histories': histories, 'teams': teams, 'allowed': allowed, 'league': league,
            'pace': statistics.mean(g['pace'] for g in rows)}


def rotation(roster, model):
    result = []
    for p in roster:
        history = model['histories'].get(p['id'], [])[-10:]
        out = any(i.get('status', '').lower() in ('out', 'suspension', 'suspended') for i in p.get('injuries', []))
        weight = statistics.mean(row['minutes']*48/g['duration'] for g, row in history) if history else 8.
        result.append({**p, 'minutes': 0., 'weight': 0 if out else weight, 'excluded': out})
    active = [p for p in result if p['weight'] > 0]
    remaining = 240.
    while active:
        total = sum(p['weight'] for p in active)
        capped = [p for p in active if remaining*p['weight']/total > 48]
        if not capped:
            for p in active:
                p['minutes'] = remaining*p['weight']/total
            break
        for p in capped:
            p['minutes'] = 48.; remaining -= 48; active.remove(p)
    return result


def project_player(player, team, opponent, home, venue_id, model):
    history = model['histories'].get(player['id'], [])[-20:]
    result = {k: player[k] for k in ('id', 'name', 'minutes', 'injuries', 'excluded') if k in player}
    result.update(team=team, games=len(history), status='available', zones=[], shots=[])
    if len(history) < 3 or sum(p['minutes'] for _, p in history) < 60:
        return {**result, 'status': 'insufficient_history', 'expected_points': None}
    latest = history[-1][0]['date']
    weighted = [(g, p, math.exp(-(day(latest)-day(g['date'])).days/45)) for g, p in history]
    exposure = sum(p['minutes']*w for _, p, w in weighted)
    historic_pace = sum(g['pace']*p['minutes']*w for g, p, w in weighted)/exposure
    team_pace = lambda code: (sum(g['pace'] for g in model['teams'].get(code, [])[-20:])+10*model['pace'])/(len(model['teams'].get(code, [])[-20:])+10)
    matchup_pace = (team_pace(team)+team_pace(opponent))/2
    pace_factor = max(.9, min(1.1, matchup_pace/historic_pace))
    total_attempts = sum((p['fga']+.44*p['fta'])*w for _, p, w in weighted)
    side_rows = [(g, p, w) for g, p, w in weighted if (g['home'] == p['team']) == home and not g.get('neutral')]
    side_minutes = sum(p['minutes']*w for _, p, w in side_rows)
    side_attempts = sum((p['fga']+.44*p['fta'])*w for _, p, w in side_rows)
    base_rate = total_attempts/exposure
    venue_factor = max(.95, min(1.05, (side_attempts+300*base_rate)/(side_minutes+300)/base_rate)) if base_rate else 1.
    expected = 0
    for z, (label, worth) in ZONES.items():
        made = sum(p['zones'][z][0]*w for _, p, w in weighted)
        attempts = sum(p['zones'][z][1]*w for _, p, w in weighted)
        lm, la = model['league'][z]
        league_pct = lm/la if la else .5
        dm, da = model['allowed'].get(opponent, model['league'])[z]
        defense = max(.9, min(1.1, ((dm+50*league_pct)/(da+50))/league_pct)) if league_pct and z != 'ft' else 1.
        accuracy = min(.98, (made+20*league_pct)/(attempts+20)*defense)
        rate = attempts/exposure*pace_factor*venue_factor
        predicted_attempts = player['minutes']*rate
        predicted_made = predicted_attempts*accuracy
        expected += worth*predicted_made
        result['zones'].append({'id': z, 'label': label, 'worth': worth, 'rate': rate, 'accuracy': accuracy,
                                'attempts': predicted_attempts, 'made': predicted_made,
                                'misses': predicted_attempts-predicted_made, 'points': worth*predicted_made,
                                'historical_made': sum(p['zones'][z][0] for _, p in history),
                                'historical_attempts': sum(p['zones'][z][1] for _, p in history),
                                'opponent_accuracy_factor': defense})
    venue_rows = [p for g, p in history if venue_id and g['venue']['id'] == venue_id]
    result.update(expected_points=expected, latest_result=latest,
                  history_start=history[0][0]['date'], points_per_game=statistics.mean(p['points'] for _, p in history),
                  pace_factor=pace_factor, venue_factor=venue_factor, matchup_pace=matchup_pace,
                  venue_games=len(venue_rows), venue_ppg=statistics.mean(p['points'] for p in venue_rows) if venue_rows else None,
                  last_games=[{'date': g['date'], 'opponent': g['away'] if p['team'] == g['home'] else g['home'],
                               'minutes': p['minutes'], 'points': p['points']} for g, p in history[-10:]],
                  shots=[s+[g['date']] for g, p in history for s in p['shots']][-150:],
                  located_attempts=sum(len(p['shots']) for _, p in history),
                  historical_attempts=sum(p['fga'] for _, p in history))
    return result


def context(raw, game):
    comp = raw['header']['competitions'][0]
    sides = {t['homeAway']: t['team']['abbreviation'] for t in comp['competitors']}
    stamp = datetime.fromisoformat(comp['date'].replace('Z', '+00:00'))
    if (str(raw['header']['id']) != game['id'] or sides != {'home': game['home'], 'away': game['away']}
            or stamp.tzinfo is None or stamp.astimezone(EASTERN).date().isoformat() != game['date']):
        raise ValueError('Matchup context returned a different game.')
    venue = raw.get('gameInfo', {}).get('venue', {})
    markets = []
    for quote in raw.get('pickcenter', [])[:3]:
        def line(kind, side, when):
            value = quote.get(kind, {}).get(side, {}).get(when, {}).get('line')
            if value is None:
                return None
            try:
                number = float(str(value).lstrip('ou'))
                return number if math.isfinite(number) else None
            except ValueError:
                return None
        markets.append({'provider': quote.get('provider', {}).get('name', 'Unknown'),
                        'total_open': line('total', 'over', 'open'), 'total_latest': line('total', 'over', 'close'),
                        'home_spread_open': line('pointSpread', 'home', 'open'), 'home_spread_latest': line('pointSpread', 'home', 'close')})
    injuries = {str(i['athlete']['id']): [{'status': i.get('status', 'Unknown'), 'date': i.get('date')}]
                for group in raw.get('injuries', []) for i in group.get('injuries', [])}
    return {'start': comp['date'], 'venue': {'id': str(venue.get('id', '')), 'name': venue.get('fullName', 'Venue unavailable'),
                                           'city': venue.get('address', {}).get('city', '')},
            'state': comp['status']['type']['state'], 'markets': markets, 'injuries': injuries,
            'source': BASE+'/summary?event='+game['id'], 'retrieved_at': datetime.now(timezone.utc).isoformat()}


def build(dataset, archive, rosters):
    if day(dataset['week_start']) < datetime.now(EASTERN).date():
        raise ValueError('Current rosters cannot describe a historical forecast.')
    if rosters.get('status') != 'experimental_not_applied' or rosters.get('week_start') != dataset['week_start']:
        raise ValueError('Matching current roster research is required.')
    stamp = datetime.fromisoformat(rosters['generated_at'])
    if stamp.tzinfo is None or not -300 <= (datetime.now(timezone.utc)-stamp).total_seconds() <= 86400:
        raise ValueError('Current rosters are over a day old.')
    model = fit_history(archive['games'], dataset['week_start'])
    def one(game):
        try:
            ctx = context(fetch_json(BASE+'/summary?event='+game['id']), game)
            teams = {}
            for side in ('away', 'home'):
                code = game[side]; opponent = game['home' if side == 'away' else 'away']
                roster = [{**p, 'injuries': ctx['injuries'].get(p['id'], p.get('injuries', []))} for p in rosters['teams'][code]['players']]
                players = [project_player(p, code, opponent, None if game.get('neutral') else side == 'home', ctx['venue']['id'], model)
                           for p in rotation(roster, model)]
                players.sort(key=lambda p: (p.get('excluded', False), -(p['expected_points'] or 0), p['id']))
                leaders = [p for p in players if not p.get('excluded') and p['expected_points'] is not None]
                teams[code] = {'players': players, 'leader_id': leaders[0]['id'] if leaders else None,
                               'roster_source': rosters['teams'][code]['source']}
            return {**game, **ctx, 'teams': teams, 'status': 'available'}
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return {**game, 'status': 'unavailable', 'reason': str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        games = list(pool.map(one, dataset['schedule']))
    # A player's observed shots do not change with the opponent. Publish them
    # once instead of repeating hundreds of locations for every scheduled game.
    profiles = {}
    shared = ('games', 'latest_result', 'history_start', 'points_per_game', 'last_games',
              'shots', 'located_attempts', 'historical_attempts')
    for game in games:
        for team in game.get('teams', {}).values():
            for player in team['players']:
                common = {key: player.pop(key) for key in shared if key in player}
                profiles.setdefault(player['id'], common)
    return {'status': 'experimental', 'version': 'player-zones-v1', 'week_start': dataset['week_start'],
            'generated_at': datetime.now(timezone.utc).isoformat(), 'roster_generated_at': rosters['generated_at'],
            'history_start': min(g['date'] for g in model['rows']), 'history_end': max(g['date'] for g in model['rows']),
            'history_games': len(model['rows']), 'excluded_games': archive.get('excluded', []),
            'source': archive['source'], 'games': games, 'profiles': profiles,
            'scope': 'Regulation scoring scenario, conditional on playing the estimated minutes. Overtime excluded.',
            'limitations': ['Projected scoring leader means highest expected points among current roster players with sufficient history, not best overall player.',
                            'Current injuries are dated source snapshots; Out players are excluded. Other estimates are conditional on playing.',
                            'Historical shot locations and opponent tendencies may be from last season; offseason role changes and defenders are not modeled.',
                            'Venue identity and historical venue splits are displayed. Only a shrunk home/away usage association changes the estimate; no arena-specific causal effect is assumed.',
                            'Game-line movement uses available opening/latest quotes from one source, not betting volume or a complete market history. Player prop lines are not supplied.',
                            'Model ranges are uncalibrated. No betting advantage or guaranteed scorer is claimed.']}


def evaluate(archive, count=40):
    rows = sorted(archive['games'], key=lambda g: (g['date'], g['id']))
    outcomes = []
    for target in rows[-count:]:
        model = fit_history(rows, target['date'])
        old = {}
        for g in model['rows']:
            for code in (g['home'], g['away']):
                old[code] = [{'id': p['id'], 'name': p['name'], 'injuries': []} for p in g['players'].values() if p['team'] == code]
        for side in ('home', 'away'):
            team = target[side]; opponent = target['away' if side == 'home' else 'home']
            projections = [project_player(p, team, opponent, None if target.get('neutral') else side == 'home', target['venue']['id'], model)
                           for p in rotation(old.get(team, []), model)]
            eligible = [p for p in projections if p['expected_points'] is not None]
            if not eligible:
                continue
            leader = max(eligible, key=lambda p: p['expected_points'])
            actual = target['players'].get(leader['id'], {}).get('points', 0)
            # Historical full-game points can include overtime; normalize evaluation
            # outcomes and comparison baseline to the regulation scope consistently.
            actual *= 48/target['duration']
            hist = model['histories'][leader['id']][-10:]
            baseline = statistics.mean(p['points']*48/g['duration'] for g, p in hist)
            outcomes.append({'date': target['date'], 'id': target['id'], 'team': team, 'player': leader['id'],
                             'model_error': abs(actual-leader['expected_points']), 'baseline_error': abs(actual-baseline)})
    return {'games': len({x['id'] for x in outcomes}), 'leaders': len(outcomes),
            'start': min(x['date'] for x in outcomes), 'end': max(x['date'] for x in outcomes),
            'mae': statistics.mean(x['model_error'] for x in outcomes),
            'baseline_mae': statistics.mean(x['baseline_error'] for x in outcomes),
            'note': 'Development replay on the last 40 archived games. Both forecasts score the same pregame-selected players, including zero if absent. '
                    'Each prior uses earlier calendar dates; historical rosters use the last earlier box score, not target-game participants. '
                    'Overtime results are normalized to 48 minutes, not actual regulation-only scoring. Historical injury reports, current trades, '
                    'rookies, interval coverage, and player-prop profitability are not validated.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--rosters', type=Path)
    parser.add_argument('--archive', type=Path, default=ROOT/'data/player_shots_2026.json.gz')
    parser.add_argument('--save-archive', type=Path)
    parser.add_argument('--evaluate', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-unavailable', action='store_true')
    args = parser.parse_args()
    archive = json.loads(gzip.decompress(args.archive.read_bytes())) if args.archive.exists() else None
    try:
        if args.evaluate:
            result = evaluate(archive)
            result['archive_sha256'] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        else:
            dataset = json.loads(args.input.read_text())
            archive = collect(dataset['history'], archive)
            if args.save_archive:
                args.save_archive.write_bytes(gzip.compress(json.dumps(archive, separators=(',', ':'), allow_nan=False).encode(), mtime=0))
            result = build(dataset, archive, json.loads(args.rosters.read_text())) if args.rosters else {'status': 'archive_saved'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if not args.allow_unavailable:
            raise
        result = {'status': 'unavailable', 'reason': str(exc), 'generated_at': datetime.now(timezone.utc).isoformat(), 'games': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n')
    print('Saved', args.output, result['status'] if 'status' in result else result, flush=True)


if __name__ == '__main__':
    main()
