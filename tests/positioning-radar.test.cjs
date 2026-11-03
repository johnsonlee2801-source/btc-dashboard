const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const file=path.join(__dirname,'../assets/positioning-radar-model.js');
const M=fs.existsSync(file)?require(file):null;
const NOW=1793448000000,T=NOW-3600000;
const H=3600000;
function concentrationSnapshot(history,address='0xabc'){
  const conc=(value,asOf)=>({value,asOf,maxAgeHours:72});
  return {universeAsOf:NOW-60000,universeTotal:1,history,
    rows:[{symbol:'XUSDT',baseAsset:'X',address,metrics:{concentration:conc(96,NOW-H)}}]};
}
test('concentration compares the observation nearest 24h within 18-30h on the same contract',()=>{
  const h=(gapH,value,address='0xabc')=>({asOf:NOW-H-gapH*H,rows:[{symbol:'XUSDT',address,metrics:{concentration:{value,asOf:NOW-H-gapH*H,maxAgeHours:72}}}]});
  let a=M.analyze(concentrationSnapshot([h(17,90),h(31,91)]),NOW);
  assert.equal(a.changes.compared,0,'outside the 18-30h window');
  a=M.analyze(concentrationSnapshot([h(19,90),h(25,94)]),NOW);
  assert.equal(a.rows[0].values.concentrationDelta,2,'nearest to 24h wins');
  a=M.analyze(concentrationSnapshot([h(24,90,'0xother')]),NOW);
  assert.equal(a.changes.compared,0,'a different contract is not yesterday');
});
test('malformed history is ignored instead of crashing',()=>{
  for(const history of [{},[null],[{rows:null}],[{rows:[null]}]])
    assert.doesNotThrow(()=>M.analyze(concentrationSnapshot(history),NOW));
});
test('funding interval needs the same settlement as the rate',()=>{
  const snap={universeAsOf:NOW-60000,rows:[{symbol:'YUSDT',metrics:{fundingRate:{value:0.01,asOf:T,maxAgeHours:11},fundingHours:{value:8,asOf:T-8*H,maxAgeHours:11}}}]};
  assert.equal(M.analyze(snap,NOW).rows[0].values.fundingHours,null);
});
const m=(value,asOf=T)=>({value,asOf,source:'test fixture',url:'https://example.com/data'});
function row(symbol='BTCUSDT',top=.7,all=.3,oi=10000000){return {symbol,baseAsset:symbol,makers:[],metrics:{topLong:m(top),accountLong:m(all),oiUsd:m(oi),topDelta:{...m(10),fromAsOf:T-86400000},accountDelta:{...m(-10),fromAsOf:T-86400000}}};}
function snapshot(rows){return {schemaVersion:1,generatedAt:NOW,universeAsOf:NOW,universeTotal:rows.length,rows,history:[],errors:[]};}
function analyze(rows){assert.ok(M,'ranking model is not implemented');return M.analyze(snapshot(rows),NOW);}

test('opposite sides ranked by gap, not price or OI',()=>{
 const a=analyze([row('A',.6,.4),row('B',.9,.3)]);
 assert.deepEqual(a.groups.divergence.map(r=>r.symbol),['B','A']);
 assert.ok(Math.abs(a.groups.divergence[0].gap-60)<1e-9);
});
test('50% is neutral; OI10m included, below excluded',()=>{
 assert.deepEqual(analyze([row('A',.5,.4),row('B',.6,.4,9999999),row('C')]).groups.divergence.map(r=>r.symbol),['C']);
});
test('crowded sides are all-account shares and include OI3m',()=>{
 const a=analyze([row('A',.9,.49,3000000),row('B',.1,.8,3000000),row('C',.1,.9,2999999)]);
 assert.deepEqual(a.groups.crowdedLong.map(r=>r.symbol),['B']);
 assert.deepEqual(a.groups.crowdedShort.map(r=>r.symbol),['A']);
});
test('different hourly windows cannot become a disagreement',()=>{
 const r=row();r.metrics.accountLong.asOf-=3600000;
 assert.equal(analyze([r]).groups.divergence.length,0);
});
test('stale and future values cannot rank',()=>{
 for(const stamp of [NOW-4*3600000,NOW+1]){
  const r=row();r.metrics.topLong.asOf=stamp;
  assert.equal(analyze([r]).groups.divergence.length,0);
 }
});
test('unknown concentration has unknown count, not zero coins',()=>{
 const a=analyze([row()]);assert.equal(a.counts.high,null);assert.equal(a.coverage.concentration,0);
});
test('90 and 95 are inclusive lower boundaries',()=>{
 const rows=[89.999,90,94.999,95].map((v,i)=>{const r=row(String(i));r.metrics.concentration=m(v);return r;});
 const a=analyze(rows);
 assert.deepEqual(a.groups.high.map(r=>r.symbol),['3']);
 assert.equal(a.groups.watch.length,2);
});
test('unknown, NaN, boolean and out of range ratio fail validation',()=>{
 for(const v of [null,NaN,true,'0.7',1.2,-.1]){
  const r=row();r.metrics.topLong=m(v);
  assert.equal(analyze([r]).groups.divergence.length,0);
 }
});
test('zero account share is a real short observation',()=>{
 assert.equal(analyze([row('A',.7,0)]).groups.crowdedShort.length,1);
});
test('duplicate symbols cannot inflate coverage',()=>{
 assert.equal(analyze([row(),row()]).rows.length,1);
});
test('missing history never manufactures entrants or exits',()=>{
 const r=row();r.metrics.concentration=m(96);
 const a=analyze([r]);assert.equal(a.changes.entered,null);assert.equal(a.changes.exited,null);
});
test('only verified same-asset exact-day concentration crossings count',()=>{
 const r=row('A');r.metrics.concentration=m(96);const s=snapshot([r]);
 s.history=[{asOf:T-86400000,rows:[{symbol:'A',metrics:{concentration:m(94,T-86400000)}}]}];
 assert.ok(M);const a=M.analyze(s,NOW);
 assert.equal(a.changes.entered,1);assert.equal(a.changes.exited,0);assert.equal(a.changes.up[0].delta,2);
 assert.equal(a.rows[0].values.concentrationDelta,2);
 r.metrics.concentration.asOf=NOW-49*3600000;
 assert.equal(M.analyze(s,NOW).changes.exited,null);
});
test('a delta with a different endpoint cannot attach to current position',()=>{
 const r=row();r.metrics.topDelta.asOf=T-3600000;
 assert.equal(analyze([r]).rows[0].values.topDelta,null);
});
test('search and risk filters operate on actual observations',()=>{
 const a=analyze([row('BTCUSDT'),row('ETHUSDT')]);
 assert.ok(M);assert.equal(M.select(a.rows,'btc','all').length,1);
 assert.equal(M.select(a.rows,'','risk').length,2);
});
test('source links allow https only and never embedded credentials',()=>{
 assert.ok(M);assert.equal(M.safeUrl('javascript:alert(1)'),null);
 assert.equal(M.safeUrl('https://user:pass@example.com'),null);
 assert.equal(M.safeUrl('https://example.com/source'),'https://example.com/source');
});
test('stale universe cannot present current ranks',()=>{
 assert.ok(M);const s=snapshot([row()]);s.universeAsOf=NOW-4*3600000;
 assert.equal(M.analyze(s,NOW).groups.divergence.length,0);
});
