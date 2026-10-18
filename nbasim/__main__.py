"""CLI for reproducible weekly reports and chronological backtests."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import ROOT, csv_games, demo_dataset, validate_dataset
from .model import backtest, report
from .provider import live_dataset
from .reporting import markdown


def main():
    parser = argparse.ArgumentParser(description='NBA Monte Carlo lab: 1,000 simulations per game')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('simulate')
    choice = run.add_mutually_exclusive_group()
    choice.add_argument('--live', action='store_true')
    choice.add_argument('--input', type=Path)
    run.add_argument('--week', help='Seven-day forecast start, YYYY-MM-DD; live defaults to today in New York')
    run.add_argument('--seed', type=int, default=42)
    run.add_argument('--odds', type=Path)
    run.add_argument('--output', type=Path)
    run.add_argument('--markdown', type=Path, help='Also save a readable weekly analysis report')
    test = sub.add_parser('backtest')
    test.add_argument('--start', default='2015-03-02')
    test.add_argument('--weeks', type=int, default=6)
    test.add_argument('--output', type=Path)
    convert = sub.add_parser('import-csv')
    convert.add_argument('--history', required=True, type=Path)
    convert.add_argument('--schedule', required=True, type=Path)
    convert.add_argument('--week', required=True)
    convert.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'simulate':
            if args.live:
                dataset = live_dataset(args.week or datetime.now(ZoneInfo('America/New_York')).date().isoformat())
            elif args.input:
                dataset = json.loads(args.input.read_text())
                if args.week:
                    dataset['week_start'] = args.week
            else:
                dataset = demo_dataset(args.week or '2015-04-06')
            result = report(dataset, args.seed, args.odds.read_text() if args.odds else '')
            if args.markdown:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.markdown.with_suffix(args.markdown.suffix + '.tmp')
                temporary.write_text(markdown(result))
                temporary.replace(args.markdown)
        elif args.command == 'backtest':
            if not 1 <= args.weeks <= 52:
                raise ValueError('Backtest weeks must be between 1 and 52.')
            result = backtest(json.loads((ROOT / 'data/season_2015.json').read_text())['games'], args.start, args.weeks)
        else:
            result = validate_dataset({'history': csv_games(args.history.read_text(), True),
                                       'schedule': csv_games(args.schedule.read_text(), False),
                                       'week_start': args.week})
        rendered = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + '.tmp')
            temporary.write_text(rendered)
            temporary.replace(args.output)
            print(f'Saved {args.output}')
        else:
            print(rendered, end='')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
