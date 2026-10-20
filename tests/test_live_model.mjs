import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {seconds,normalizeSummary,scoreAt,statsThrough,project,compareMarket} from '../nbasim/static/live-model.mjs';
const replay=JSON.parse(fs.readFileSync(new URL('../data/pace_replay.json',import.meta.url),'utf8'));
const game=normalizeSummary(replay.summary),priors=replay.priors;

test('NBA fractional clocks preserve seconds and invalid clocks fail',()=>{
  assert.equal(seconds('55.5'),55.5);assert.equal(seconds('0.0'),0);assert.equal(seconds('11:35'),695);assert.equal(seconds('0:01.2'),1.2);
  for(const bad of ['12:60','-3','NaN','60.1','x'])assert.throws(()=>seconds(bad));
});
test('pregame missing scores and live summary without an official clock are handled explicitly',()=>{
  const raw=structuredClone(replay.summary),c=raw.header.competitions[0];
  c.status={type:{state:'pre'}};raw.plays=[];
  for(const t of c.competitors)delete t.score;
  assert.equal(normalizeSummary(raw).home.score,0);assert.equal(normalizeSummary(raw).elapsed,0);
  const active=structuredClone(replay.summary);active.header.competitions[0].status={type:{state:'in'}};
  active.plays=active.plays.filter(p=>game.plays.find(g=>g.id===p.id).t<=360);
  const g=normalizeSummary(active);assert.equal(g.elapsed,g.plays.at(-1).t);assert.equal(g.clockSource,'last_play');
});
test('tipoff and intermission statuses normalize without pretending play has elapsed',()=>{
  const raw=structuredClone(replay.summary),c=raw.header.competitions[0];raw.plays=[];
  c.status={period:0,type:{state:'in',name:'STATUS_IN_PROGRESS'}};
  assert.equal(normalizeSummary(raw).elapsed,0);
  c.status={period:1,displayClock:'12:00',type:{state:'in',name:'STATUS_IN_PROGRESS'}};
  assert.equal(normalizeSummary(raw).elapsed,0);assert.equal(normalizeSummary(raw).paused,false);
  c.status={period:2,displayClock:'0.0',type:{state:'in',name:'STATUS_HALFTIME'}};
  assert.equal(normalizeSummary(raw).elapsed,1440);assert.equal(normalizeSummary(raw).paused,true);
  c.status={period:2,displayClock:'7:23',type:{state:'in',name:'STATUS_DELAYED',detail:'Delayed'}};
  assert.equal(normalizeSummary(raw).paused,true);
});
test('future participants, plays, and final scores cannot change an earlier projection',()=>{
  const a=project(game,priors,{scope:'q1',elapsed:360});
  const changed=structuredClone(game);changed.home.score=999;changed.away.score=999;
  for(const p of changed.plays)if(p.t>360){p.home=999;p.away=998;p.shot=false;p.type='';}
  assert.deepEqual(project(changed,priors,{scope:'q1',elapsed:360}),a);
});
test('quarter analysis excludes earlier-quarter points',()=>{
  const p=project(game,priors,{scope:'q2',elapsed:1080});
  const atStart=scoreAt(game,720),now=scoreAt(game,1080);
  assert.equal(p.stats.home.points+p.stats.away.points,now.home+now.away-atStart.home-atStart.away);
  assert.ok(p.totals.every(t=>t>=p.stats.home.points+p.stats.away.points));
  assert.throws(()=>project(game,priors,{scope:'q1',elapsed:1080}));
});
test('dead-ball team rebounds do not falsely reduce estimated possessions',()=>{
  const g={home:{id:'1'},away:{id:'2'},plays:[
    {t:10,period:1,team:'1',home:0,away:0,shot:true,attempted:2,scoring:false,type:'jump shot',text:'miss'},
    {t:11,period:1,team:'1',home:0,away:0,shot:false,type:'offensive rebound',text:'Home offensive team rebound'},
    {t:20,period:1,team:'1',home:0,away:0,shot:true,attempted:2,scoring:false,type:'jump shot',text:'miss'},
    {t:21,period:1,team:'1',home:0,away:0,shot:false,type:'offensive rebound',text:'Player offensive rebound'}]};
  const s=statsThrough(g,30);assert.equal(s.home.fga,2);assert.equal(s.home.orb,1);assert.equal(s.home.possessions,1);
});
test('more possessions and more points change distinct model components',()=>{
  const base=project(game,priors,{scope:'q1',elapsed:360});
  const fast=structuredClone(game);
  for(let i=0;i<10;i++)fast.plays.push({t:350+i*.1,seq:9000+i,period:1,team:i%2?game.home.id:game.away.id,home:base.score.home,away:base.score.away,shot:false,type:'turnover',text:'turnover'});
  fast.plays.sort((a,b)=>a.t-b.t||a.seq-b.seq);
  assert.ok(project(fast,priors,{scope:'q1',elapsed:360}).projectedPace>base.projectedPace);
  const hotter=structuredClone(game);for(const p of hotter.plays)if(p.t<=360){p.home+=4;p.away+=4;}
  const r=project(hotter,priors,{scope:'q1',elapsed:360});
  assert.equal(r.projectedPace,base.projectedPace);assert.ok(r.homePPP>base.homePPP);
});
test('market probability, pushes, and payout math use the actual prices',()=>{
  const p=project(game,priors,{scope:'q1',elapsed:360});p.totals=[50,51,52,53];p.priorAgeDays=0;
  const now=Date.now(),context={now,receivedAt:now,lastPlayAt:now,live:true};
  const m=compareMarket(p,{line:51,overOdds:-110,underOdds:100,observedAt:now},context);
  assert.equal(m.over,.5);assert.equal(m.under,.25);assert.equal(m.push,.25);
  assert.equal(m.evOver,.5*100/110-.25);assert.equal(m.breakEvenUnder,.5);
  const higher=compareMarket(p,{line:52.5,overOdds:-110,underOdds:100,observedAt:now},context);
  assert.ok(higher.over<m.over);assert.equal(higher.push,0);
});
test('stale prices, stale feeds, old priors, replays, and late fouling prevent watches',()=>{
  const p=project(game,priors,{scope:'q1',elapsed:360});p.totals=[90,91,92,93];p.priorAgeDays=0;p.prior.recentGames=5;
  const now=Date.now(),market={line:50,overOdds:-110,underOdds:-110,observedAt:now},fresh={now,receivedAt:now,lastPlayAt:now,live:true};
  assert.match(compareMarket(p,market,fresh).status,/Experimental over watch/);
  const cases=[compareMarket(p,{...market,observedAt:now-61000},fresh),
    compareMarket(p,market,{...fresh,lastPlayAt:now-121000}),
    compareMarket(p,market,{...fresh,receivedAt:now-91000}),
    compareMarket({...p,priorAgeDays:90},market,fresh),
    compareMarket({...p,prior:{...p.prior,recentGames:1}},market,fresh),
    compareMarket(p,market,{...fresh,live:false}),
    compareMarket({...p,period:4,elapsed:2800},market,fresh)];
  for(const r of cases){assert.ok(r.blocks.length);assert.match(r.status,/No signal/);}
});
test('replays are deterministic and period completion/active overtime are rejected',()=>{
  const a=project(game,priors,{scope:'game',elapsed:1800});
  assert.deepEqual(project(game,priors,{scope:'game',elapsed:1800}).totals,a.totals);
  assert.throws(()=>project(game,priors,{scope:'q1',elapsed:720}));
  assert.throws(()=>project(game,priors,{scope:'game',elapsed:2900}));
  assert.throws(()=>project(game,priors,{elapsed:0}));
});
