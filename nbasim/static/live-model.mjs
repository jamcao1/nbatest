// Experimental totals model shared by the browser and chronological replay tests.
export const VERSION = 'live-pace-v1';
export function seconds(clock) {
  if (/^\d{1,2}(?:\.\d+)?$/.test(String(clock)) && Number(clock)<60) return Number(clock);
  const m = /^(\d{1,2}):(\d{2}(?:\.\d+)?)$/.exec(String(clock));
  if (!m || +m[2] >= 60) throw new Error('The game clock is invalid.');
  return +m[1]*60 + +m[2];
}
const periodLength = n => n <= 4 ? 720 : 300;
const periodStart = n => n <= 4 ? (n-1)*720 : 2880+(n-5)*300;
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const average = xs => xs.reduce((a,b)=>a+b,0)/xs.length;

export function normalizeSummary(raw) {
  const c=raw.header?.competitions?.[0];
  if(!c || c.competitors?.length!==2) throw new Error('Two teams and a game status are required.');
  const sides=Object.fromEntries(c.competitors.map(t=>[t.homeAway,t]));
  if(!sides.home || !sides.away) throw new Error('Home/away identities are missing.');
  const status=c.status||{}, state=status.type?.state||'unknown';
  const home={id:String(sides.home.team.id),code:sides.home.team.abbreviation,score:Number(sides.home.score??(state==='pre'?0:NaN))},
        away={id:String(sides.away.team.id),code:sides.away.team.abbreviation,score:Number(sides.away.score??(state==='pre'?0:NaN))};
  if(![home.score,away.score].every(x=>Number.isFinite(x)&&x>=0)) throw new Error('Scoreboard totals are invalid.');
  const seen=new Set();
  const plays=(raw.plays||[]).map(p=>{
    const n=Number(p.period?.number), remaining=seconds(p.clock?.displayValue);
    if(!Number.isInteger(n)||n<1||remaining>periodLength(n)||seen.has(String(p.id))) throw new Error('Invalid or duplicate play-by-play event.');
    seen.add(String(p.id));
    return {id:String(p.id),seq:Number(p.sequenceNumber),period:n,t:periodStart(n)+periodLength(n)-remaining,
            home:Number(p.homeScore),away:Number(p.awayScore),team:String(p.team?.id||''),
            type:String(p.type?.text||'').replace(/\s+/g,' ').toLowerCase(),text:p.text||'',
            shot:p.shootingPlay===true,attempted:Number(p.pointsAttempted||0),scoring:p.scoringPlay===true,
            wallclock:p.wallclock?Date.parse(p.wallclock):null};
  }).sort((a,b)=>a.t-b.t||a.seq-b.seq);
  if(plays.some(p=>![p.home,p.away,p.seq].every(Number.isFinite)||p.home<0||p.away<0)) throw new Error('Invalid play-by-play scores.');
  let period=Number(status.period||plays.at(-1)?.period||0), elapsed=0;
  if(state==='in') {
    if(!period) throw new Error('Waiting for the first recorded play.');
    if(status.displayClock) {
      const clock=seconds(status.displayClock);
      if(clock>periodLength(period)) throw new Error('Live clock exceeds period length.');
      elapsed=periodStart(period)+periodLength(period)-clock;
    } else if(plays.length) elapsed=plays.at(-1).t;
    else throw new Error('Live period/clock is unavailable.');
  } else if(state==='post') elapsed=periodStart(period)+periodLength(period);
  let boxPossessions=null;
  try {
    const estimates=raw.boxscore.teams.map(t=>{const d=Object.fromEntries(t.statistics.map(s=>[s.name,s.displayValue]));return Number(d['fieldGoalsMade-fieldGoalsAttempted'].split('-')[1])+.44*Number(d['freeThrowsMade-freeThrowsAttempted'].split('-')[1])-Number(d.offensiveRebounds)+Number(d.totalTurnovers);});
    if(estimates.length===2&&estimates.every(Number.isFinite))boxPossessions=average(estimates);
  } catch { /* Unavailable live box scores must not be silently treated as zero. */ }
  return {id:String(raw.header.id),date:c.date,home,away,state,period,elapsed,plays,boxPossessions,clockSource:status.displayClock?'scoreboard':'last_play',
          status:status.type?.detail||status.type?.description||state};
}

