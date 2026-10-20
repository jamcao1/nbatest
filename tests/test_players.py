import copy
import gzip
import json
import unittest
from pathlib import Path

from nbasim.players import context, fit_history, parse_game, project_player, rotation, zone_for

ARCHIVE = json.loads(gzip.decompress((Path(__file__).parents[1]/'data/player_shots_2026.json.gz').read_bytes()))


class PlayerResearchTests(unittest.TestCase):
    def test_mismatched_play_log_withholds_locations_but_preserves_box_scoring(self):
        g = ARCHIVE['games'][0]
        chosen = next(p for p in g['players'].values() if p['fga'] and len(p['shots']) == p['fga'])
        raw = {'header': {'id': g['id'], 'competitions': [{'date': g['start'],
               'status': {'type': {'completed': True}},
               'competitors': [{'linescores': [{}]*int(4+(g['duration']-48)/5)} for _ in range(2)]}]},
               'boxscore': {'players': [], 'teams': []}, 'plays': []}
        for code in (g['home'], g['away']):
            ps = [p for p in g['players'].values() if p['team'] == code]
            athletes = [{'athlete': {'id': p['id'], 'displayName': p['name']},
                         'stats': [str(p['minutes']), str(p['points']), f"{p['fgm']}-{p['fga']}",
                                   f"{p['threem']}-{p['threea']}", f"{p['ftm']}-{p['fta']}"]} for p in ps]
            raw['boxscore']['players'].append({'team': {'abbreviation': code},
                'statistics': [{'labels': ['MIN', 'PTS', 'FG', '3PT', 'FT'], 'athletes': athletes}]})
            values = {'fieldGoalsMade-fieldGoalsAttempted': f"{sum(p['fgm'] for p in ps)}-{sum(p['fga'] for p in ps)}",
                      'freeThrowsMade-freeThrowsAttempted': f"{sum(p['ftm'] for p in ps)}-{sum(p['fta'] for p in ps)}",
                      'offensiveRebounds': '5', 'totalTurnovers': '10'}
            raw['boxscore']['teams'].append({'statistics': [{'name': k, 'displayValue': v} for k, v in values.items()]})
        raw['plays'] = [{'id': str(i), 'shootingPlay': True, 'pointsAttempted': worth,
                         'scoringPlay': bool(made), 'coordinate': {'x': x, 'y': y},
                         'participants': [{'athlete': {'id': chosen['id']}}]}
                        for i, (x, y, made, worth) in enumerate(chosen['shots'])]
        parsed = parse_game(raw, g)['players'][chosen['id']]
        self.assertTrue(parsed['locations_reconciled'])
        self.assertEqual(len(parsed['shots']), chosen['fga'])
        raw['plays'].pop()
        parsed = parse_game(raw, g)['players'][chosen['id']]
        self.assertFalse(parsed['locations_reconciled'])
        self.assertEqual(parsed['shots'], [])
        self.assertEqual(parsed['points'], chosen['points'])
        self.assertEqual(parsed['zones']['unknown3'][1], chosen['threea'])

    def test_coordinates_and_unknowns_are_not_fabricated(self):
        def shot(x, y, worth=2, text=''):
            return {'coordinate': {'x': x, 'y': y}, 'pointsAttempted': worth, 'text': text, 'scoringPlay': True}
        self.assertEqual(zone_for(shot(25, 1))[0], 'rim')
        self.assertEqual(zone_for(shot(25, 10))[0], 'paint')
        self.assertEqual(zone_for(shot(38, 14))[0], 'mid')
        self.assertEqual(zone_for(shot(2, 4, 3))[0], 'corner3')
        self.assertEqual(zone_for(shot(25, 26, 3))[0], 'arc3')
        self.assertEqual(zone_for(shot(25, 1, 3, 'makes 26-foot jumper')), ('unknown3', None))
        self.assertEqual(zone_for(shot(float('nan'), 1)), ('unknown2', None))
        self.assertEqual(zone_for({'pointsAttempted': 2}), ('unknown2', None))

    def test_archive_baskets_locations_and_points_reconcile(self):
        for g in ARCHIVE['games']:
            for p in g['players'].values():
                self.assertEqual(sum(v[0]*({'ft': 1, 'corner3': 3, 'arc3': 3, 'unknown3': 3}.get(z, 2))
                                     for z, v in p['zones'].items()), p['points'])
                self.assertEqual(sum(v[1] for z, v in p['zones'].items() if z != 'ft'), p['fga'])
                self.assertEqual(sum(v[0] for z, v in p['zones'].items() if z != 'ft'), p['fgm'])
                if not p['locations_reconciled']:
                    self.assertEqual(p['shots'], [])
                self.assertLessEqual(len(p['shots']), p['fga'])

    def test_future_games_cannot_change_prior_or_player_projection(self):
        cutoff = '2026-04-01'
        model = fit_history(ARCHIVE['games'], cutoff)
        pid = max(model['histories'], key=lambda x: len(model['histories'][x]))
        g, p = model['histories'][pid][-1]
        candidate = {'id': pid, 'name': p['name'], 'minutes': 32, 'injuries': [], 'excluded': False}
        original = project_player(candidate, p['team'], g['away'], True, g['venue']['id'], model)
        changed = copy.deepcopy(ARCHIVE['games'])
        for game in changed:
            if game['date'] >= cutoff:
                game['pace'] = 9999; game['players'] = {}
        altered = project_player(candidate, p['team'], g['away'], True, g['venue']['id'], fit_history(changed, cutoff))
        self.assertEqual(original, altered)
        self.assertTrue(all(g['date'] < cutoff for g in model['rows']))

    def test_out_players_have_zero_minutes_and_unknown_players_are_unrated(self):
        model = fit_history(ARCHIVE['games'], '2026-10-20')
        game = ARCHIVE['games'][-1]
        roster = [{'id': p['id'], 'name': p['name'], 'injuries': []} for p in game['players'].values()]
        roster[0]['injuries'] = [{'status': 'Out'}]
        roster.append({'id': 'rookie', 'name': 'No NBA history', 'injuries': []})
        minutes = rotation(roster, model)
        self.assertEqual(minutes[0]['minutes'], 0)
        self.assertAlmostEqual(sum(p['minutes'] for p in minutes), 240)
        self.assertTrue(all(0 <= p['minutes'] <= 48 for p in minutes))
        new = project_player(minutes[-1], game['home'], game['away'], True, '', model)
        self.assertEqual(new['status'], 'insufficient_history')
        self.assertIsNone(new['expected_points'])

    def test_expected_baskets_and_points_sum_with_new_team_identity(self):
        model = fit_history(ARCHIVE['games'], '2026-10-20')
        pid = max(model['histories'], key=lambda x: len(model['histories'][x]))
        g, p = model['histories'][pid][-1]
        player = {'id': pid, 'name': p['name'], 'minutes': 35, 'excluded': False, 'injuries': []}
        result = project_player(player, 'BOS', 'DET', None, 'unknown-venue', model)
        self.assertEqual(result['id'], pid)
        self.assertEqual(result['team'], 'BOS')
        self.assertEqual(result['venue_games'], 0)
        self.assertAlmostEqual(result['venue_factor'], 1)
        self.assertAlmostEqual(result['expected_points'], sum(z['worth']*z['made'] for z in result['zones']))
        for z in result['zones']:
            self.assertAlmostEqual(z['made']+z['misses'], z['attempts'])
        self.assertGreater(len(result['shots']), 0)

    def test_market_movement_needs_real_quotes_and_matching_game(self):
        raw = {'header': {'id': '12', 'competitions': [{'date': '2026-10-20T19:00Z',
               'competitors': [{'homeAway': 'home', 'team': {'abbreviation': 'BOS'}},
                               {'homeAway': 'away', 'team': {'abbreviation': 'DET'}}],
               'status': {'type': {'state': 'pre'}}}]},
               'pickcenter': [{'provider': {'name': 'Test provider'}, 'total': {'over': {
                   'open': {'line': 'o220.5'}, 'close': {'line': 'o218.5'}}}}]}
        game = {'id': '12', 'date': '2026-10-20', 'home': 'BOS', 'away': 'DET'}
        parsed = context(raw, game)
        self.assertEqual(parsed['markets'][0]['total_open'], 220.5)
        self.assertEqual(parsed['markets'][0]['total_latest'], 218.5)
        self.assertIsNone(parsed['markets'][0]['home_spread_open'])
        self.assertEqual(parsed['venue']['name'], 'Venue unavailable')
        with self.assertRaises(ValueError):
            context(raw, {**game, 'home': 'NY'})


if __name__ == '__main__':
    unittest.main()
