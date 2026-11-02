const test=require('node:test');
const assert=require('node:assert/strict');
const M=require('../assets/observatory-model.js');

const NOW=Date.parse('2026-11-02T12:00:00Z');
const item=(over={})=>({key:'mayer',op:'<',threshold:0.8,value:0.7,asOf:'2026-11-01',maxAgeDays:3,...over});

test('freshness is re-judged against today, not the snapshot time',()=>{
  assert.equal(M.itemFresh(item(),NOW),true);
  assert.equal(M.itemFresh(item({asOf:'2026-10-30'}),NOW),true,'3 days old is still inside a 3-day budget');
  assert.equal(M.itemFresh(item({asOf:'2026-10-29'}),NOW),false);
  assert.equal(M.itemFresh(item({asOf:'2026-11-03'}),NOW),false,'future dates are rejected');
});
test('expired or missing inputs are unknown, never false',()=>{
  assert.equal(M.itemState(item({asOf:'2026-10-20'}),NOW),null);
  assert.equal(M.itemState(item({value:null}),NOW),null);
  assert.equal(M.itemState(item({value:0}),NOW),true,'zero is a real value');
  assert.equal(M.itemState(item({value:0.8}),NOW),false,'strict boundary');
});
test('score keeps an upper bound for unknown items',()=>{
  const groups=[{id:'a',weight:40,items:[item(),item({key:'x',value:null})]},{id:'b',weight:60,items:[item({value:1.2})]}];
  const s=M.score(groups,NOW);
  assert.deepEqual([s.lower,s.upper,s.lit,s.known,s.total],[20,40,1,2,3]);
});
test('verdict bands follow the published thresholds',()=>{
  assert.equal(M.verdict(0).code,'none');assert.equal(M.verdict(19.9).code,'none');
  assert.equal(M.verdict(20).code,'watch');assert.equal(M.verdict(50).code,'building');assert.equal(M.verdict(60).code,'strong');
});
test('combo needs both trigger prices and reports the lower one',()=>{
  const combo={conditions:[{triggerPrice:75800},{triggerPrice:69300}]};
  assert.deepEqual(M.comboState(combo,78000),{each:[false,false],all:false,target:69300});
  assert.equal(M.comboState(combo,70000).each[0],true);
  assert.equal(M.comboState({conditions:[{triggerPrice:null},{triggerPrice:1}]},70000),null);
});
test('move to trigger is relative to the live price',()=>{
  assert.ok(Math.abs(M.move(80,100)+20)<1e-9);
  assert.equal(M.move(80,null),null);
});
test('exchange reserves need their own recent observation',()=>{
  const anchor='2026-11-02T00:00:00Z';
  assert.equal(M.reserveFresh(anchor,{asOf:'2026-11-01T12:00:00Z'},NOW),true);
  assert.equal(M.reserveFresh(anchor,{asOf:'2026-10-30T00:00:00Z'},NOW),false);
});
