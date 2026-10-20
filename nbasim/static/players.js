import {estimate} from './player-model.mjs';
const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
const state={data:null,generation:0},f=x=>Number(x).toFixed(1);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const svg=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
const date=x=>new Intl.DateTimeFormat('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/New_York'}).format(new Date(x))+' ET';
async function json(path){const r=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(20000)});if(!r.ok)throw new Error(`Research request failed (${r.status}).`);return r.json();}
function clear(){for(const id of ['player-cards','venue-context','player-market'])$(id).replaceChildren();$('players-notice').hidden=true;}
function table(headers,rows){const t=el('table',undefined,'shot-table'),head=el('tr');headers.forEach(x=>head.append(el('th',x)));const th=el('thead');th.append(head);t.append(th);const b=el('tbody');rows.forEach(row=>{const tr=el('tr');row.forEach(x=>tr.append(el('td',String(x))));b.append(tr);});t.append(b);return t;}
function courtBase(){
  const court=svg('svg',{viewBox:'0 0 500 470',role:'img','aria-label':'Half-court scoring map'});court.classList.add('court');
  const lines=svg('g',{'class':'court-line'});
  lines.append(svg('rect',{x:1,y:1,width:498,height:468}),svg('rect',{x:170,y:0,width:160,height:190}),
    svg('circle',{cx:250,cy:190,r:60}),svg('path',{d:'M30 0 V142 A237.5 237.5 0 0 0 470 142 V0'}),
    svg('path',{d:'M190 470 A60 60 0 0 1 310 470'}),svg('path',{d:'M220 40 H280'}),
    svg('circle',{cx:250,cy:52.5,r:7.5}),svg('path',{d:'M210 52.5 A40 40 0 0 0 290 52.5'}));
  court.append(lines);return court;
}
function card(game,code,home){
  const team=game.teams[code],root=el('article',undefined,'player-card');root.dataset.team=code;
  const heading=el('div',undefined,'player-heading'),badge=el('div',code,'player-monogram'),names=el('div');
  const title=el('h2'),subtitle=el('p');names.append(el('span',`${code} · ${game.neutral?'NEUTRAL':home?'HOME':'AWAY'}`,'eyebrow'),title,subtitle);heading.append(badge,names);
  const label=el('label','Inspect a player','sr-only'),select=el('select',undefined,'player-select');select.id=`player-${code}`;label.htmlFor=select.id;
  for(const p of team.players){const o=el('option',`${p.name}${p.excluded?' · Out':p.status!=='available'?' · Not rated':` · ${f(p.expected_points)} pts`}`);o.value=p.id;select.append(o);}
  select.value=team.leader_id||team.players[0]?.id||'';
  const content=el('div');root.append(heading,label,select,content);
  function show(){
    const selected=team.players.find(p=>p.id===select.value);content.replaceChildren();if(!selected)return;
    const player={...state.data.profiles[selected.id],...selected};
    title.textContent=player.name;subtitle.textContent=player.id===team.leader_id?'Projected scoring leader':'Player scoring profile';
    if(player.status!=='available'){content.append(el('p','Insufficient history for a player-specific scoring estimate. No shooting profile has been invented.','no-profile'));return;}
    let minutes=player.minutes,mode='expected',outcome='all',selectedZone=null;
    const availability=el('p',undefined,'availability');
    const injuries=(player.injuries||[]).map(i=>`${i.status}${i.date?' · '+i.date:''}`).join('; ');
    availability.textContent=player.excluded?`Listed Out in this snapshot. Excluded from the scoring-leader selection. ${injuries}`:
      injuries?`${injuries}. Estimate is conditional on playing.`:'No injury designation returned in this snapshot; availability is not confirmed.';
    const number=el('div',undefined,'scoring-number'),points=el('strong');number.append(points,el('span','expected points'));
    const range=el('p',undefined,'player-range'),scope=el('p','REGULATION ONLY · CONDITIONAL ON MINUTES','projection-scope');
    const strip=el('div',undefined,'basket-strip');
    const metrics=[['Made baskets','baskets'],['Missed field goals','misses'],['Made free throws','freeThrows']].map(([label,key])=>{const item=el('div'),value=el('strong');item.append(value,el('span',label));strip.append(item);return {key,value};});
    const control=el('label',undefined,'minutes-control'),output=el('output'),slider=el('input');
    slider.type='range';slider.min='0';slider.max='48';slider.step='.5';slider.value=String(minutes);slider.setAttribute('aria-label',`${player.name} estimated regulation minutes`);slider.disabled=player.excluded;
    const reset=el('button','Reset','reset-minutes');reset.type='button';
    control.append(document.createTextNode('Minutes scenario · '),output,slider);control.append(reset);
    const controls=el('div',undefined,'chart-controls'),expected=el('button','Projected zones'),historical=el('button','Recorded shots');
    expected.type=historical.type='button';controls.append(expected,historical);
    const filters=el('div',undefined,'chart-controls');filters.hidden=true;
    const filterButtons=['all','makes','misses'].map(value=>{const b=el('button',value[0].toUpperCase()+value.slice(1));b.type='button';b.addEventListener('click',()=>{outcome=value;draw();});filters.append(b);return {b,value};});
    const drawing=el('div'),caption=el('p',undefined,'court-caption'),tableBox=el('div',undefined,'shot-table-wrap');
    const evidence=el('div',undefined,'player-factors');
    evidence.append(el('h3','What shapes this estimate'),
      el('p',`${player.games} observed appearances · ${player.history_start} to ${player.latest_result}. ${f(player.points_per_game)} historical points per appearance.`),
      el('p',`Matchup pace: ${f(player.matchup_pace)} possessions per team per 48 minutes. Attempt-volume adjustment: ${(100*(player.pace_factor-1)).toFixed(1)}%.`),
      el('p',`${game.neutral?'Neutral-site':home?'Home':'Away'} usage association: ${(100*(player.venue_factor-1)).toFixed(1)}%. Opponent zone accuracy is shrunk toward league averages.`),
      el('p',player.venue_games?`${game.venue.name}: ${player.venue_games} sampled appearances, ${f(player.venue_ppg)} points per appearance. Descriptive split, not an arena bonus.`:`No sampled appearances at ${game.venue.name}; no arena-specific effect is assumed.`),
      el('p',`Mapped ${player.located_attempts} of ${player.historical_attempts} historical field-goal attempts. Other attempts remain unlocated.`));
    const recent=el('div',undefined,'recent-points');recent.setAttribute('role','img');recent.setAttribute('aria-label','Recent recorded points: '+player.last_games.map(g=>`${g.date}: ${g.points}`).join(', '));
    const max=Math.max(1,...player.last_games.map(g=>g.points));
    for(const g of player.last_games){const bar=el('div');bar.style.height=`${Math.max(2,g.points/max*70)}px`;bar.title=`${g.date} vs ${g.opponent}: ${g.points} points in ${f(g.minutes)} minutes`;bar.append(el('span',String(g.points)));recent.append(bar);}
    evidence.append(recent,el('p','Last ten recorded appearances · oldest to newest. These are past results, not future scoring paths.'));
    content.append(availability,number,scope,range,strip,control,controls,filters,drawing,caption,tableBox,evidence);
    let projection;
    function draw(){
      if(!projection||projection.minutes!==minutes)projection=estimate(player,minutes);
      points.textContent=f(projection.points);range.textContent=`Model 80% range: ${projection.interval80.join('–')} points · uncalibrated`;
      metrics.forEach(x=>x.value.textContent=f(projection[x.key]));
      output.textContent=`${f(minutes)}${Math.abs(minutes-player.minutes)>.01?' · edited scenario':' · model estimate'}`;
      expected.setAttribute('aria-pressed',String(mode==='expected'));historical.setAttribute('aria-pressed',String(mode==='history'));filters.hidden=mode!=='history';
      filterButtons.forEach(({b,value})=>b.setAttribute('aria-pressed',String(value===outcome)));
      const court=courtBase();
      court.setAttribute('role',mode==='expected'?'group':'img');
      if(mode==='expected'){
        const positions={rim:[250,55],paint:[250,151],mid:[399,204],corner3:[69,69],arc3:[260,357]};
        for(const z of projection.zones){if(!positions[z.id])continue;const [x,y]=positions[z.id];
          const mark=svg('g',{'class':`zone-marker ${selectedZone===z.id?'selected':''}`,tabindex:0,role:'button','aria-label':`${z.label}: ${f(z.points)} projected points, ${f(z.made)} made, ${f(z.misses)} missed`});
          mark.append(svg('circle',{cx:x,cy:y,r:Math.max(30,Math.min(43,28+z.points*1.4))}));
          const value=svg('text',{x,y:y+3,'class':'zone-value'});value.textContent=f(z.points);
          const label=svg('text',{x,y:y+20});label.textContent=z.id==='corner3'?'Both corners':z.id==='paint'?'Paint':z.id==='arc3'?'Above break':z.label;
          mark.append(value,label);
          const choose=()=>{selectedZone=selectedZone===z.id?null:z.id;draw();};
          mark.addEventListener('click',choose);mark.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});court.append(mark);
        }
        caption.textContent='Expected points by area. Zone markers are schematic, not future shot locations. Select a marker to highlight its row. Free throws and unlocated shots are in the table.';
      }else{
        const shots=player.shots.filter(s=>s[1]<=41.75&&(outcome==='all'||(outcome==='makes')===Boolean(s[2])));
        for(const [x,y,made,worth,when]of shots){
          const cx=x*10,cy=(y+5.25)*10;
          const point=made?svg('circle',{cx,cy,r:3.6,'class':'shot-made'}):svg('path',{d:`M${cx-3} ${cy-3}l6 6m-6 0l6 -6`,'class':'shot-miss'});
          const title=svg('title');title.textContent=`${when}: ${made?'Made':'Missed'} ${worth}-point attempt`;point.append(title);court.append(point);
        }
        caption.textContent=`${shots.length} plotted ${outcome==='all'?'attempts':outcome} from the latest ${player.shots.length} recorded locations. Green ● made; orange × missed. The table covers all ${player.games} sampled appearances.`;
      }
      drawing.replaceChildren(court);
      const headers=mode==='expected'?['Area','Made','Missed','Points']:['Area','Made','Missed','FG / FT %'];
      const rows=projection.zones.map(z=>mode==='expected'?[z.label,f(z.made),f(z.misses),f(z.points)]:
        [z.label,z.historical_made,z.historical_attempts-z.historical_made,z.historical_attempts?(100*z.historical_made/z.historical_attempts).toFixed(1)+'%':'—']);
      const t=table(headers,rows);
      [...t.tBodies[0].rows].forEach((r,i)=>r.classList.toggle('selected',projection.zones[i].id===selectedZone));
      tableBox.replaceChildren(t);
    }
    slider.addEventListener('input',()=>{minutes=Number(slider.value);draw();});
    reset.addEventListener('click',()=>{minutes=player.minutes;slider.value=String(minutes);draw();});
    expected.addEventListener('click',()=>{mode='expected';draw();});historical.addEventListener('click',()=>{mode='history';draw();});
    draw();
  }
  select.addEventListener('change',show);show();return root;
}
function render(){
  clear();const game=state.data.games.find(g=>g.id===$('player-game').value);if(!game)return;
  if(game.status!=='available'){$('players-error').textContent=`Matchup research is unavailable: ${game.reason}`;$('players-error').hidden=false;return;}
  $('players-error').hidden=true;
  const title=el('div');title.append(el('span','THE MATCHUP','eyebrow'),el('h2',`${game.away} at ${game.home}`),el('p',date(game.start)));
  const venue=el('div');venue.append(el('span','THE COURT','eyebrow'),el('h2',game.venue.name),el('p',`${game.venue.city}${game.neutral?' · Neutral site':''}`));
  $('venue-context').append(title,venue);
  $('players-notice').hidden=false;
  const aged=Date.now()-Date.parse(state.data.history_end+'T00:00:00Z')>30*86400000;
  const past=Date.now()>=Date.parse(game.start);
  const staleRoster=Date.now()-Date.parse(state.data.roster_generated_at)>86400000;
  $('players-notice').textContent=`${past?'PREGAME SNAPSHOT · Scheduled tipoff has passed; these are not live player totals. ':''}${aged?'Historical shooting data is over 30 days old. ':''}${staleRoster?'Roster snapshot is over a day old. ':''}Current roster and injury snapshots inform eligibility, but new roles and confirmed rotations are not known. Regulation estimates are conditional on the listed minutes.`;
  for(const side of ['away','home'])$('player-cards').append(card(game,game[side],side==='home'));
  const market=$('player-market');
  if(!game.markets.length)market.append(el('p','No opening/latest game quotes were returned. No market trend is inferred.'));
  for(const m of game.markets){
    market.append(el('p',m.provider));
    for(const [label,open,latest]of [['Game total',m.total_open,m.total_latest],[`${game.home} spread`,m.home_spread_open,m.home_spread_latest]]){
      const box=el('div',undefined,'market-move');box.append(el('span',label),el('strong',`${open??'Unavailable'} → ${latest??'Unavailable'}`),
        el('span',open!==null&&latest!==null?`${latest-open>0?'+':''}${f(latest-open)} points from opening quote`:'Both quotes are needed to show movement'));market.append(box);
    }
  }
  market.append(el('p',`Context retrieved ${date(game.retrieved_at)}. This is the retrieval time, not a verified price-change timestamp.`));
  const source=el('a','View source game research ↗','player-source');source.href=`https://www.espn.com/nba/game/_/gameId/${game.id}`;source.target='_blank';source.rel='noopener noreferrer';market.append(source);
}
async function load(){
  const generation=++state.generation;$('players-retry').disabled=true;$('player-game').disabled=true;$('players-error').hidden=true;clear();
  try{
    const data=await json('./players.json');if(generation!==state.generation)return;
    if(data.status!=='experimental'||!Array.isArray(data.games))throw new Error(data.reason||'Player research has not been generated yet.');
    state.data=data;
    $('players-status').textContent=`Research updated ${date(data.generated_at)} · ${data.history_games} historical games through ${data.history_end}.`;
    const previous=$('player-game').value;
    $('player-game').replaceChildren(...data.games.map(g=>{const o=el('option',`${g.away} at ${g.home} · ${g.date}${g.status!=='available'?' · unavailable':''}`);o.value=g.id;return o;}));
    const query=new URLSearchParams(location.search).get('game');
    if(data.games.some(g=>g.id===(query||previous)))$('player-game').value=query||previous;
    $('player-game').disabled=!data.games.length;
    $('player-method').replaceChildren(...data.limitations.map(s=>el('p',s)));
    if(!data.games.length)$('players-status').textContent+=' No scheduled matchups in this report.';
    render();
  }catch(e){if(generation===state.generation){state.data=null;clear();$('players-error').textContent=e.message;$('players-error').hidden=false;$('players-status').textContent='Player projections are unavailable; no older report is being shown.';}}
  finally{if(generation===state.generation)$('players-retry').disabled=false;}
}
$('player-game').addEventListener('change',render);$('players-retry').addEventListener('click',load);
load();
json('./player-evaluation.json').then(e=>{
  if(!e.leaders)throw new Error('Unavailable');
  $('player-evaluation').append(el('p',`${e.games} past games · ${e.leaders} pregame-selected scoring leaders · ${e.start} to ${e.end}.`),
    table(['Points error · lower is better','Mean absolute error'],[['Scoring model',f(e.mae)],['Last-ten scoring average',f(e.baseline_mae)]]),
    el('p',e.mae>=e.baseline_mae?'The model did not beat the last-ten scoring average in this sample. Treat the added detail as exploratory.':'The model had lower error in this sample; this does not establish future accuracy.'),el('p',e.note));
}).catch(()=>{$('player-evaluation').textContent='Replay evaluation is unavailable. No accuracy or betting-performance claim is made.';});
