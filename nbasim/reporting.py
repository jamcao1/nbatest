"""Readable weekly reports, suitable for scheduled job artifacts."""
from datetime import timedelta

from .data import day


def markdown(report):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    end = day(report['week_start']) + timedelta(days=6)
    lines = [f"# NBA simulations: {report['week_start']} to {end}", '',
             f"Source: {cell(report['source'])}", f"Generated: {report['generated_at']}", '',
             f"**{len(report['games'])} matchups, 1,000 simulations per game.** "
             f"Model: {report['model_version']}; seed: {report['seed']}.", '',
             f"Training: {report['training_games']} completed games; latest result: {report['latest_training_result']}.", '',
             'Projected scores are averages, not exact-score predictions. Win probabilities are model estimates. '
             'Injuries, lineups, and roster changes are not modeled.', '']
    warnings = sorted({w for game in report['games'] for w in game['warnings']})
    if any('30 days old' in w for w in warnings):
        lines += ['**Prior-season/stale-data caution:** some training results are over 30 days old. '
                  'These estimates do not incorporate offseason roster changes.', '']
    lines += ['| Date | Away at home | Average score (away–home) | Favored team | Win probability | Home margin: 80% range |',
              '|---|---|---:|---|---:|---:|']
    for game in report['games']:
        lo, hi = game['margin_80_interval']
        lines.append(f"| {game['date']} | {cell(game['away'])} at {cell(game['home'])} | "
                     f"{game['projected_away_score']:.1f}–{game['projected_home_score']:.1f} | "
                     f"{cell(game['favorite'])} | {game['favorite_probability']:.1%} | {lo:+.1f} to {hi:+.1f} |")
    if not report['games']:
        lines += ['', 'No scheduled matchups were returned for this window.']
    lines += ['', 'Positive home margin means the home team wins. The 80% range describes simulated game '
              'variation, not all uncertainty about the model.', '', '## Game analysis', '']
    for game in report['games']:
        f = game['factors']
        lines += [f"### {game['date']}: {cell(game['away'])} at {cell(game['home'])}", '',
                  f"{cell(game['favorite'])} is the most frequent winner ({game['favorite_probability']:.1%}). "
                  f"Projected total: {game['projected_total']:.1f}. Home-court margin: {f['home_court_points']:+.2f} points; "
                  f"rest adjustment to the home margin: {f['rest_margin_points']:+.2f} points.", '']
        for side in ('away', 'home'):
            profile = f[side]
            if profile:
                lines.append(f"- {cell(game[side])}: offense {profile['attack']:+.2f}; points conceded "
                             f"{profile['concede']:+.2f} (positive means weaker defense); "
                             f"{profile['games']} training games; most recent {profile['last_played']}.")
        lines += [f"- {cell(w)}" for w in game['warnings']]
        market = game.get('market')
        if not market:
            lines += ['- No market lines supplied; no betting edge or market trend is claimed.']
        else:
            lines += [f"- Market snapshot: {market['observed_at']}."]
            for key, label in [('home_cover_probability', 'Home spread cover'), ('over_probability', 'Over'),
                               ('home_no_vig_probability', 'Home no-vig market probability')]:
                if key in market:
                    lines.append(f"- {label}: {market[key]:.1%}.")
            lines.append('- Full market prices, push probabilities, and uploaded line movement are in the JSON report.')
        lines.append('')
    lines += ['## Model assumptions', ''] + [f'- {cell(a)}' for a in report['assumptions']]
    return '\n'.join(lines) + '\n'
