import copy
import json
import math
import unittest
from datetime import datetime, timezone

from nbasim.data import ROOT, csv_games, demo_dataset, parse_odds, validate_dataset
from nbasim.model import SIMULATIONS, backtest, fit, implied, report, simulate
from nbasim.provider import parse_events


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = demo_dataset()
        cls.model = fit(cls.dataset['history'], cls.dataset['week_start'])
        cls.game = cls.dataset['schedule'][0]

    def test_exactly_1000_decisive_outcomes(self):
        r = simulate(self.game, self.model, self.dataset['schedule'])
        self.assertEqual(r['home_wins'] + r['away_wins'], SIMULATIONS)
        self.assertEqual(sum(b['count'] for b in r['margin_distribution']), 1000)
        self.assertEqual(r['home_win_probability'], r['home_wins'] / 1000)
        self.assertLessEqual(r['margin_80_interval'][0], r['margin_80_interval'][1])
        lo, hi = r['home_probability_mc_95_interval']
        self.assertLessEqual(lo, r['home_win_probability'])
        self.assertGreaterEqual(hi, r['home_win_probability'])

    def test_seed_reproducibility_and_independence_from_order(self):
        a = simulate(self.game, self.model, self.dataset['schedule'], 10)
        b = simulate(self.game, self.model, list(reversed(self.dataset['schedule'])), 10)
        c = simulate(self.game, self.model, self.dataset['schedule'], 11)
        self.assertEqual(a, b)
        self.assertNotEqual(a['margin_distribution'], c['margin_distribution'])

    def test_future_outcomes_cannot_change_training(self):
        future = {**self.game, 'home_score': 299, 'away_score': 1}
        altered = copy.deepcopy(self.dataset)
        altered['history'].append(future)
        self.assertEqual(fit(altered['history'], altered['week_start']), self.model)
        first = report(self.dataset)
        second = report(altered)
        self.assertEqual(first['games'], second['games'])

    def test_neutral_equal_teams_have_symmetric_probability(self):
        neutral = {**self.game, 'neutral': True}
        m = copy.deepcopy(self.model)
        m['attack'] = dict.fromkeys(m['attack'], 0)
        m['concede'] = dict.fromkeys(m['concede'], 0)
        for p in m['profiles'].values():
            p['last_played'] = '2015-04-01'
        r = simulate(neutral, m, [])
        self.assertAlmostEqual(r['home_win_probability'], 0.5, delta=.06)
        home = simulate({**neutral, 'neutral': False}, m, [])
        self.assertGreater(home['home_win_probability'], r['home_win_probability'])

    def test_better_offense_increases_win_probability(self):
        before = simulate(self.game, self.model, [])
        m = copy.deepcopy(self.model)
        m['attack'][self.game['home']] += 15
        after = simulate(self.game, m, [])
        self.assertGreater(after['home_win_probability'], before['home_win_probability'] + .2)

    def test_back_to_back_direction(self):
        m = copy.deepcopy(self.model)
        m['profiles'][self.game['home']]['last_played'] = '2015-04-05'
        m['profiles'][self.game['away']]['last_played'] = '2015-04-03'
        r = simulate(self.game, m, [])
        self.assertEqual(r['factors']['rest_margin_points'], -1.25)

    def test_unknown_team_is_explicit(self):
        r = simulate({**self.game, 'home': 'NEW'}, self.model, [])
        self.assertIn('no training games', ' '.join(r['warnings']))
        self.assertIsNone(r['factors']['home'])

    def test_stale_training_warning_survives_projected_games(self):
        future = {**self.game, 'date': '2015-10-21'}
        previous = {**self.game, 'id': 'previous-scheduled-game', 'date': '2015-10-20'}
        r = simulate(future, self.model, [previous, future])
        self.assertEqual(r['factors']['home_rest_days'], 0)
        self.assertTrue(any('training results are over 30 days old' in w for w in r['warnings']))

    def test_market_sign_pushes_and_no_vig(self):
        odds = {'home_spread': -5, 'total': 200, 'home_moneyline': -110, 'away_moneyline': -110}
        r = simulate(self.game, self.model, [], odds=odds)
        m = r['market']
        self.assertLessEqual(m['home_cover_probability'], r['home_win_probability'])
        self.assertAlmostEqual(m['home_cover_probability'] + m['away_cover_probability'] + m['spread_push_probability'], 1)
        self.assertAlmostEqual(m['over_probability'] + m['under_probability'] + m['total_push_probability'], 1)
        self.assertEqual(m['home_no_vig_probability'], .5)
        plain = simulate(self.game, self.model, [])
        self.assertEqual(plain['home_win_probability'], r['home_win_probability'])
        self.assertAlmostEqual(implied(-200), 2/3)
        self.assertAlmostEqual(implied(200), 1/3)

    def test_holdout_count_and_metrics(self):
        season = json.loads((ROOT / 'data/season_2015.json').read_text())['games']
        r = backtest(season)
        self.assertEqual(r['games'], 319)
        self.assertEqual(sum(x['test_games'] for x in r['folds']), 319)
        self.assertEqual(sum(x['games'] for x in r['calibration']), 319)
        for k in ('brier_score', 'winner_accuracy', 'margin_80_coverage'):
            self.assertTrue(0 <= r[k] <= 1)
        self.assertEqual(len(season), 1230)

    def test_seed_validation(self):
        for seed in (True, -1, 1.5, '42', 2**32):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                report(self.dataset, seed)


