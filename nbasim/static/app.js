'use strict';
const $ = id => document.getElementById(id);
const PUBLISHED = document.body.dataset.mode === 'published';
const state = {dataset: null, report: null, rosters: null, mode: 'historical replay', odds: '', busy: false};
const pct = value => `${(value * 100).toFixed(1)}%`;
const signed = value => `${value > 0 ? '+' : ''}${value.toFixed(1)}`;
const fmtDate = value => new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function showError(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
async function api(path, body) {
  if (PUBLISHED) {
    if (path !== '/api/backtest' || body) throw new Error('New simulations and imports are available in the Python app. This website displays the published weekly report.');
    path = './backtest.json';
  }
  const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request failed.');
  return result;
}
function busy(value) {
  state.busy = value;
  for (const id of ['run','demo','live','dataset-file','odds-file','week','seed','clear-odds']) $(id).disabled = value;
  $('run').textContent = value ? 'Simulating…' : 'Run 1,000 simulations ↗';
  $('games').classList.toggle('busy', value);
  $('games').setAttribute('aria-busy', String(value));
}
function modes() {
  $('demo').classList.toggle('selected', state.mode === 'historical replay');
  $('live').classList.toggle('selected', state.mode === 'live public data');
  $('demo').setAttribute('aria-pressed', String(state.mode === 'historical replay'));
  $('live').setAttribute('aria-pressed', String(state.mode === 'live public data'));
}
async function run(reload = false) {
  if (state.busy) return;
  clearError(); busy(true);
  try {
    let dataset = state.dataset;
    if (reload || !dataset || dataset.week_start !== $('week').value) {
      if (state.mode === 'imported') throw new Error('An imported dataset has a fixed week. Import a new dataset to change its dates.');
      const endpoint = state.mode === 'historical replay' ? 'demo' : 'live';
      dataset = await api(`/api/${endpoint}?week=${encodeURIComponent($('week').value)}`);
    }
    const result = await api('/api/simulate', {dataset, seed:Number($('seed').value), odds_csv:state.odds});
    state.dataset = dataset; state.report = result;
    render();
  } catch (error) {
    showError(error);
    if (state.report) $('notice').textContent = `The new run failed. Results below remain from ${state.report.mode}, ${state.report.week_start}.`;
  } finally { busy(false); }
}
function stat(label, value, note, suffix = '') {
  const box = el('div', 'stat'); box.append(el('div','stat-label',label));
  const main = el('div','stat-value',value); if (suffix) main.append(el('small','',suffix));
  box.append(main,el('div','stat-note',note)); return box;
}
function render() {
  const report = state.report, games = report.games;
  const top = [...games].sort((a,b) => b.favorite_probability-a.favorite_probability)[0];
  $('summary').replaceChildren(stat('GAMES ON THE SLATE', String(games.length), 'Seven-day forecast window'), stat('SIMULATED GAMES', (games.length*1000).toLocaleString(), '1,000 independent draws per matchup'), stat('STRONGEST FAVORITE', top ? top.favorite : '—', top ? `${top.away} at ${top.home}` : 'No upcoming games', top ? pct(top.favorite_probability) : ''), stat('TRAINING RESULTS', report.training_games.toLocaleString(), `Through ${report.latest_training_result}`));
  $('week-title').textContent = `Week of ${fmtDate(report.week_start)}, ${report.week_start.slice(0,4)}`;
  $('notice').textContent = report.mode === 'historical replay' ? 'HISTORICAL REPLAY · Real 2014–15 NBA data. These are past matchups, not current NBA predictions. Scores and results from the forecast week are withheld.' : `${report.mode.toUpperCase()} · Ratings use results before ${report.week_start}. Only scheduled, unstarted games are shown for the live feed.`;
  if (PUBLISHED) {
    const stamp = new Intl.DateTimeFormat('en-US', {dateStyle:'medium',timeStyle:'short',timeZone:'America/New_York'}).format(new Date(report.generated_at));
    $('published-at').textContent = `Updated ${stamp} · New York time`;
    const end = new Date(`${report.week_start}T12:00:00Z`); end.setUTCDate(end.getUTCDate()+6);
    const today = new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const expired = end.toISOString().slice(0,10) < today;
    const staleTraining = games.some(g=>g.warnings.some(w=>w.includes('30 days old')));
    $('notice').textContent = `${expired ? 'PAST FORECAST' : 'PUBLISHED WEEKLY FORECAST'} · Games shown were scheduled when this report was generated; this is not a live scoreboard. ${expired ? 'This report’s week has ended. Check the latest workflow run if a new report is missing. ' : ''}${staleTraining ? 'Training results are over 30 days old; offseason roster changes are not modeled.' : ''}`;
  }
  $('source').textContent = report.source;
  $('assumptions').replaceChildren(...report.assumptions.map(x => el('li','',x)));
  $('export').disabled = false;
  $('odds-label').textContent = state.odds ? 'Imported market snapshots · model stays independent' : 'No betting lines loaded';
  $('clear-odds').hidden = !state.odds;
  renderGames();
}
function probabilityBar(p) {
  const bar = el('div','probability-bar');
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 100 4'); svg.setAttribute('preserveAspectRatio','none'); svg.setAttribute('aria-hidden','true');
  const rect = document.createElementNS(svg.namespaceURI,'rect'); rect.setAttribute('width', String(p*100)); rect.setAttribute('height','4');
  svg.append(rect); bar.append(svg); return bar;
}
function renderGames() {
  if (!state.report) return;
  const search = $('search').value.trim().toUpperCase();
  const games = state.report.games.filter(g => `${g.home} ${g.away}`.toUpperCase().includes(search));
  $('game-count').textContent = `${games.length} MATCHUPS · 1,000 SIMULATIONS EACH`;
  $('empty').hidden = games.length > 0;
  $('games').replaceChildren(...games.map(g => {
    const card = el('button','game-card');
    card.setAttribute('aria-label', `${g.away} at ${g.home}, ${g.favorite} ${pct(g.favorite_probability)} win probability. View details.`);
    const meta = el('div','card-meta'); meta.append(el('span','',fmtDate(g.date).toUpperCase()),el('span','tag',g.favorite_probability >= .7 ? 'CLEAR FAVORITE' : g.favorite_probability < .55 ? 'CLOSE MATCHUP' : 'MODEL LEAN')); card.append(meta);
    for (const [team,score,location] of [[g.away,g.projected_away_score,'AWAY'],[g.home,g.projected_home_score,g.neutral?'NEUTRAL':'HOME']]) {
      const row = el('div','team-row'); row.append(el('span','team-avatar',team));
      const name = el('span','team-name',team); name.append(el('span','team-location',location));
      row.append(name,el('span',`score ${g.favorite===team?'winner':''}`,score.toFixed(1))); card.append(row);
    }
    const prob = el('div','probability'), label = el('div','probability-label');
    label.append(el('span','',g.favorite==='Even'?'Even matchup':`${g.favorite} win probability`),el('strong','',pct(g.favorite_probability)));
    prob.append(label,probabilityBar(g.favorite_probability)); card.append(prob);
    const foot = el('div','card-bottom'); foot.append(el('span','',`Projected total ${g.projected_total.toFixed(1)}`),el('span','', 'Explore game ↗')); card.append(foot);
    card.addEventListener('click',() => showDetail(g)); return card;
  }));
}
function table(headers, rows) {
  const t = el('table'), head = el('thead'), tr = el('tr'); headers.forEach(h => tr.append(el('th','',h))); head.append(tr);
  const body = el('tbody'); rows.forEach(row => {const r = el('tr');row.forEach(x => r.append(el('td','',String(x))));body.append(r);}); t.append(head,body); return t;
}
function histogram(bins) {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 600 190'); svg.classList.add('histogram'); svg.setAttribute('role','img');
  svg.setAttribute('aria-label', bins.map(b => `${b.label}: ${b.count} simulations`).join(', '));
  const max = Math.max(1,...bins.map(b=>b.count));
  bins.forEach((bin,i) => {
    const height=bin.count/max*125, rect=document.createElementNS(ns,'rect');
    for(const [k,v] of Object.entries({x:i*100+12,y:145-height,width:76,height,rx:3})) rect.setAttribute(k,String(v));
    const label=document.createElementNS(ns,'text'); label.setAttribute('x',String(i*100+50));label.setAttribute('y','167');label.setAttribute('text-anchor','middle');label.textContent=bin.label;
    const count=document.createElementNS(ns,'text');count.classList.add('bar-count');count.setAttribute('x',String(i*100+50));count.setAttribute('y',String(138-height));count.setAttribute('text-anchor','middle');count.textContent=String(bin.count);
    svg.append(rect,label,count);
  }); return svg;
}
function showDetail(g) {
  const box=$('detail-content');box.replaceChildren(el('h2','',`${g.away} at ${g.home}`),el('p','',`${fmtDate(g.date)} · ${state.report.mode} · Seed ${state.report.seed}`),el('div','detail-score',`${g.projected_away_score.toFixed(1)} — ${g.projected_home_score.toFixed(1)}`),el('p','',`Average projected final score. ${g.favorite === 'Even' ? 'Neither team is favored.' : `${g.favorite} won ${Math.round(g.favorite_probability*1000)} of 1,000 simulations.`}`));
  const stats=el('div','detail-stats');
  for (const [label,value] of [['Home win probability',pct(g.home_win_probability)],['Home margin · 80% range',g.margin_80_interval.map(signed).join(' to ')],['Total · 80% range',g.total_80_interval.join(' to ')]]) {const item=el('div');item.append(el('span','',label),document.createTextNode(value));stats.append(item);}
  box.append(stats,el('h3','','How the 1,000 games ended'),histogram(g.margin_distribution),el('p','',`Home win probability sampling interval (95%): ${g.home_probability_mc_95_interval.map(pct).join('–')}. This measures Monte Carlo sampling error, not uncertainty in the model or its assumptions.`));
  const f=g.factors;
  box.append(el('h3','','What shapes this matchup'),table(['Metric',g.away,g.home],[['Opponent-adjusted offense',f.away?signed(f.away.attack):'League prior',f.home?signed(f.home.attack):'League prior'],['Points conceded adjustment',f.away?signed(f.away.concede):'League prior',f.home?signed(f.home.concede):'League prior'],['Last 10 record',f.away?`${f.away.last_10_wins}–${f.away.last_10_games-f.away.last_10_wins}`:'—',f.home?`${f.home.last_10_wins}–${f.home.last_10_games-f.home.last_10_wins}`:'—'],['Rest days',f.away_rest_days??'Unknown',f.home_rest_days??'Unknown']]));
  box.append(el('p','',`Home-court margin: ${signed(f.home_court_points)} points. Rest margin adjustment: ${signed(f.rest_margin_points)} points for ${g.home}. Positive points-conceded adjustment means weaker defense. Recent records are descriptive, not an additional model bonus.`));
  if(g.market) {
    const m=g.market, rows=[];
    if(m.home_spread!==undefined) rows.push([`${g.home} spread`,signed(m.home_spread)],['Home / away cover',`${pct(m.home_cover_probability)} / ${pct(m.away_cover_probability)}`],['Spread push',pct(m.spread_push_probability)]);
    if(m.total!==undefined) rows.push(['Market total',m.total],['Over / under',`${pct(m.over_probability)} / ${pct(m.under_probability)}`],['Total push',pct(m.total_push_probability)]);
    if(m.home_no_vig_probability!==undefined) rows.push(['Home no-vig market probability',pct(m.home_no_vig_probability)],['Model − market',`${signed(m.home_model_market_difference*100)} percentage points`]);
    if(m.home_spread_movement!==undefined) rows.push(['Uploaded home spread movement',signed(m.home_spread_movement)]);
    if(m.total_movement!==undefined) rows.push(['Uploaded total movement',signed(m.total_movement)]);
    box.append(el('h3','','Market comparison'),table(['Metric','Value'],rows),el('p','',`${m.snapshots} uploaded snapshot(s). Latest: ${m.observed_at}. Movement reflects only your uploaded observations, not a complete market trend. Differences are not validated betting edges.`));
  } else box.append(el('h3','','Market comparison'),el('p','',PUBLISHED ? 'No market lines were supplied for this published report. No betting edge or market trend is claimed.' : 'Upload odds CSV to compare the model with spread, total, and no-vig moneyline probabilities. No lines or betting trends have been invented.'));
  g.warnings.forEach(w=>box.append(el('p','warning',w)));
  if (state.rosters?.status === 'experimental_not_applied') {
    const detail=el('details');detail.append(el('summary','','Current roster changes and estimated minutes'));
    detail.append(el('p','warning','Roster research is not applied to the score or probability above. Minute estimates are not confirmed lineups.'));
    for (const team of [g.away,g.home]) if(state.rosters.teams[team]) detail.append(rosterTeam(team));
    box.append(detail);
  }
  $('detail').showModal();
}
function rosterTeam(code) {
  const team=state.rosters.teams[code], section=el('section','roster-team-detail');
  section.append(el('h3','',code),el('p','',`Compared with the last observed lineup on ${team.comparison_date || 'an unknown date'}. Roster source timestamp: ${team.provider_timestamp}.`));
  section.append(el('p','',`Now listed, absent from that lineup: ${team.added_since_last_box.join(', ') || 'None'}.`),el('p','',`In that lineup, absent from the current roster: ${team.absent_since_last_box.join(', ') || 'None'}.`));
  section.append(el('p','warning',`${pct(team.unknown_minutes_share)} of estimated minutes belong to players with no observed performance history. These comparisons are not a verified list of trades or signings.`));
  const wrap=el('div','roster-table');
  wrap.append(table(['Player','Estimated MIN','Observed PPG','Availability snapshot'],team.players.map(p=>[
    p.name+(p.unknown_player_prior?' · no history':''),p.minutes.toFixed(1),p.points_per_game===null?'Unknown':p.points_per_game.toFixed(1),
    p.injuries?.length?p.injuries.map(i=>`${i.status} (${i.date || 'date unknown'})`).join('; '):'No report returned; availability unconfirmed'
  ])));
  section.append(wrap,el('p','',`PPG uses available games played through ${state.rosters.latest_training_result}, excluding DNPs. Estimated minutes use the last five box-score appearances including DNPs, normalized to 240 per team; displayed rounding can change the sum slightly. New players receive a generic allocation prior. Injury snapshots do not adjust minutes or confirm availability for a future game.`));
  const source=el('a','','View roster source ↗');source.href=team.source;source.target='_blank';source.rel='noopener';section.append(source);
  return section;
}
async function loadRosterContext() {
  if (document.body.dataset.rosters !== 'true') return;
  $('roster-context').hidden=false;
  try {
    const response=await fetch('./rosters.json',{cache:'no-store'});
    if(!response.ok) throw new Error('Current roster context could not be loaded.');
    const r=await response.json();
    if(r.week_start!==state.report.week_start) throw new Error('Roster context belongs to a different forecast window.');
    if(r.status!=='experimental_not_applied') throw new Error('Current roster context is unavailable. The predictions do not include roster adjustments.');
    state.rosters=r;
    const stamp=new Intl.DateTimeFormat('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/New_York'}).format(new Date(r.generated_at));
    $('roster-status').textContent=`Roster snapshot ${stamp}, New York time. This research is not applied to the published predictions. Estimated rotations are not confirmed lineups. ${r.training_games} of ${r.requested_training_games} historical box scores passed validation.`;
    $('roster-controls').hidden=false;
    $('roster-team').replaceChildren(...Object.keys(r.teams).sort().map(t=>{const o=el('option','',t);o.value=t;return o;}));
    const show=()=>$('roster-team-detail').replaceChildren(rosterTeam($('roster-team').value));
    $('roster-team').onchange=show;show();
    if(r.evaluation) {
      const e=r.evaluation, box=$('roster-evaluation');
      box.append(el('h3','','Did the experimental adjustment improve predictions?'),el('p','',`${e.games} held-out games · ${e.start} to ${e.end}. ${e.improved_both_metrics?'Both measured errors decreased, but broader validation is still required.':'It did not improve both measured errors, so the adjustment is not used.'}`));
      box.append(table(['Metric · lower is better','Team baseline','Roster experiment'],[
        ['Probability error (Brier)',e.baseline_brier.toFixed(4),e.candidate_brier.toFixed(4)],
        ['Average margin error',e.baseline_margin_error.toFixed(2)+' pts',e.candidate_margin_error.toFixed(2)+' pts']
      ]),el('p','',e.note));
    }
  } catch(error) {
    state.rosters=null;$('roster-controls').hidden=true;$('roster-team-detail').replaceChildren();
    $('roster-status').textContent=error.message;
  }
}
function download(name, content, type='application/json') {const url=URL.createObjectURL(new Blob([content],{type}));const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('run').addEventListener('click',()=>run(state.mode !== 'imported'));
$('demo').addEventListener('click',()=>{state.mode='historical replay';state.odds='';$('week').value='2015-04-06';modes();run(true);});
$('live').addEventListener('click',()=>{state.mode='live public data';state.odds='';$('week').value=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());modes();run(true);});
$('search').addEventListener('input',renderGames);
$('close-detail').addEventListener('click',()=>$('detail').close());
$('export').addEventListener('click',()=>download(`nba-${state.report.week_start}-simulations.json`,JSON.stringify(state.report,null,2)));
$('download-dataset').addEventListener('click',async()=>{try{const data=state.dataset||await api('/api/demo');download('nba-dataset.json',JSON.stringify(data,null,2));}catch(e){showError(e);}});
$('dataset-file').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;clearError();busy(true);
  try{if(file.size>2000000)throw new Error('Dataset must be smaller than 2 MB.');const dataset=JSON.parse(await file.text());dataset.mode='imported';
    const result=await api('/api/simulate',{dataset,seed:Number($('seed').value)});
    state.dataset=dataset;state.report=result;state.mode='imported';state.odds='';$('week').value=result.week_start;modes();render();
  }catch(error){showError(error);}finally{event.target.value='';busy(false);}
});
$('odds-file').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;clearError();busy(true);
  try{if(!state.dataset)throw new Error('Load a dataset before importing odds.');if(file.size>500000)throw new Error('Odds CSV must be smaller than 500 KB.');const odds=await file.text();
    const result=await api('/api/simulate',{dataset:state.dataset,seed:Number($('seed').value),odds_csv:odds});state.odds=odds;state.report=result;render();
  }catch(error){showError(error);}finally{event.target.value='';busy(false);}
});
$('clear-odds').addEventListener('click',()=>{state.odds='';run();});
$('backtest').addEventListener('click',async()=>{const button=$('backtest');button.disabled=true;button.textContent='Replaying historical games…';clearError();try{
  const r=await api('/api/backtest'), box=$('backtest-result'), grid=el('div','backtest-grid');
  for(const [label,value] of [['Winner accuracy',pct(r.winner_accuracy)],['Brier score · lower is better',r.brier_score.toFixed(3)],['Baseline Brier score',r.home_rate_baseline_brier.toFixed(3)],['80% margin range coverage',pct(r.margin_80_coverage)]]){const d=el('div','',value);d.append(el('span','',label));grid.append(d);}
  box.replaceChildren(grid,el('p','',`${r.games} games · March 2–April 12, 2015. Margin error: ${r.margin_mae.toFixed(1)} points; total error: ${r.total_mae.toFixed(1)} points. ${r.note}`));
  const details=el('details'), summary=el('summary','','Probability calibration');details.append(summary,table(['Predicted home win bin','Games','Observed rate'],r.calibration.map(c=>[c.bin,c.games,c.actual_home_win_rate===null?'—':pct(c.actual_home_win_rate)])));box.append(details);
}catch(error){showError(error);}finally{button.disabled=false;button.textContent=PUBLISHED?'View historical backtest ↗':'Run historical backtest ↗';}});
async function loadPublishedReport() {
  clearError();
  try {
    const response = await fetch('./weekly.json', {cache:'no-store'});
    if (!response.ok) throw new Error('The weekly report could not be loaded. Please refresh or check the latest workflow run.');
    const report = await response.json();
    if (!Array.isArray(report.games) || report.simulations_per_game !== 1000) throw new Error('The published report has an unexpected format.');
    state.report = report;
    $('backtest').textContent = 'View historical backtest ↗';
    render();
    await loadRosterContext();
  } catch(error) {
    $('notice').textContent = 'Published report unavailable.';
    showError(error);
  }
}
if (PUBLISHED) loadPublishedReport(); else run();
