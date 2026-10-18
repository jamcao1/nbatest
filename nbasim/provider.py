"""Public ESPN scoreboard adapter. An undocumented feed may change without notice."""
import concurrent.futures
import gzip
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .data import day, validate_dataset

ENDPOINT = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
EASTERN = ZoneInfo('America/New_York')


def parse_events(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError('NBA data feed returned an unexpected schema (missing events).')
    history, schedule = [], []
    for event in payload['events']:
        # Regular season and playoffs only: do not silently model preseason/All-Star games.
        if event.get('season', {}).get('type') not in (2, 3):
            continue
        competitions = event.get('competitions', [])
        if len(competitions) != 1:
            raise ValueError('Unexpected NBA competition format.')
        comp = competitions[0]
        try:
            sides = {x['homeAway']: x for x in comp['competitors']}
            h, a = sides['home'], sides['away']
            date_value = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
            if date_value.tzinfo is None:
                raise ValueError('Feed game timestamps need timezone information.')
            game = {'id': str(event['id']), 'date': date_value.astimezone(EASTERN).date().isoformat(),
                    'home': h['team']['abbreviation'], 'away': a['team']['abbreviation'],
                    'neutral': bool(comp.get('neutralSite', False))}
            status = comp.get('status', event.get('status', {})).get('type', {})
            if status.get('completed'):
                game.update(home_score=int(h['score']), away_score=int(a['score']))
                history.append(game)
            elif status.get('state') == 'pre' and status.get('name') == 'STATUS_SCHEDULED':
                schedule.append(game)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('NBA feed contains an invalid game; no report was produced.') from exc
    return history, schedule


def fetch_day(date):
    # This NBA endpoint rejects date ranges with HTTP 400; use one calendar day.
    dates = date.strftime('%Y%m%d')
    req = urllib.request.Request(f'{ENDPOINT}?dates={dates}&limit=1000', headers={'User-Agent': 'Courtside-NBA-Lab/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(10_000_001)
        if raw[:2] == b'\x1f\x8b':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                raw = compressed.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError('NBA data response exceeded the size limit.')
        payload = json.loads(raw)
        parse_events(payload)  # Check the response before using its season calendar.
        if len(payload['events']) >= 1000:
            raise ValueError('NBA feed may have truncated the daily result set.')
        return payload
    except urllib.error.HTTPError as exc:
        raise ValueError(f'NBA feed rejected the request for {date.isoformat()} (HTTP {exc.code}). '
                         'No live report was produced; historical replay and imported data remain available.') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError('Could not connect to site.api.espn.com. Check network/proxy access or import a dataset. '
                         'Historical replay remains available; it has not been substituted for live data.') from exc


def calendar_days(payload):
    """Use the provider's season calendar; absent calendars fall back to daily scans."""
    leagues = payload.get('leagues', [])
    if not leagues or leagues[0].get('calendarType') != 'day':
        return None
    calendar = leagues[0].get('calendar')
    if not isinstance(calendar, list) or not calendar:
        return None
    try:
        timestamps = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in calendar]
        if any(value.tzinfo is None for value in timestamps):
            return None
        return {value.astimezone(EASTERN).date() for value in timestamps}
    except (ValueError, TypeError, AttributeError):
        return None


def live_dataset(week):
    start = day(week)
    end = start + timedelta(days=6)
    first = start - timedelta(days=240)
    history, schedule = {}, {}
    def collect(payload):
        past, future = parse_events(payload)
        history.update({g['id']: g for g in past if first <= day(g['date']) < start})
        schedule.update({g['id']: g for g in future if start <= day(g['date']) <= end})

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        boundaries = list(pool.map(fetch_day, [first, end]))
        calendars = [calendar_days(payload) for payload in boundaries]
        # A 247-day window spans at most two NBA seasons. Read both calendars,
        # including the previous season when forecasts follow the offseason.
        if all(calendar is not None for calendar in calendars):
            dates = set.union(*calendars)
        else:
            dates = {first + timedelta(days=i) for i in range((end - first).days + 1)}
        for payload in boundaries:
            collect(payload)
        pending = sorted(d for d in dates if first < d < end)
        for payload in pool.map(fetch_day, pending):
            collect(payload)
    return validate_dataset({'history': list(history.values()), 'schedule': list(schedule.values()),
                             'week_start': week, 'mode': 'live public data',
                             'source': 'ESPN public scoreboard; regular season and playoffs. Retrieved ' + datetime.now(EASTERN).isoformat()})
