import copy
import gzip
import json
import unittest

from nbasim.data import ROOT
from nbasim.pace_data import game_stats, priors


class PaceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = json.loads(gzip.decompress((ROOT/'data/pace_history_2026.json.gz').read_bytes()))

    def test_pace_matches_possession_formula_and_overtime_normalization(self):
        raw = next(g for g in self.archive['games'] if len(g['header']['competitions'][0]['competitors'][0]['linescores']) > 4)
        row = game_stats(raw)
        possessions = sum(t['fga']+.44*t['fta']-t['orb']+t['to'] for t in row['teams'].values())/2
        self.assertAlmostEqual(row['pace'],possessions*48/row['duration'])
        self.assertGreater(row['duration'],48)

    def test_incomplete_quarter_scores_rejected(self):
        raw=copy.deepcopy(self.archive['games'][0])
        raw['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue']='999'
        raw['header']['competitions'][0]['competitors'][0]['linescores'][0].pop('value',None)
        with self.assertRaisesRegex(ValueError,'reconcile'):
            game_stats(raw)

    def test_pace_rank_is_distinct_from_scoring_and_not_universal(self):
        p=priors(self.archive)
        self.assertEqual(len(p['teams']),30)
        self.assertEqual(p['teams']['MIA']['pace_rank'],3)
        self.assertEqual(p['teams']['DEN']['pace_rank'],13)
        self.assertEqual(p['teams']['DEN']['offense_rank'],1)
        self.assertLess(p['teams']['MIA']['above_league_pace_fraction'],1)
        self.assertLess(p['teams']['DEN']['above_league_pace_fraction'],1)


if __name__=='__main__':
    unittest.main()
