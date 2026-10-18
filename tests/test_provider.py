import gzip
import io
import json
import unittest
import urllib.error
from datetime import date, timedelta
from unittest.mock import patch

from nbasim.provider import calendar_days, fetch_day, live_dataset


class LiveProviderTests(unittest.TestCase):
    def test_single_day_request_and_gzip_response(self):
        body = gzip.compress(json.dumps({'events': []}).encode())
        with patch('nbasim.provider.urllib.request.urlopen', return_value=io.BytesIO(body)) as request:
            self.assertEqual(fetch_day(date(2026, 10, 20)), {'events': []})
        self.assertEqual(request.call_args.args[0].full_url,
                         'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261020&limit=1000')

    def test_feed_rejection_is_not_reported_as_missing_network_permission(self):
        error = urllib.error.HTTPError('https://site.api.espn.com', 400, 'Bad Request', {}, None)
        with patch('nbasim.provider.urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(ValueError, 'HTTP 400') as raised:
                fetch_day(date(2026, 10, 20))
        self.assertNotIn('Allow', str(raised.exception))

    def test_connection_failure_is_distinct_from_feed_rejection(self):
        with patch('nbasim.provider.urllib.request.urlopen', side_effect=urllib.error.URLError('connection failed')):
            with self.assertRaisesRegex(ValueError, 'Could not connect'):
                fetch_day(date(2026, 10, 20))

    def test_calendar_uses_eastern_dates_and_validates_metadata(self):
        good = {'leagues': [{'calendarType': 'day', 'calendar': ['2026-10-21T01:00Z']} ]}
        self.assertEqual(calendar_days(good), {date(2026, 10, 20)})
        for invalid in ({}, {'leagues':[{'calendarType':'day','calendar':['invalid']}]},
                        {'leagues':[{'calendarType':'day','calendar':['2026-10-21']}] } ):
            self.assertIsNone(calendar_days(invalid))

    def test_previous_and_current_season_calendars_both_used(self):
        start = date(2026, 10, 18)
        first, end = start - timedelta(days=240), start + timedelta(days=6)
        prior_game, future_game = first + timedelta(days=1), start + timedelta(days=2)
        def fixture(d):
            days = [first, prior_game] if d == first else [future_game, end]
            return {'events': [], 'leagues': [{'calendarType':'day', 'calendar':[f'{x}T12:00Z' for x in days]}]}
        with patch('nbasim.provider.fetch_day', side_effect=fixture) as fetched, \
             patch('nbasim.provider.validate_dataset', side_effect=lambda x: x):
            live_dataset(start.isoformat())
        self.assertEqual({c.args[0] for c in fetched.call_args_list}, {first, end, prior_game, future_game})
        self.assertEqual(fetched.call_count, 4)

    def test_missing_calendars_fall_back_without_skipping_days(self):
        start = date(2026, 10, 18)
        with patch('nbasim.provider.fetch_day', return_value={'events': []}) as fetched, \
             patch('nbasim.provider.validate_dataset', side_effect=lambda x: x):
            live_dataset(start.isoformat())
        dates = {c.args[0] for c in fetched.call_args_list}
        self.assertEqual(len(dates), 247)
        self.assertEqual(min(dates), start-timedelta(days=240))
        self.assertEqual(max(dates), start+timedelta(days=6))


if __name__ == '__main__':
    unittest.main()