class InputTests(unittest.TestCase):
    def test_duplicate_games_rejected(self):
        d = demo_dataset()
        d['schedule'].append(d['schedule'][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_dataset(d)

    def test_scores_outside_horizon_not_exposed(self):
        d = demo_dataset()
        self.assertTrue(all('home_score' not in g for g in d['schedule']))
        d['schedule'][0]['date'] = '2015-04-20'
        with self.assertRaisesRegex(ValueError, 'seven days'):
            validate_dataset(d)

    def test_nonfinite_and_invalid_scores_rejected(self):
        for value in (float('nan'),float('inf'),-1,400,True,2.2):
            d = demo_dataset()
            d['history'][0]['home_score'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_dataset(d)

    def test_csv_import(self):
        rows = csv_games('id,date,home,away,home_score,away_score,neutral\nx,2026-01-01,A,B,101,100,true\n', True)
        self.assertEqual(rows[0]['home_score'], 101)
        self.assertTrue(rows[0]['neutral'])

    def test_odds_snapshot_order_and_asof(self):
        schedule = [{'id':'x'}]
        cutoff = datetime(2026,1,2,tzinfo=timezone.utc)
        header = 'game_id,observed_at,home_spread,total,home_moneyline,away_moneyline\n'
        rows = 'x,2026-01-01T20:00:00Z,-4.5,220,-150,130\nx,2026-01-01T10:00:00Z,-3.5,219,-140,120\n'
        result = parse_odds(header+rows, schedule, cutoff)['x']
        self.assertEqual(result['home_spread'], -4.5)
        self.assertEqual(result['home_spread_movement'], -1)
        self.assertEqual(result['snapshots'], 2)
        with self.assertRaisesRegex(ValueError, 'later'):
            parse_odds(header+'x,2026-01-03T00:00:00Z,-4,220,-150,130',schedule,cutoff)
        with self.assertRaisesRegex(ValueError, 'both'):
            parse_odds(header+'x,2026-01-01T00:00:00Z,-4,220,-150,',schedule,cutoff)

    def test_invalid_odds_csv_rejected(self):
        for content in ('bad,header\n1,2\n', 'game_id,observed_at,total\n',
                        'game_id,observed_at,total\nx,2026-01-01T00:00:00Z,\n'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_odds(content, [{'id':'x'}], datetime(2026,1,2,tzinfo=timezone.utc))


class ProviderTests(unittest.TestCase):
    def event(self, status='STATUS_SCHEDULED', completed=False, season=2):
        return {'id':'1','date':'2026-01-02T01:00:00Z','season':{'type':season},
                'competitions':[{'competitors':[{'homeAway':'home','team':{'abbreviation':'BOS'},'score':'110'},
                                                {'homeAway':'away','team':{'abbreviation':'NYK'},'score':'101'}],
                                 'status':{'type':{'name':status,'state':'post' if completed else 'pre','completed':completed}}}]}

    def test_timezone_completed_and_scheduled(self):
        h,s = parse_events({'events':[self.event()]})
        self.assertEqual(len(s),1)
        self.assertEqual(s[0]['date'],'2026-01-01')
        h,s = parse_events({'events':[self.event('STATUS_FINAL',True)]})
        self.assertEqual(h[0]['home_score'],110)
        self.assertEqual(s,[])

    def test_preseason_and_postponed_excluded(self):
        self.assertEqual(parse_events({'events':[self.event(season=1)]}),([],[]))
        self.assertEqual(parse_events({'events':[self.event('STATUS_POSTPONED')]}),([],[]))

    def test_invalid_schema_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'schema'):
            parse_events({})
        event = self.event()
        event['competitions'][0]['competitors'] = []
        with self.assertRaisesRegex(ValueError,'invalid game'):
            parse_events({'events':[event]})


if __name__ == '__main__':
    unittest.main()
