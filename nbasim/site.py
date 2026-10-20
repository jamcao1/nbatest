"""Build a static dashboard for GitHub Pages from a completed simulation report."""
import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from .data import ROOT
from .model import backtest
from .reporting import markdown


def build_site(report_path, output, roster_path=None, pace_path=None):
    report = json.loads(Path(report_path).read_text())
    if report.get('mode') != 'live public data' or report.get('simulations_per_game') != 1000:
        raise ValueError('The public site requires a live-data report with 1,000 simulations per game.')
    if not isinstance(report.get('games'), list):
        raise ValueError('The report must contain a games list.')
    if any(g.get('simulations') != 1000 or g.get('home_wins', 0)+g.get('away_wins', 0) != 1000
           for g in report['games']):
        raise ValueError('Every published game must contain 1,000 decisive outcomes.')
    roster = json.loads(Path(roster_path).read_text()) if roster_path else None
    if roster is not None:
        if roster.get('week_start') != report['week_start'] or roster.get('status') not in ('experimental_not_applied', 'unavailable'):
            raise ValueError('Roster context must match this forecast and disclose its experimental/unavailable status.')
        stamp = datetime.fromisoformat(roster['generated_at'])
        generated = datetime.fromisoformat(report['generated_at'])
        if stamp.tzinfo is None or generated.tzinfo is None or abs((stamp - generated).total_seconds()) > 86400:
            raise ValueError('Roster context must be generated within a day of this forecast.')
        if roster['status'] != 'unavailable':
            if len(roster.get('teams', {})) != 30:
                raise ValueError('Roster context requires all 30 teams.')
            for team in roster['teams'].values():
                minutes = [p['minutes'] for p in team['players']]
                if any(not math.isfinite(m) or not 0 <= m <= 48 for m in minutes) or abs(sum(minutes) - 240) > .001:
                    raise ValueError('Estimated rotations must contain 240 feasible player-minutes.')
    # Prepare everything before modifying the output directory. Only known output
    # files are written; do not recursively delete a user-specified directory.
    analysis = markdown(report)
    historical = backtest(json.loads((ROOT/'data/season_2015.json').read_text())['games'])
    static = ROOT/'nbasim/static'
    html = (static/'index.html').read_text()
    html = html.replace('<body>', '<body data-mode="published">')
    if roster is not None:
        html = html.replace('data-mode="published"', 'data-mode="published" data-rosters="true"')
    html = html.replace('<section class="toolbar"', '<section hidden class="toolbar"')
    html = html.replace('<div class="data-actions"', '<div hidden class="data-actions"')
    html = html.replace('Loading historical replay…', 'Loading the published weekly forecast…')
    publication = '''<section class="publication" aria-label="Published report information">
      <div><span class="eyebrow">THE LATEST WEEKLY REPORT</span><p id="published-at">Loading publication time…</p></div>
      <div class="publication-links"><a href="./weekly.md" download>Download analysis ↓</a><a href="https://github.com/jamcao1/nbatest/actions/workflows/weekly.yml">Report updates ↗</a></div>
    </section>'''
    if roster is not None:
        publication = publication.replace('<div class="publication-links">',
                                          '<div class="publication-links"><a href="#roster-context">Roster changes ↓</a>')
    html = html.replace('<section hidden class="toolbar"', publication+'\n    <section hidden class="toolbar"')
    output = Path(output)
    if output.resolve() == static.resolve():
        raise ValueError('Build output cannot overwrite the application static source directory.')
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {'index.html': html, 'app.js': (static/'app.js').read_text(),
                 'style.css': (static/'style.css').read_text(),
                 'weekly.json': json.dumps(report, indent=2, allow_nan=False)+'\n',
                 'weekly.md': analysis, 'backtest.json': json.dumps(historical, indent=2, allow_nan=False)+'\n',
                 '.nojekyll': ''}
    if roster is not None:
        artifacts['rosters.json'] = json.dumps(roster, indent=2, allow_nan=False) + '\n'
    for name in ('live.html','live.js','live-model.mjs'):
        artifacts[name] = (static/name).read_text()
    # Browsers can cache Pages assets across deployments. Link each live bundle
    # to its exact contents so refreshed HTML cannot run the previous module.
    version = lambda content: hashlib.sha256(content.encode()).hexdigest()[:16]
    artifacts['live.js'] = artifacts['live.js'].replace(
        "'./live-model.mjs'", f"'./live-model.mjs?v={version(artifacts['live-model.mjs'])}'")
    artifacts['live.html'] = artifacts['live.html'].replace(
        'src="./live.js"', f'src="./live.js?v={version(artifacts["live.js"])}"')
    artifacts['pace-priors.json'] = Path(pace_path or ROOT/'data/pace_priors.json').read_text()
    artifacts['pace-replay.json'] = (ROOT/'data/pace_replay.json').read_text()
    artifacts['pace-evaluation.json'] = (ROOT/'data/pace_evaluation.json').read_text()
    for name, content in artifacts.items():
        (output/name).write_text(content)
    return output


def main():
    parser = argparse.ArgumentParser(description='Build the published weekly NBA dashboard')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'site')
    parser.add_argument('--rosters', type=Path, help='Optional dated experimental roster context')
    parser.add_argument('--pace', type=Path, help='Pace priors refreshed from completed games')
    args = parser.parse_args()
    try:
        output = build_site(args.report, args.output, args.rosters, args.pace)
        print(f'Built static website: {output}')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
