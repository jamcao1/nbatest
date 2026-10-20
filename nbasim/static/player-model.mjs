// Descriptive regulation scoring scenarios. No market prices enter this model.
export function estimate(player, minutes=player.minutes, draws=1500) {
  if(player.status!=='available')throw new Error('This player has insufficient scoring history.');
  if(!Number.isFinite(minutes)||minutes<0||minutes>48)throw new Error('Use 0 to 48 regulation minutes.');
  if(!Number.isInteger(draws)||draws<100||draws>10000)throw new Error('Invalid simulation count.');
  const zones=player.zones.map(z=>{
    if(!Number.isFinite(z.rate)||z.rate<0||!Number.isFinite(z.accuracy)||z.accuracy<0||z.accuracy>1)throw new Error('Invalid player scoring rates.');
    const attempts=z.rate*minutes,made=attempts*z.accuracy;
    return {...z,attempts,made,misses:attempts-made,points:made*z.worth};
  });
  let seed=2166136261;
  for(const c of `${player.id}:${minutes.toFixed(2)}`)seed=Math.imul(seed^c.charCodeAt(0),16777619)>>>0;
  const random=()=>{seed+=0x6D2B79F5;let x=seed;x=Math.imul(x^x>>>15,x|1);x^=x+Math.imul(x^x>>>7,x|61);return ((x^x>>>14)>>>0)/4294967296;};
  const normal=()=>Math.sqrt(-2*Math.log(Math.max(1e-12,random())))*Math.cos(2*Math.PI*random());
  const poisson=mean=>{
    if(mean===0)return 0;
    if(mean>30)return Math.max(0,Math.round(mean+Math.sqrt(mean)*normal()));
    const end=Math.exp(-mean);let product=1,count=0;
    do{count++;product*=random();}while(product>end);
    return count-1;
  };
  const totals=[];
  for(let i=0;i<draws;i++){
    const volume=Math.exp(normal()*.18-.18**2/2);
    let points=0;
    for(const z of zones){
      const n=poisson(z.attempts*volume);
      for(let j=0;j<n;j++)if(random()<z.accuracy)points+=z.worth;
    }
    totals.push(points);
  }
  totals.sort((a,b)=>a-b);
  return {zones,minutes,points:zones.reduce((s,z)=>s+z.points,0),
    baskets:zones.filter(z=>z.worth>1).reduce((s,z)=>s+z.made,0),
    misses:zones.filter(z=>z.worth>1).reduce((s,z)=>s+z.misses,0),
    freeThrows:zones.find(z=>z.id==='ft')?.made||0,
    interval80:[totals[Math.floor(draws*.1)],totals[Math.floor(draws*.9)]],totals};
}
