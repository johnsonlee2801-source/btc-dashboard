const {test}=require('node:test');
const assert=require('node:assert/strict');
let model;try {model=require('../assets/observatory-model.js');} catch {}
const now=Date.parse('2026-10-29T12:00:00Z');
const m=(value,asOf='2026-10-28')=>({value,asOf,status:'fresh',maxAgeHours:72});
test('model exists',()=>assert.ok(model,'shared model must exist'));
test('dates are revalidated after snapshot generation',()=>{
 assert.equal(model.fresh(m(.3,'2026-10-01'),now),false);
 assert.equal(model.fresh(m(.3,'2026-11-01'),now),false);
 assert.equal(model.fresh(m(.3),now),true);
});
test('null, zero, and false do not collapse together',()=>{
 assert.equal(model.fresh(m(null),now),false);
 assert.equal(model.fresh(m(false),now),false);
 assert.equal(model.signal({key:'rsi',op:'<',threshold:35},{rsi:m(0)},now),true);
});
test('missing factors preserve score interval',()=>{
 const a={metrics:{x:m(0),y:m(null)},groups:[{weight:100,items:[{key:'x',op:'<',threshold:1},{key:'y',op:'<',threshold:1}]}]};
 assert.deepEqual(model.score(a,now),{lower:50,upper:100,available:1,total:2});
});
test('ETH cannot receive a BTC score',()=>assert.equal(model.score({symbol:'ETH',groups:[]},now),null));
test('bull line requires both source levels',()=>{
 assert.equal(model.bullLine({ma200w:m(70000),sth_cost:m(null)},now),null);
 assert.equal(model.bullLine({ma200w:m(70000),sth_cost:m(75000)},now),75000);
});
test('chart windows use the end observation date, not synthetic time',()=>{
 const points=[{date:'2026-01-01',close:1},{date:'2026-10-01',close:2},{date:'2026-10-28',close:3}];
 assert.deepEqual(model.rangeHistory(points,90),points.slice(1));
 assert.deepEqual(model.rangeHistory([],90),[]);
});
test('combination is not green when STH source is stale',()=>{
 const metrics={price:m(70000),sth_cost:m(75000,'2026-10-01'),drawdown90:m(25)};
 assert.equal(model.combination(metrics,now),null);
});
test('known failed condition conclusively prevents combination',()=>{
 const metrics={price:m(80000),sth_cost:m(null),drawdown90:m(10)};
 assert.equal(model.combination(metrics,now),false);
});
test('each exchange needs its own current observation date',()=>{
 assert.equal(typeof model.reserveFresh,'function');
 assert.equal(model.reserveFresh('2026-10-28',{asOf:'2026-10-01',stale:false},now),false);
 assert.equal(model.reserveFresh('2026-10-28',{asOf:'2026-11-01',stale:false},now),false);
 assert.equal(model.reserveFresh('2026-10-28',{asOf:'2026-10-28',stale:false},now),true);
});
test('BTC below-line position is known without 28 days of cost history',()=>{
 assert.equal(typeof model.positionBand,'function');
 const metrics={ma200w:m(70000),sth_cost:m(75000),price:m(60000)};
 assert.equal(model.positionBand(metrics,now),0);
 metrics.price=m(72000);assert.equal(model.positionBand(metrics,now),1);
 metrics.price=m(80000);assert.equal(model.positionBand(metrics,now),null);
 metrics.sth_cost=m(null);assert.equal(model.positionBand(metrics,now),null);
});
test('derived ratio expires if a required denominator expires',()=>{
 const ratio={...m(.6),dependencies:{price:{asOf:'2026-10-28',maxAgeHours:72},ma200w:{asOf:'2026-09-27',maxAgeHours:216}}};
 assert.equal(model.fresh(ratio,now),false);
 assert.equal(model.signal({key:'ratio',op:'<',threshold:1},{ratio},now),null);
});
test('a weekly denominator older than 72h can remain valid within its 216h window',()=>{
 const ratio={...m(.6),dependencies:{price:{asOf:'2026-10-28',maxAgeHours:72},ma200w:{asOf:'2026-10-25',maxAgeHours:216}}};
 assert.equal(model.fresh(ratio,now),true);
});
