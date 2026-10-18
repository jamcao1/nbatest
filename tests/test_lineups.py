import copy
import gzip
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from nbasim.lineups import collect_boxes, evaluate, parse_boxscore, player_model, project_minutes, roster_delta


def game(index=0):
    row = {'id': str(index + 1), 'date': (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
           'home': 'A', 'away': 'B', 'home_score': 105, 'away_score': 100, 'neutral': False}
    row['players'] = {team: [{'id': f'{team}{i}', 'name': f'{team} Player {i}',
                              'minutes': 48, 'points': 21 if team == 'A' else 20}
                             for i in range(5)] for team in ('A', 'B')}
    return row


def payload(row):
    return {'header': {'id': row['id'], 'competitions': [{'date': row['date'] + 'T20:00Z',
            'status': {'type': {'completed': True}}}]}, 'boxscore': {'players': [
                {'team': {'abbreviation': team}, 'statistics': [{'labels': ['MIN', 'PTS'],
                 'athletes': [{'athlete': {'id': p['id'], 'displayName': p['name']},
                               'stats': [str(p['minutes']), str(p['points'])], 'didNotPlay': False}
                              for p in players]}]} for team, players in row['players'].items()]}}


class LineupTests(unittest.TestCase):
    def test_dated_archive_fallback_requires_matching_live_result(self):
        row = game()
        live_result = {k:v for k,v in row.items() if k != 'players'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'archive.json.gz'
            archive.write_bytes(gzip.compress(json.dumps({'retrieved_at': '2026-01-02T00:00:00Z', 'games': [row]}).encode()))
            with patch('nbasim.lineups.fetch_json', side_effect=OSError('feed unavailable')):
                boxes = collect_boxes([live_result], root/'cache', archive)
                self.assertEqual(boxes[0]['archive_fallback']['retrieved_at'], '2026-01-02T00:00:00Z')
                self.assertEqual(boxes[0]['players'], row['players'])
                with self.assertRaisesRegex(ValueError, '95%'):
                    collect_boxes([{**live_result, 'home_score': 106}], root/'cache', archive)

    def test_box_score_must_reconcile_with_completed_result(self):
        row = game()
        self.assertEqual(parse_boxscore(payload(row), row)['players'], row['players'])
        for change in ('points', 'minutes', 'identity', 'status'):
            data = payload(row)
            if change == 'points':
                data['boxscore']['players'][0]['statistics'][0]['athletes'][0]['stats'][1] = '99'
            elif change == 'minutes':
                data['boxscore']['players'][0]['statistics'][0]['athletes'][0]['stats'][0] = '0'
            elif change == 'identity':
                data['header']['id'] = 'wrong'
            else:
                data['header']['competitions'][0]['status']['type']['completed'] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_boxscore(data, row)

    def test_unknown_nonparticipant_disclosed_but_participant_rejected(self):
        row = game()
        data = payload(row)
        data['boxscore']['players'][0]['statistics'][0]['athletes'].append(
            {'athlete': {'shortName': 'Unidentified'}, 'didNotPlay': True, 'stats': []})
        parsed = parse_boxscore(data, row)
        self.assertEqual(parsed['unidentified_dnp'], [{'team': 'A', 'name': 'Unidentified'}])
        data['boxscore']['players'][0]['statistics'][0]['athletes'][-1].update(didNotPlay=False, stats=['4', '2'])
        with self.assertRaisesRegex(ValueError, 'stable identifier'):
            parse_boxscore(data, row)

    def test_minutes_are_feasible_and_unknown_players_disclosed(self):
        boxes = [game(i) for i in range(10)]
        roster = boxes[-1]['players']['A'] + [{'id': 'rookie', 'name': 'New Player'}]
        result = project_minutes(roster, boxes, '2026-01-11')
        self.assertAlmostEqual(sum(p['minutes'] for p in result), 240)
        self.assertTrue(all(0 <= p['minutes'] <= 48 for p in result))
        unknown = next(p for p in result if p['id'] == 'rookie')
        self.assertTrue(unknown['unknown_player_prior'])
        self.assertIsNone(unknown['points_per_game'])
        self.assertGreater(unknown['minutes'], 0)

    def test_future_games_do_not_change_minutes_or_player_ratings(self):
        boxes = [game(i) for i in range(12)]
        roster = boxes[0]['players']['A']
        cutoff = '2026-01-11'
        minutes = project_minutes(roster, boxes, cutoff)
        fitted = player_model(boxes, cutoff, 2.5)
        changed = copy.deepcopy(boxes)
        for row in changed[10:]:
            row['home_score'] = 250
            row['players']['A'][0]['minutes'] = 0
        self.assertEqual(minutes, project_minutes(roster, changed, cutoff))
        self.assertEqual(fitted, player_model(changed, cutoff, 2.5))

    def test_transferred_player_keeps_identity_and_strength(self):
        rotation = [{'id': 'incoming', 'minutes': 48}, {'id': 'unknown', 'minutes': 192}]
        model = {'coefficients': {'incoming': 4}, 'baseline_strength': {'A': 1, 'B': 3}}
        self.assertEqual(roster_delta(rotation, model, 'A'), 3)
        self.assertEqual(roster_delta(rotation, model, 'B'), 1)

    def test_backtest_does_not_use_held_out_players_or_minutes(self):
        boxes = [game(i) for i in range(38)]
        first = evaluate(boxes, start='2026-02-01', weeks=1)
        altered = copy.deepcopy(boxes)
        for row in altered[31:]:
            row['players'] = {'A': [{'id': 'future-star', 'minutes': 240, 'points': 105}],
                              'B': [{'id': 'future-player', 'minutes': 240, 'points': 100}]}
        self.assertEqual(first, evaluate(altered, start='2026-02-01', weeks=1))
        self.assertEqual(first['games'], 7)
        altered[-1]['home_score'] = 80
        self.assertNotEqual(first['baseline_brier'], evaluate(altered, start='2026-02-01', weeks=1)['baseline_brier'])


if __name__ == '__main__':
    unittest.main()
