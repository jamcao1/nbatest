// Run with a dated file of {summary, priors} pairs prepared before inspecting results.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {normalizeSummary,project,scoreAt} from '../nbasim/static/live-model.mjs';
const cases=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),groups=new Map(),excluded=[],accepted=[];
for(const item of cases){
  let game;
  try{
    game=normalizeSummary(item.summary);
    const final=game.plays.at(-1);
    if(final.home!==game.home.score||final.away!==game.away.score)throw new Error('Final score does not reconcile with play-by-play.');
    const c=item.summary.header.competitions[0].competitors;
    for(let q=1;q<=4;q++){
      const start=scoreAt(game,(q-1)*720),end=scoreAt(game,q*720);
      const actual=c.reduce((sum,t)=>sum+Number(t.linescores[q-1].value??t.linescores[q-1].displayValue),0);
      if(end.home+end.away-start.home-start.away!==actual)throw new Error('Quarter scores do not reconcile.');
    }
  }catch(error){excluded.push({id:item.summary.header.id,reason:error.message});continue;}
  accepted.push(game);
  const points=(a,b)=>b.home+b.away-a.home-a.away;
  for(const scope of ['q1','q2','q3','q4','game']){
    const checkpoints=scope==='game'?[6,18,30,42]:[3,6,9];
    for(const minutes of checkpoints){
      const start=scope==='game'?0:(Number(scope[1])-1)*720,elapsed=start+minutes*60;
      const r=project(game,item.priors,{scope,elapsed,draws:2000});
      const actual=scope==='game'?game.home.score+game.away.score:points(scoreAt(game,start),scoreAt(game,start+720));
      const current=r.stats.home.points+r.stats.away.points, targetMinutes=scope==='game'?48:12;
      const prior=current+r.remaining*r.prior.pace/48*(r.prior.homePPP+r.prior.awayPPP);
      const extrapolation=current/r.minutes*targetMinutes;
      const label=scope==='game'?`Full game · ${minutes} min elapsed`:`Quarters · ${minutes} min elapsed`;
      if(!groups.has(label))groups.set(label,[]);
      groups.get(label).push({model:Math.abs(r.mean-actual),prior:Math.abs(prior-actual),extrapolation:Math.abs(extrapolation-actual),covered:actual>=r.interval80[0]&&actual<=r.interval80[1]});
    }
  }
}
if(accepted.length<cases.length*.9)throw new Error(`Too many incomplete replays: ${accepted.length}/${cases.length}`);
const mean=xs=>xs.reduce((a,b)=>a+b,0)/xs.length;
const easternDate=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
const result={model_version:'live-pace-v1',archive_sha256:createHash('sha256').update(fs.readFileSync(new URL('../data/pace_history_2026.json.gz',import.meta.url))).digest('hex'),games:accepted.length,requested_games:cases.length,
  start:easternDate(accepted[0].date),end:easternDate(accepted.at(-1).date),excluded,
  metrics:[...groups].map(([label,rows])=>({label,forecasts:rows.length,model_mae:mean(rows.map(r=>r.model)),prior_mae:mean(rows.map(r=>r.prior)),extrapolation_mae:mean(rows.map(r=>r.extrapolation)),coverage80:mean(rows.map(r=>Number(r.covered)))})),
  note:'Development replay, not an independent prospective test. Errors are mean absolute points. Quarter rows pool all four quarters; repeated checkpoints are correlated. Historical-rate baseline adds expected remaining points to the observed score. Public logs may contain later corrections. No archived in-play odds were available, so betting returns, actual market edges, and live feed latency were not validated.'};
fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