export function scoreAt(game, elapsed) {
  const p=game.plays.filter(p=>p.t<=elapsed).at(-1);
  return p?{home:p.home,away:p.away}:{home:0,away:0};
}

export function statsThrough(game, end, start=0, period=null) {
  const empty=()=>({fga:0,fgm:0,fta:0,orb:0,to:0,points:0,possessions:0});
  const out={home:empty(),away:empty()};
  const selected=game.plays.filter(p=>p.t<=end && p.t>start && (period===null||p.period===period));
  for(const p of selected) {
    const team=p.team===game.home.id?out.home:p.team===game.away.id?out.away:null;
    if(!team) continue;
    if(p.shot&&p.attempted>=2){team.fga++;if(p.scoring)team.fgm++;}
    if(p.shot&&p.attempted===1) team.fta++;
    // Team/dead-ball rebounds are not individual offensive rebounds in the box-score estimator.
    if(p.type==='offensive rebound'&&!/team rebound/i.test(p.text))team.orb++;
    if(p.type.includes('turnover'))team.to++;
  }
  const before=period!==null?
    game.plays.filter(p=>p.period<period&&p.t<=start).at(-1):game.plays.filter(p=>p.t<=start).at(-1);
  const after=period!==null?selected.at(-1):game.plays.filter(p=>p.t<=end).at(-1);
  for(const side of ['home','away']) {
    out[side].points=Math.max(0,(after?.[side]??before?.[side]??0)-(before?.[side]??0));
    out[side].possessions=Math.max(0,out[side].fga+.44*out[side].fta-out[side].orb+out[side].to);
  }
  out.possessions=(out.home.possessions+out.away.possessions)/2;
  return out;
}

function rngFor(text) {
  let seed=2166136261;
  for(const char of text)seed=Math.imul(seed^char.charCodeAt(0),16777619)>>>0;
  const uniform=()=>{seed+=0x6D2B79F5;let x=seed;x=Math.imul(x^x>>>15,x|1);x^=x+Math.imul(x^x>>>7,x|61);return ((x^x>>>14)>>>0)/4294967296;};
  return ()=>Math.sqrt(-2*Math.log(Math.max(uniform(),1e-12)))*Math.cos(2*Math.PI*uniform());
}
function quantile(values,p){return values[Math.floor((values.length-1)*p)];}
export function matchupPrior(game, priors) {
  const h=priors.teams[game.home.code], a=priors.teams[game.away.code], league=priors.league;
  if(!league||!Number.isFinite(league.pace)||!Number.isFinite(league.ppp)) throw new Error('Historical pace priors are unavailable.');
  const shrink=(t,key,fallback)=>t?(t[key]*t.games+fallback*10)/(t.games+10):fallback;
  const pace=(shrink(h,'pace',league.pace)+shrink(a,'pace',league.pace))/2;
  return {pace,homePPP:(shrink(h,'offense_ppp',league.ppp)+shrink(a,'defense_ppp',league.ppp))/2,
          awayPPP:(shrink(a,'offense_ppp',league.ppp)+shrink(h,'defense_ppp',league.ppp))/2,
          missing:!h||!a,latest:[h?.latest_result||priors.end,a?.latest_result||priors.end].sort()[0],
          recentGames:Math.min(h?.recent_games??0,a?.recent_games??0)};
}

