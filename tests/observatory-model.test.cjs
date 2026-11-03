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
const combo=(sthDay='2026-11-01',ddDay='2026-11-01')=>({conditions:[{id:'sth',triggerPrice:75800,asOf:sthDay},{id:'drawdown',triggerPrice:69296,asOf:ddDay}]});
test('combo needs both fresh trigger prices and reports the lower one',()=>{
  assert.deepEqual(M.comboState(combo(),78000,NOW),{each:[false,false],all:false,target:69296});
  assert.equal(M.comboState(combo(),70000,NOW).each[0],true);
  assert.equal(M.comboState({conditions:[{id:'sth',triggerPrice:null,asOf:'2026-11-01'},{id:'drawdown',triggerPrice:1,asOf:'2026-11-01'}]},70000,NOW),null);
  assert.equal(M.comboState({conditions:[]},70000,NOW),null,'no conditions is not "all met"');
});
test('an expired snapshot never shows the combo as lit',()=>{
  assert.equal(M.comboState(combo('2026-10-20','2026-10-20'),60000,NOW),null);
  assert.equal(M.comboState(combo('2026-11-01','2026-10-29'),60000,NOW),null,'the 90-day high lives 3 days');
});
test('the drawdown condition is inclusive at its trigger price, STH cost strict',()=>{
  assert.deepEqual(M.comboState(combo(),69296,NOW).each,[true,true]);
  assert.equal(M.comboState({conditions:[{id:'sth',triggerPrice:70000,asOf:'2026-11-01'},{id:'drawdown',triggerPrice:69296,asOf:'2026-11-01'}]},70000,NOW).each[0],false);
});
test('malformed rules and dates are unknown, never a verdict',()=>{
  assert.equal(M.itemState(item({op:'toString'}),NOW),null);
  assert.equal(M.itemState(item({op:'__defineGetter__'}),NOW),null);
  assert.equal(M.itemState(item({threshold:null}),NOW),null);
  assert.equal(M.itemState(item({threshold:undefined}),NOW),null);
  assert.equal(M.itemFresh(item({asOf:'2026-02-30'}),Date.parse('2026-03-02T12:00:00Z')),false);
  assert.equal(M.itemFresh(item({asOf:20261101}),NOW),false);
});
test('move to trigger is relative to the live price',()=>{
  assert.ok(Math.abs(M.move(80,100)+20)<1e-9);
  assert.equal(M.move(80,null),null);
});
test('exchange reserves need their own recent observation',()=>{
  const anchor='2026-11-02T00:00:00Z';
  assert.equal(M.reserveFresh(anchor,{asOf:'2026-11-01T12:00:00Z'},NOW),true);
  assert.equal(M.reserveFresh(anchor,{asOf:'2026-10-30T00:00:00Z'},NOW),false);
  assert.equal(M.reserveFresh('2026-11-03T00:00:00Z',{asOf:'2026-11-02T00:00:00Z'},NOW),false,'future anchor');
});
