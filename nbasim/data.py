"""Validated, provider-independent game inputs."""
import csv
import io
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def day(value):
    if not isinstance(value, str):
        raise ValueError('Dates must use YYYY-MM-DD.')
    return date.fromisoformat(value)


def number(value, field, low, high):
    if isinstance(value, bool):
        raise ValueError(f'{field} must be a number.')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{field} must be a number.') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{field} must be between {low} and {high}.')
    return result


def games(rows, completed):
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('Game inputs must be a list of at most 5,000 games.')
    seen, output = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each game must be an object.')
        item = {}
        for key in ('id', 'date', 'home', 'away'):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 100:
                raise ValueError(f'Each game needs a nonempty {key} (at most 100 characters).')
            item[key] = value.strip()
        day(item['date'])
        if item['id'] in seen:
            raise ValueError(f'Duplicate game ID: {item["id"]}')
        seen.add(item['id'])
        if item['home'] == item['away']:
            raise ValueError('A team cannot play itself.')
        if not isinstance(row.get('neutral', False), bool):
            raise ValueError('neutral must be true or false.')
        item['neutral'] = row.get('neutral', False)
        if completed:
            for key in ('home_score', 'away_score'):
                val = number(row.get(key), key, 0, 300)
                if not val.is_integer():
                    raise ValueError('Final scores must be integers.')
                item[key] = int(val)
            if item['home_score'] == item['away_score']:
                raise ValueError('Completed NBA games cannot end in a tie.')
        output.append(item)
    return sorted(output, key=lambda x: (x['date'], x['id']))


def validate_dataset(payload):
    if not isinstance(payload, dict):
        raise ValueError('Dataset must be a JSON object.')
    history = games(payload.get('history'), True)
    schedule = games(payload.get('schedule'), False)
    if not history:
        raise ValueError('Provide completed games to train the model.')
    if len(schedule) > 100:
        raise ValueError('Select at most 100 games per report.')
    cutoff = day(payload.get('week_start'))
    if any(not 0 <= (day(g['date']) - cutoff).days < 7 for g in schedule):
        raise ValueError('Scheduled games must fall within seven days of week_start.')
    history = [g for g in history if day(g['date']) < cutoff]
    if len(history) < 30:
        raise ValueError('At least 30 completed games before week_start are required.')
    overlapping = {g['id'] for g in history} & {g['id'] for g in schedule}
    if overlapping:
        raise ValueError('History and schedule must have different game IDs.')
    return {'history': history, 'schedule': schedule, 'week_start': cutoff.isoformat(),
            'mode': str(payload.get('mode', 'imported'))[:100],
            'source': str(payload.get('source', 'User-supplied data'))[:1000]}


def demo_dataset(week='2015-04-06'):
    season = json.loads((ROOT / 'data/season_2015.json').read_text())
    start = day(week)
    history = [g for g in season['games'] if day(g['date']) < start]
    schedule = [{k: g[k] for k in ('id', 'date', 'home', 'away', 'neutral')}
                for g in season['games'] if 0 <= (day(g['date']) - start).days < 7]
    if not schedule:
        raise ValueError('Historical replay has no games for this week. Use 2015-04-06.')
    return validate_dataset({'history': history, 'schedule': schedule,
                             'week_start': week, 'mode': 'historical replay', 'source': season['source']})


def csv_games(content, completed):
    rows = list(csv.DictReader(io.StringIO(content)))
    for row in rows:
        raw = (row.get('neutral') or '').strip().lower()
        if raw not in ('', 'true', 'false'):
            raise ValueError('CSV neutral must be true, false, or empty.')
        row['neutral'] = raw == 'true'
    return games(rows, completed)


def parse_odds(content, schedule, as_of):
    """Latest available snapshot for each game; positive spread means home underdog."""
    if not content.strip():
        return {}
    ids = {g['id'] for g in schedule}
    selected = {}
    reader = csv.DictReader(io.StringIO(content))
    columns = set(reader.fieldnames or [])
    if not {'game_id', 'observed_at'} <= columns:
        raise ValueError('Odds CSV needs game_id and observed_at columns.')
    if not columns & {'home_spread', 'total', 'home_moneyline', 'away_moneyline'}:
        raise ValueError('Odds CSV needs a spread, total, or moneyline column.')
    for row in reader:
        gid = row.get('game_id', '')
        if gid not in ids:
            raise ValueError(f'Odds game_id {gid!r} is not in this week’s schedule.')
        try:
            stamp = datetime.fromisoformat((row.get('observed_at') or '').replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('Each odds row needs observed_at as an ISO timestamp with timezone.') from None
        if stamp.tzinfo is None:
            raise ValueError('observed_at must include a timezone.')
        if stamp > as_of:
            raise ValueError('Odds timestamps cannot be later than the forecast as-of time.')
        item = {'observed_at': stamp.isoformat()}
        for key, low, high in [('home_spread', -60, 60), ('total', 100, 400),
                               ('home_moneyline', -100000, 100000), ('away_moneyline', -100000, 100000)]:
            if (row.get(key) or '').strip():
                item[key] = number(row[key], key, low, high)
                if 'moneyline' in key and abs(item[key]) < 100:
                    raise ValueError('American moneylines must be <= -100 or >= +100.')
        if ('home_moneyline' in item) != ('away_moneyline' in item):
            raise ValueError('Provide both moneylines to compute a no-vig probability.')
        if len(item) == 1:
            raise ValueError('Each odds row must include a market value.')
        selected.setdefault(gid, []).append((stamp, item))
    if not selected:
        raise ValueError('Odds CSV has no data rows.')
    out = {}
    for gid, observations in selected.items():
        observations.sort(key=lambda x: x[0])
        if len({x[0] for x in observations}) != len(observations):
            raise ValueError('Use unique observed_at timestamps per game.')
        latest = observations[-1][1]
        latest['snapshots'] = len(observations)
        first = observations[0][1]
        for key in ('home_spread', 'total'):
            if key in latest and key in first and len(observations) > 1:
                latest[key + '_movement'] = round(latest[key] - first[key], 2)
        out[gid] = latest
    return out