export function project(game, priors, {scope='game',elapsed=game.elapsed,draws=2000}={}) {
  if(!Number.isInteger(draws)||draws<100||draws>20000) throw new Error('Use 100 to 20,000 simulation draws.');
  if(!Number.isFinite(elapsed)||elapsed<=0||elapsed>2880) throw new Error('Analysis requires regulation play to have started. Overtime already in progress is unsupported.');
  const period=Math.min(4,Math.floor((elapsed-.001)/720)+1);
  const quarter=/^q[1-4]$/.test(scope)?Number(scope[1]):null;
  if(scope!=='game'&&quarter===null) throw new Error('Choose a quarter or the full game.');
  if(quarter!==null && quarter!==period) throw new Error('Select the quarter currently being played.');
  const start=quarter!==null?(quarter-1)*720:0,end=quarter!==null?quarter*720:2880;
  const minutes=(elapsed-start)/60, remaining=(end-elapsed)/60;
  if(remaining<=0) throw new Error('This market period has ended.');
  const stats=statsThrough(game,elapsed,start,quarter), prior=matchupPrior(game,priors), score=scoreAt(game,elapsed);
  // A twelve-minute pace prior and thirty possessions of scoring prior limit reactions to brief runs.
  const paceRate=(prior.pace/48*12+stats.possessions)/(12+minutes);
  const homePPP=(prior.homePPP*30+stats.home.points)/(30+stats.home.possessions);
  const awayPPP=(prior.awayPPP*30+stats.away.points)/(30+stats.away.possessions);
  const recentStart=Math.max(start,elapsed-180), recent=statsThrough(game,elapsed,recentStart,null);
  const recentMinutes=(elapsed-recentStart)/60;
  const recentPace=recentMinutes?recent.possessions/recentMinutes*48:null;
  const droughts={};
  for(const side of ['home','away']) {
    const scoring=game.plays.filter((p,i)=>p.t<=elapsed&&p.period===period&&p[side]>(game.plays[i-1]?.[side]||0));
    droughts[side]=elapsed-Math.max((period-1)*720,scoring.at(-1)?.t??(period-1)*720);
  }
  const recentShots=recent.home.fga+recent.away.fga, recentMakes=recent.home.fgm+recent.away.fgm;
  let diagnosis='Mixed or insufficient evidence; a short scoreless stretch does not establish a lasting trend.';
  if(recentMinutes>=2 && recentPace < prior.pace*.8) diagnosis='Fewer possessions in the recent window: slower play is contributing to the low scoring.';
  else if(recentMinutes>=2 && recentShots>=4 && recentMakes/recentShots<.3) diagnosis='Possessions are continuing but shots are not falling. Misses are contributing; a rebound in scoring is not guaranteed.';
  else if(recentMinutes>=2 && recent.home.to+recent.away.to>=3) diagnosis='Turnovers are ending possessions without shots. Tempo alone is not translating into scoring.';
  const normal=rngFor(`${VERSION}:${game.id}:${elapsed}:${scope}`), totals=[];
  let overtimes=0;
  const baseHome=quarter!==null?stats.home.points:score.home,baseAway=quarter!==null?stats.away.points:score.away;
  for(let i=0;i<draws;i++) {
    const rate=clamp(paceRate+normal()*.28*Math.sqrt(12/(12+minutes)),.8,3.3);
    const hp=clamp(homePPP+normal()*.14*Math.sqrt(30/(30+stats.home.possessions)),.55,1.65),
          ap=clamp(awayPPP+normal()*.14*Math.sqrt(30/(30+stats.away.possessions)),.55,1.65);
    const drawScore=(duration,ppp)=>{const mean=rate*duration*ppp;return Math.max(0,Math.round(mean+normal()*Math.sqrt(1.5*mean)));};
    let h=baseHome+drawScore(remaining,hp),a=baseAway+drawScore(remaining,ap);
    if(scope==='game'&&h===a) {
      overtimes++;
      for(let ot=0;ot<10&&h===a;ot++){h+=drawScore(5,hp);a+=drawScore(5,ap);}
      if(h===a)h++; // Numerically negligible termination guard after ten simulated overtimes.
    }
    totals.push(h+a);
  }
  totals.sort((a,b)=>a-b);
  const gameDay=Date.parse(game.date),priorDay=Date.parse(prior.latest+'T00:00:00Z');
  return {scope,period,elapsed,remaining,minutes,score,stats,prior,recent,recentPace,droughts,diagnosis,
          observedPace:stats.possessions/minutes*48,projectedPace:paceRate*48,homePPP,awayPPP,
          mean:average(totals),interval80:[quantile(totals,.1),quantile(totals,.9)],totals,
          overtimeProbability:overtimes/draws,priorAgeDays:Math.max(0,(gameDay-priorDay)/86400000)};
}

