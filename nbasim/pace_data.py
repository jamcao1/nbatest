"""Dated possession estimates and compact play-by-play research inputs from ESPN."""
import argparse
import concurrent.futures
import gzip
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import ROOT
from .lineups import BASE, fetch_json


def compact(payload):
    comp = payload['header']['competitions'][0]
    competitors = [{k:t[k] for k in ('homeAway','score','linescores')} | {
        'team':{k:t['team'][k] for k in ('id','abbreviation')}} for t in comp['competitors']]
    return {'header': {'id': payload['header']['id'], 'season': payload['header']['season'],
                       'competitions': [{'date':comp['date'],'status':comp['status'],'competitors':competitors}]},
            'boxscore': {'teams': [{'team':{k:t['team'][k] for k in ('id','abbreviation')},
                                    'statistics':[{k:s[k] for k in ('name','displayValue')} for s in t['statistics']]}
                                   for t in payload['boxscore']['teams']]},
            'plays': [{k:p[k] for k in ('id', 'sequenceNumber', 'period', 'clock', 'type', 'text',
                                      'homeScore', 'awayScore', 'team', 'shootingPlay', 'pointsAttempted',
                                      'scoringPlay', 'scoreValue', 'wallclock') if k in p} for p in payload.get('plays', [])]}


def game_stats(payload):
    comp = payload['header']['competitions'][0]
    if not comp['status']['type'].get('completed'):
        raise ValueError('Historical pace requires a completed game.')
    sides = {t['homeAway']:t for t in comp['competitors']}
    teams = {}
    for item in payload['boxscore']['teams']:
        values = {s['name']:s['displayValue'] for s in item['statistics']}
        fg = [int(v) for v in values['fieldGoalsMade-fieldGoalsAttempted'].split('-')]
        ft = [int(v) for v in values['freeThrowsMade-freeThrowsAttempted'].split('-')]
        orb, turnovers = int(values['offensiveRebounds']), int(values['totalTurnovers'])
        if not 0 <= fg[0] <= fg[1] <= 180 or not 0 <= ft[0] <= ft[1] <= 100 or not 0 <= orb <= fg[1] or not 0 <= turnovers <= 60:
            raise ValueError('Invalid team box score.')
        teams[item['team']['abbreviation']] = {'fga':fg[1], 'fta':ft[1], 'orb':orb, 'to':turnovers,
                                               'possessions':fg[1]+.44*ft[1]-orb+turnovers}
    periods = max(len(t.get('linescores', [])) for t in sides.values())
    if periods < 4:
        raise ValueError('Incomplete quarter scores.')
    duration = 48 + 5*(periods-4)
    for side, t in sides.items():
        code = t['team']['abbreviation']
        teams[code].update(points=int(t['score']), side=side,
                           quarters=[float(v.get('value', v.get('displayValue'))) for v in t['linescores']])
        if sum(teams[code]['quarters']) != teams[code]['points']:
            raise ValueError('Quarter scores do not reconcile with the final result.')
    if len(teams) != 2:
        raise ValueError('Two team box scores are required.')
    possessions = statistics.mean(t['possessions'] for t in teams.values())
    if not 60 <= possessions*48/duration <= 140:
        raise ValueError('Implausible possession estimate.')
    game_date=datetime.fromisoformat(comp['date'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    return {'id':str(payload['header']['id']), 'date':game_date,
            'season_type':payload['header']['season']['type'], 'duration':duration,
            'pace':possessions*48/duration, 'possessions':possessions, 'teams':teams}


def collect(history, cache, archive=None):
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    old = json.loads(gzip.decompress(Path(archive).read_bytes())) if archive else {'games':[]}
    indexed = {str(p['header']['id']):p for p in old['games']}
    def matches(stats, game):
        return stats['id']==game['id'] and stats['date']==game['date'] and all(
            stats['teams'].get(game[side],{}).get('points')==game[side+'_score'] and
            stats['teams'].get(game[side],{}).get('side')==side for side in ('home','away'))
    def get(g):
        try:
            if not g['id'].isdigit():
                raise ValueError('An ESPN event ID is required.')
            path = cache/(g['id']+'.json')
            payload = indexed.get(g['id'])
            if payload:
                stats = game_stats(payload)
                if not matches(stats,g):
                    payload = None
            if payload is None:
                payload = json.loads(path.read_text()) if path.exists() else compact(fetch_json(BASE+'/summary?event='+g['id']))
                stats = game_stats(payload)
                if not matches(stats,g):
                    raise ValueError('Box-score points do not match scoreboard results.')
                path.write_text(json.dumps(payload, separators=(',',':')))
            return payload, None
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return None, {'id':g['id'], 'reason':str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(get, history))
    games, rejected = [r for r,e in results if r], [e for r,e in results if e]
    if len(games) < .9*len(history):
        raise ValueError(f'Only {len(games)}/{len(history)} complete pace box scores available.')
    print(f'Pace data: {len(games)}/{len(history)} complete games; {len(rejected)} exclusions.', flush=True)
    return {'retrieved_at':datetime.now(timezone.utc).isoformat(), 'archive_retrieved_at':old.get('retrieved_at'),
            'source':BASE+'/summary', 'games':games, 'rejected':rejected}


def priors(archive):
    rows = [game_stats(g) for g in archive['games'] if g['header']['season']['type'] == 2]
    if not rows:
        raise ValueError('Regular-season box scores are required for pace priors.')
    teams = {}
    for g in rows:
        for code, t in g['teams'].items():
            opponent = next(v for c,v in g['teams'].items() if c != code)
            teams.setdefault(code, []).append({'date':g['date'], 'pace':g['pace'], 'possessions':g['possessions'],
                                               'points':t['points'], 'allowed':opponent['points'],
                                               'combined':t['points']+opponent['points']})
    league_pace = statistics.mean(g['pace'] for g in rows)
    league_ppp = sum(t['points'] for g in rows for t in g['teams'].values()) / (2*sum(g['possessions'] for g in rows))
    sample_end=datetime.fromisoformat(max(g['date'] for g in rows)).date()
    output = {}
    for code, games in teams.items():
        poss = sum(g['possessions'] for g in games)
        output[code] = {'games':len(games), 'recent_games':sum((sample_end-datetime.fromisoformat(g['date']).date()).days<=30 for g in games),
                        'pace':statistics.mean(g['pace'] for g in games),
                        'offense_ppp':sum(g['points'] for g in games)/poss,
                        'defense_ppp':sum(g['allowed'] for g in games)/poss,
                        'points_per_game':statistics.mean(g['points'] for g in games),
                        'combined_total':statistics.mean(g['combined'] for g in games),
                        'pace_range':[min(g['pace'] for g in games),max(g['pace'] for g in games)],
                        'above_league_pace_fraction':sum(g['pace']>league_pace for g in games)/len(games),
                        'latest_result':max(g['date'] for g in games)}
    for rank, code in enumerate(sorted(output, key=lambda t:output[t]['pace'], reverse=True),1):
        output[code]['pace_rank'] = rank
    for rank, code in enumerate(sorted(output, key=lambda t:output[t]['offense_ppp'], reverse=True),1):
        output[code]['offense_rank'] = rank
    return {'generated_at':datetime.now(timezone.utc).isoformat(), 'source':archive['source'],
            'archive_retrieved_at':archive.get('archive_retrieved_at'), 'games':len(rows),
            'start':min(g['date'] for g in rows), 'end':max(g['date'] for g in rows),
            'league':{'pace':league_pace,'ppp':league_ppp}, 'teams':output,
            'definition':'Estimated possessions per team per 48 minutes: average of FGA + 0.44*FTA - offensive rebounds + total turnovers for both teams, adjusted for overtime. Regular-season sample only; not official NBA tracking pace.',
            'limitations':'Historical team averages do not account for current rotations or injuries. A fast team does not play fast against every opponent. Public play-by-play can be delayed or corrected.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--save-archive',type=Path)
    parser.add_argument('--cache',type=Path,default=ROOT/'.cache/pace')
    parser.add_argument('--prepare-replay-cases',type=Path,help='Prepare the last 60 regular-season games with strictly earlier priors')
    args=parser.parse_args()
    if args.prepare_replay_cases:
        if not args.archive:parser.error('--archive is required for replay preparation')
        data=json.loads(gzip.decompress(args.archive.read_bytes()))
        regular=sorted((g for g in data['games'] if g['header']['season']['type']==2),
                       key=lambda g:g['header']['competitions'][0]['date'])
        dated=[(game_stats(g)['date'],g) for g in regular]
        cases=[]
        for g in regular[-60:]:
            cutoff=game_stats(g)['date']
            cases.append({'summary':g,'priors':priors({**data,'games':[old for date,old in dated if date<cutoff]})})
        args.prepare_replay_cases.parent.mkdir(parents=True,exist_ok=True)
        args.prepare_replay_cases.write_text(json.dumps(cases,separators=(',',':')))
        print(f'Prepared {len(cases)} chronological replay cases.',flush=True)
        return
    if not args.input or not args.output:parser.error('--input and --output are required to update priors')
    dataset=json.loads(args.input.read_text())
    data=collect(dataset['history'],args.cache,args.archive)
    if args.save_archive:
        args.save_archive.write_bytes(gzip.compress(json.dumps(data,separators=(',',':')).encode(),mtime=0))
    result=priors(data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({t:result['teams'].get(t) for t in ('MIA','DEN')},indent=2),flush=True)


if __name__=='__main__':
    main()
