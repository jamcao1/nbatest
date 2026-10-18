"""Build a static dashboard for GitHub Pages from a completed simulation report."""
import argparse
import json
from pathlib import Path

from .data import ROOT
from .model import backtest
from .reporting import markdown


def build_site(report_path, output):
    report = json.loads(Path(report_path).read_text())
    if report.get('mode') != 'live public data' or report.get('simulations_per_game') != 1000:
        raise ValueError('The public site requires a live-data report with 1,000 simulations per game.')
    if not isinstance(report.get('games'), list):
        raise ValueError('The report must contain a games list.')
    if any(g.get('simulations') != 1000 or g.get('home_wins', 0)+g.get('away_wins', 0) != 1000
           for g in report['games']):
        raise ValueError('Every published game must contain 1,000 decisive outcomes.')
    # Prepare everything before modifying the output directory. Only known output
    # files are written; do not recursively delete a user-specified directory.
    analysis = markdown(report)
    historical = backtest(json.loads((ROOT/'data/season_2015.json').read_text())['games'])
    static = ROOT/'nbasim/static'
    html = (static/'index.html').read_text()
    html = html.replace('<body>', '<body data-mode="published">')
    html = html.replace('<section class="toolbar"', '<section hidden class="toolbar"')
    html = html.replace('<div class="data-actions"', '<div hidden class="data-actions"')
    html = html.replace('Loading historical replay…', 'Loading the published weekly forecast…')
    publication = '''<section class="publication" aria-label="Published report information">
      <div><span class="eyebrow">THE LATEST WEEKLY REPORT</span><p id="published-at">Loading publication time…</p></div>
      <div class="publication-links"><a href="./weekly.md" download>Download analysis ↓</a><a href="https://github.com/jamcao1/nbatest/actions/workflows/weekly.yml">Report updates ↗</a></div>
    </section>'''
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
    for name, content in artifacts.items():
        (output/name).write_text(content)
    return output


def main():
    parser = argparse.ArgumentParser(description='Build the published weekly NBA dashboard')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'site')
    args = parser.parse_args()
    try:
        output = build_site(args.report, args.output)
        print(f'Built static website: {output}')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