export function compareMarket(projection, {line,overOdds,underOdds,observedAt}, {now=Date.now(),receivedAt,lastPlayAt,live=true}={}) {
  if(!Number.isFinite(line)||line<=0||!Number.isFinite(overOdds)||!Number.isFinite(underOdds)||
     Math.abs(overOdds)<100||Math.abs(underOdds)<100||Math.abs(overOdds)>100000||Math.abs(underOdds)>100000)
    throw new Error('Enter the actual total and American prices for both over and under (for example -110).');
  if(!Number.isFinite(observedAt)||observedAt>now+5000) throw new Error('Confirm when this market line was observed.');
  const n=projection.totals.length,over=projection.totals.filter(t=>t>line).length/n,
        under=projection.totals.filter(t=>t<line).length/n,push=projection.totals.filter(t=>t===line).length/n;
  const implied=o=>o<0?-o/(100-o):100/(100+o),profit=o=>o<0?100/-o:o/100;
  const blocks=[];
  if(!live)blocks.push('Historical replay or game not in progress.');
  if(!Number.isFinite(receivedAt)||now-receivedAt>90000)blocks.push('Game retrieval is over 90 seconds old.');
  if(!Number.isFinite(lastPlayAt)||now-lastPlayAt>120000||lastPlayAt>now+5000)blocks.push('The feed timestamp is missing, delayed, or invalid.');
  if(now-observedAt>60000)blocks.push('The entered line is over 60 seconds old; reconfirm the current market.');
  if(projection.minutes<3||projection.stats.possessions<5)blocks.push('Too little play in this market period.');
  if(projection.priorAgeDays>30||projection.prior.missing)blocks.push('Team priors are stale or missing; roster changes are not modeled.');
  if(projection.prior.recentGames<5)blocks.push('Both teams need at least five recent games before a research watch is considered.');
  if(projection.scope!=='game'&&projection.remaining<1)blocks.push('The final minute of a quarter needs possession and free-throw strategy that is not modeled.');
  if(projection.period===4&&projection.elapsed>=2760)blocks.push('Late-game fouling and timeout strategy are not modeled.');
  const margin=Math.abs(projection.score.home-projection.score.away);
  if(projection.period>=3&&margin>=20)blocks.push('A large lead can change rotations and tempo.');
  const evOver=over*profit(overOdds)-under,evUnder=under*profit(underOdds)-over;
  const lean=evOver>evUnder?'over':'under',prob=lean==='over'?over:under,price=lean==='over'?overOdds:underOdds;
  const conditional=push<1?prob/(1-push):0,edge=conditional-implied(price);
  const watch=blocks.length===0&&edge>=.05&&Math.max(evOver,evUnder)>0;
  return {over,under,push,evOver,evUnder,breakEvenOver:implied(overOdds),breakEvenUnder:implied(underOdds),
          noVigOver:implied(overOdds)/(implied(overOdds)+implied(underOdds)),lean,edge,blocks,
          status:watch?`Experimental ${lean} watch — not a validated betting edge`:blocks.length?'No signal: data or model limitations':'No clear model/price difference'};
}
