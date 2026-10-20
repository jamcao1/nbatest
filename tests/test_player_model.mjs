import test from 'node:test';
import assert from 'node:assert/strict';
import {estimate} from '../nbasim/static/player-model.mjs';
const player={id:'fixture',minutes:32,status:'available',zones:[
  {id:'rim',worth:2,rate:.2,accuracy:.65,historical_made:13,historical_attempts:20},
  {id:'arc3',worth:3,rate:.15,accuracy:.38,historical_made:38,historical_attempts:100},
  {id:'ft',worth:1,rate:.12,accuracy:.8,historical_made:80,historical_attempts:100}
]};
test('expected points reconcile with made twos, threes and free throws',()=>{
  const p=estimate(player);
  assert.equal(p.points,p.zones.reduce((s,z)=>s+z.worth*z.made,0));
  for(const z of p.zones)assert.ok(Math.abs(z.made+z.misses-z.attempts)<1e-10);
  assert.equal(p.baskets,p.zones[0].made+p.zones[1].made);
  assert.equal(p.freeThrows,p.zones[2].made);
  assert.ok(p.totals.every(x=>Number.isInteger(x)&&x>=0));
});
test('minutes scenarios change volume while retaining shooting probabilities',()=>{
  const full=estimate(player,32),half=estimate(player,16);
  assert.equal(half.points,full.points/2);
  assert.equal(half.baskets,full.baskets/2);
  assert.deepEqual(half.zones.map(z=>z.accuracy),full.zones.map(z=>z.accuracy));
  const none=estimate(player,0);assert.equal(none.points,0);assert.deepEqual(none.interval80,[0,0]);
});
test('simulations are reproducible and refuse missing profiles and invalid minutes',()=>{
  assert.deepEqual(estimate(player),estimate(player));
  assert.throws(()=>estimate({...player,status:'insufficient_history'}));
  for(const minutes of [-1,49,NaN,Infinity])assert.throws(()=>estimate(player,minutes));
});
test('shared shot-volume uncertainty produces a nonzero interval',()=>{
  const p=estimate(player);
  assert.ok(p.interval80[0]<p.points&&p.interval80[1]>p.points);
  assert.ok(Math.abs(p.totals.reduce((s,x)=>s+x,0)/p.totals.length-p.points)<1);
});
