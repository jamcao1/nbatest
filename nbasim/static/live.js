import {normalizeSummary,project,compareMarket,scoreAt,statsThrough} from './live-model.mjs';
const $=id=>document.getElementById(id),api='https://site.api.espn.com/apis/site/v2/sports/basketball/nba';
const state={priors:null,game:null,projection:null,replay:null,market:null,receivedAt:null,generation:0,loading:false,lastSchedule:0,quality:[]};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const pct=x=>(100*x).toFixed(1)+'%', number=x=>Number(x).toFixed(1);
function table(headers,rows){const t=el('table'),head=el('tr');headers.forEach(x=>head.append(el('th',x)));const th=el('thead');th.append(head);t.append(th);const b=el('tbody');rows.forEach(row=>{const tr=el('tr');row.forEach(x=>tr.append(el('td',String(x))));b.append(tr);});t.append(b);return t;}
function fail(error){$('live-error').textContent=error.message;$('live-error').hidden=false;}
async function json(url){const response=await fetch(url,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(20000)});if(!response.ok)throw new Error(`Data request failed (${response.status}).`);return response.json();}
function clearMarket(){state.market=null;for(const id of ['market-line','market-over','market-under'])$(id).value='';$('market-result').replaceChildren(el('p','Enter a current line to compare.'));}
function clearAnalysis(){state.projection=null;state.quality=[];$('market-confirm').disabled=true;$('live-summary').replaceChildren();$('live-recent').replaceChildren();$('live-droughts').replaceChildren();$('live-trend').replaceChildren();$('live-diagnosis').textContent='No current projection is available.';$('market-result').replaceChildren(el('p','No current projection; comparison is paused.'));}
function stat(label,value,note){const box=el('div',undefined,'stat');box.append(el('div',label,'stat-label'),el('div',value,'stat-value'),el('div',note,'stat-note'));return box;}
function clock(t){const quarter=Math.max(1,Math.min(4,Math.floor((t-.001)/720)+1)),left=Math.max(0,Math.ceil(quarter*720-t));return `Q${quarter} ${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`;}
function chart(game,until){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 600 120');svg.classList.add('pace-chart');svg.setAttribute('role','img');svg.setAttribute('aria-label','Combined points scored during each completed or partial game minute');
  const values=[];for(let t=0;t<until;t+=60){const a=scoreAt(game,t),b=scoreAt(game,Math.min(t+60,until));values.push(b.home+b.away-a.home-a.away);}
  const max=Math.max(8,...values),width=580/values.length;
  values.forEach((value,i)=>{const rect=document.createElementNS(ns,'rect');rect.setAttribute('x',String(i*width+10));rect.setAttribute('y',String(100-value/max*85));rect.setAttribute('width',String(Math.max(2,width-2)));rect.setAttribute('height',String(Math.max(0,value/max*85)));const title=document.createElementNS(ns,'title');title.textContent=`Minute ${i+1}: ${value} points`;rect.append(title);svg.append(rect);});
  return svg;
}
async function schedule(generation){
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const previous=new Date(today+'T12:00:00Z');previous.setUTCDate(previous.getUTCDate()-1);
  const dates=[today,previous.toISOString().slice(0,10)];
  const replies=await Promise.allSettled(dates.map(d=>json(`${api}/scoreboard?dates=${d.replaceAll('-','')}&limit=1000`)));
  if(generation!==state.generation)return;
  if(replies[0].status!=='fulfilled')throw replies[0].reason;
  const events=replies.flatMap((r,i)=>r.status==='fulfilled'?(r.value.events||[]).filter(e=>[2,3].includes(e.season?.type)&&(i===0||e.status?.type?.state==='in')):[]);
  const unique=[...new Map(events.map(e=>[e.id,e])).values()].sort((a,b)=>(a.status.type.state==='in'?-1:0)-(b.status.type.state==='in'?-1:0));
  const old=$('live-game').value;$('live-game').replaceChildren(...unique.map(e=>{const o=el('option',`${e.shortName} · ${e.status.type.shortDetail||e.status.type.description}`);o.value=e.id;return o;}));
  if(unique.some(e=>e.id===old))$('live-game').value=old;
  else if(old){state.game=null;clearMarket();clearAnalysis();}
  if(!unique.length){const o=el('option','No regular-season or playoff games returned.');o.value='';$('live-game').append(o);}
  state.lastSchedule=Date.now();
}
function renderMarket(){
  if(!state.projection||!state.market)return;
  const box=$('market-result');
  try{
    const r=compareMarket(state.projection,state.market,{receivedAt:state.receivedAt,lastPlayAt:state.game.plays.filter(p=>p.t<=state.game.elapsed).at(-1)?.wallclock,live:$('live-mode').value==='live'&&state.game.state==='in'});
    if(state.quality.length){r.blocks.push(...state.quality);r.status='No signal: feed reconciliation failed';}
    box.replaceChildren(el('h3',r.status),table(['Outcome','Model probability'],[['Over',pct(r.over)],['Under',pct(r.under)],['Push',pct(r.push)]]),
      el('p',`Conditional break-even probabilities: over ${pct(r.breakEvenOver)}, under ${pct(r.breakEvenUnder)}. Model return per $1 risked: over $${r.evOver.toFixed(2)}, under $${r.evUnder.toFixed(2)}. These are unvalidated model calculations, not observed returns.`),
      el('p',`Line ${state.market.line} confirmed at ${new Date(state.market.observedAt).toLocaleTimeString()}. Reconfirm after 60 seconds or whenever the market moves.`));
    for(const reason of r.blocks)box.append(el('p',reason,'warning'));
  }catch(error){box.replaceChildren(el('p',error.message,'warning'));}
}
function render(){
  const game=state.game;if(!game)return;
  const replay=$('live-mode').value==='replay',elapsed=replay?Number($('replay-time').value):game.elapsed;
  const period=Math.max(1,Math.min(4,replay?Math.floor((elapsed-.001)/720)+1:game.period||1));
  for(const option of $('live-scope').options)option.disabled=option.value!=='game'&&option.value!==`q${period}`;
  if(!$('live-scope').selectedOptions[0]||$('live-scope').selectedOptions[0].disabled){$('live-scope').value=`q${period}`;clearMarket();}
  const stamp=state.receivedAt?new Date(state.receivedAt).toLocaleTimeString():'';
  $('replay-clock').textContent=clock(elapsed);
  const gameDate=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',dateStyle:'medium'}).format(new Date(game.date));
  $('live-status').textContent=replay?`HISTORICAL REPLAY · ${game.away.code} at ${game.home.code} · ${gameDate} · ${clock(elapsed)}. Only plays through this clock enter the calculation.`:`${game.away.code} at ${game.home.code} · ${game.status} · Retrieved ${stamp}. Public feed, not guaranteed real time.`;
  $('live-history').hidden=replay;
  if(!replay&&game.state==='in'&&game.clockSource==='last_play')$('live-status').textContent+=' Clock follows the last recorded play.';
  if(!replay&&(game.state!=='in'||game.period>4||elapsed>2880)){clearAnalysis();$('live-diagnosis').textContent=game.state==='pre'?'Waiting for tipoff. No live estimate or market signal is available.':game.state==='post'?'This game is final. Choose an active game or historical replay.':'Overtime or an unknown game status is not supported.';return;}
  if(!replay&&(game.paused||elapsed===0||elapsed%720===0)){
    clearAnalysis();$('live-diagnosis').textContent=elapsed===0?'Waiting for the first recorded possession. Analysis starts automatically once play is available.':'Period break or play paused. Comparisons resume automatically when regulation play continues.';return;
  }
  if(replay&&$('live-scope').value!=='game'&&elapsed%720===0){clearAnalysis();$('live-diagnosis').textContent='This quarter has ended. Move the replay clock forward to analyze the next quarter.';return;}
  const priors=replay?state.replay.priors:state.priors;
  const p=project(game,priors,{scope:$('live-scope').value,elapsed});state.projection=p;
  state.quality=[];
  if(!replay){
    const played=game.plays.filter(x=>x.t<=elapsed),last=played.at(-1);
    if(!last||last.home!==game.home.score||last.away!==game.away.score)state.quality.push('Play-by-play and scoreboard totals disagree.');
    const allStats=statsThrough(game,elapsed);
    if(game.boxPossessions===null||Math.abs(allStats.possessions-game.boxPossessions)>3)state.quality.push('Play-by-play possession counts cannot be reconciled with the live box score.');
    if(!played.some(x=>x.period===p.period&&x.t<=(p.period-1)*720+90))state.quality.push('The beginning of this quarter is missing from the feed.');
  }
  $('live-summary').replaceChildren(stat('SCORE',`${game.away.code} ${p.score.away} · ${game.home.code} ${p.score.home}`,clock(elapsed)),stat('OBSERVED PACE',number(p.observedPace),'Estimated possessions/team/48 min for selected period'),stat('PROJECTED TOTAL',number(p.mean),`${p.scope==='game'?'Full game including simulated OT':'Combined quarter points'} · 80% range ${p.interval80.join('–')}`),stat('BLENDED PACE',number(p.projectedPace),`Historical matchup prior ${number(p.prior.pace)}`));
  $('live-diagnosis').textContent=p.diagnosis;
  $('live-recent').replaceChildren(table(['Last ≤3 game minutes',game.away.code,game.home.code],[['Points',p.recent.away.points,p.recent.home.points],['Field goals',`${p.recent.away.fgm}/${p.recent.away.fga}`,`${p.recent.home.fgm}/${p.recent.home.fga}`],['Estimated possessions',number(p.recent.away.possessions),number(p.recent.home.possessions)],['Turnovers',p.recent.away.to,p.recent.home.to]]));
  $('live-droughts').replaceChildren(el('p',`Since last score in this quarter: ${game.away.code} ${number(p.droughts.away/60)} minutes; ${game.home.code} ${number(p.droughts.home/60)} minutes.`),el('p',`Prior data through ${p.prior.latest}; ${Math.floor(p.priorAgeDays)} days before this game. Team/roster changes are not modeled.`,p.priorAgeDays>30?'warning':''));
  for(const warning of state.quality)$('live-droughts').append(el('p',warning,'warning'));
  $('live-trend').replaceChildren(chart(game,elapsed),el('p','Combined points per game minute; last bar may be a partial minute.'));
  $('market-rules').textContent=p.scope==='game'?'Use the full-game combined total including overtime. Current in-game overtime is not supported.':`Use the combined total for quarter ${p.period} only, including points already scored in that quarter.`;
  $('market-confirm').disabled=false;
  renderMarket();
}
async function refresh(){
  if(state.loading)return;state.loading=true;$('live-refresh').disabled=true;$('live-error').hidden=true;$('live-notice').hidden=true;const generation=++state.generation;
  try{
    if(!state.priors){
      const priors=await json('./pace-priors.json');
      if(generation!==state.generation)return;
      if(!priors.league||!Number.isFinite(priors.league.pace)||!Number.isFinite(priors.league.ppp)||!priors.teams||!Number.isFinite(Date.parse(priors.end)))throw new Error('Historical pace data is invalid.');
      state.priors=priors;
      const old=Date.now()-Date.parse(priors.end+'T00:00:00Z')>30*86400000;
      $('live-history').textContent=`Team history through ${priors.end}. ${old?'History is over 30 days old: live tracking is available, but opportunity watches are paused.':'Watch availability also depends on each team’s recent sample and feed quality.'}`;
    }
    if($('live-mode').value==='replay'){
      if(!state.replay)state.replay=await json('./pace-replay.json');
      if(generation!==state.generation)return;
      state.game=normalizeSummary(state.replay.summary);state.receivedAt=Date.now();render();
    }else{
      if(Date.now()-state.lastSchedule>60000){
        try{await schedule(generation);}
        catch(error){
          if(generation!==state.generation)return;
          if(!/^\d+$/.test($('live-game').value))throw error;
          $('live-notice').textContent='The game list could not refresh. Continuing to fetch the selected game; the list will retry on the next refresh.';
          $('live-notice').hidden=false;
        }
      }
      if(generation!==state.generation)return;
      const id=$('live-game').value;
      if(!/^\d+$/.test(id)){state.game=null;clearAnalysis();$('live-status').textContent='No games available. Historical replay is ready to explore.';return;}
      const raw=await json(`${api}/summary?event=${id}`);
      if(generation!==state.generation)return;
      if(String(raw.header?.id)!==id)throw new Error('The provider returned a different game. Comparison is paused.');
      state.game=normalizeSummary(raw);state.receivedAt=Date.now();render();
    }
  }catch(error){if(generation===state.generation){state.game=null;clearAnalysis();fail(error);$('live-status').textContent='Live data unavailable. Comparisons are paused; no older estimate is being presented as current.';}}
  finally{if(generation===state.generation){state.loading=false;$('live-refresh').disabled=false;}}
}
function changed(){state.generation++;state.loading=false;state.game=null;clearMarket();clearAnalysis();refresh();}
$('live-mode').addEventListener('change',()=>{const replay=$('live-mode').value==='replay';$('replay-controls').hidden=!replay;$('game-label').hidden=replay;changed();});
$('live-game').addEventListener('change',changed);
$('live-scope').addEventListener('change',()=>{clearMarket();render();});
$('replay-time').addEventListener('input',()=>{clearMarket();render();});
$('live-refresh').addEventListener('click',refresh);
$('market-form').addEventListener('submit',event=>{event.preventDefault();state.market={line:Number($('market-line').value),overOdds:Number($('market-over').value),underOdds:Number($('market-under').value),observedAt:Date.now()};renderMarket();});
for(const id of ['market-line','market-over','market-under'])$(id).addEventListener('input',()=>{state.market=null;$('market-result').replaceChildren(el('p','Confirm the edited line and both prices to compare.'));});
setInterval(()=>{if(!document.hidden&&$('live-mode').value==='live'&&$('live-auto').checked)refresh();},30000);
setInterval(()=>{if(!document.hidden)renderMarket();},5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&$('live-mode').value==='live'&&$('live-auto').checked)refresh();});
async function init(){
  refresh();
  try{const e=await json('./pace-evaluation.json');const box=$('live-evaluation');box.append(el('p',`${e.games} historical games · ${e.start} to ${e.end}. Every matchup prior uses earlier games only. ${e.note}`),table(['Market/checkpoint','Model error','Historical-rate error','Straight extrapolation error','80% range coverage'],e.metrics.map(x=>[x.label,x.model_mae.toFixed(1),x.prior_mae.toFixed(1),x.extrapolation_mae.toFixed(1),pct(x.coverage80)])));}catch{ $('live-evaluation').textContent='Replay evaluation is unavailable. No validation or profitability claim is made.';}
}
init();
