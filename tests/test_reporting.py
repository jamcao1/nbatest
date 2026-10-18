import unittest

from nbasim.data import demo_dataset
from nbasim.model import report
from nbasim.reporting import markdown


class ReportTests(unittest.TestCase):
    def test_readable_report_preserves_results_and_assumptions(self):
        result = report(demo_dataset())
        text = markdown(result)
        self.assertIn('49 matchups, 1,000 simulations per game', text)
        self.assertEqual(text.count('\n### '), 49)
        self.assertIn('No market lines supplied', text)
        first = result['games'][0]
        self.assertIn(f"{first['favorite_probability']:.1%}", text)
        self.assertIn('not exact-score predictions', text)


if __name__ == '__main__':
    unittest.main()
