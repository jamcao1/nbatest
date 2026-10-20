import json
import tempfile
import unittest
from pathlib import Path

from nbasim.data import demo_dataset
from nbasim.model import report
from nbasim.site import build_site


class StaticSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical = report(demo_dataset())

    def test_build_contains_only_publishable_assets_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Simulated live input for an offline build test, never published.
            fixture = {**self.historical, 'mode': 'live public data'}
            source = root/'input.json'
            source.write_text(json.dumps(fixture))
            site = root/'nbatest'
            build_site(source, site)
            self.assertEqual({p.name for p in site.iterdir()},
                             {'index.html','app.js','style.css','weekly.json','weekly.md','backtest.json','.nojekyll',
                              'live.html','live.js','live-model.mjs','pace-priors.json','pace-replay.json','pace-evaluation.json'})
            html = (site/'index.html').read_text()
            self.assertIn('data-mode="published"', html)
            self.assertIn('href="./style.css"', html)
            self.assertIn('src="./app.js"', html)
            self.assertIn('<section hidden class="toolbar"', html)
            self.assertNotIn('Loading historical replay', html)
            self.assertEqual(json.loads((site/'weekly.json').read_text())['games'], fixture['games'])
            self.assertEqual(json.loads((site/'backtest.json').read_text())['games'],319)

    def test_historical_or_incomplete_report_cannot_replace_existing_site(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'input.json'
            site = root/'site'
            site.mkdir()
            (site/'index.html').write_text('previous working site')
            for fixture in (self.historical, {**self.historical, 'mode':'live public data',
                                             'games':[{**self.historical['games'][0], 'home_wins':0,'away_wins':0}]}):
                source.write_text(json.dumps(fixture))
                with self.assertRaises(ValueError):
                    build_site(source, site)
                self.assertEqual((site/'index.html').read_text(),'previous working site')

    def test_mismatched_or_infeasible_roster_cannot_replace_existing_site(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, roster_path, site = root/'report.json', root/'roster.json', root/'site'
            fixture = {**self.historical, 'mode': 'live public data'}
            source.write_text(json.dumps(fixture))
            site.mkdir()
            (site/'index.html').write_text('previous working site')
            roster = {'week_start': fixture['week_start'], 'generated_at': fixture['generated_at'],
                      'status': 'experimental_not_applied',
                      'teams': {str(i): {'players': [{'minutes':48} for _ in range(5)]} for i in range(30)}}
            invalid = [{**roster, 'week_start': '1900-01-01'},
                       {**roster, 'generated_at': '2015-01-01T00:00:00+00:00'},
                       {**roster, 'teams': {str(i): {'players': [{'minutes':49} for _ in range(5)]} for i in range(30)}}]
            for value in invalid:
                roster_path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    build_site(source, site, roster_path)
                self.assertEqual((site/'index.html').read_text(), 'previous working site')
            roster_path.write_text(json.dumps({**roster, 'status': 'unavailable', 'teams': {}}))
            build_site(source, site, roster_path)
            self.assertIn('data-rosters="true"', (site/'index.html').read_text())
            self.assertEqual(json.loads((site/'rosters.json').read_text())['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
