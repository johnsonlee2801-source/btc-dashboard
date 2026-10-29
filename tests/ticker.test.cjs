const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync(new URL('../api/ticker.js',`file://${__filename}`),'utf8');
const load=()=>import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('ticker serves a dated, cached quote even when other venues fail',async()=>{
 const original=global.fetch;
 global.fetch=async url=>{
  if(String(url).includes('okx.com'))return new Response(JSON.stringify({data:[{last:'81000',open24h:'80000'}]}));
  throw Error('venue unavailable');
 };
 try{
  const {default:handler}=await load();
  const res=await handler(new Request('https://test.local/api/ticker?symbol=BTC'));
  const data=await res.json();
  assert.equal(res.status,200);assert.equal(data.price,81000);assert.equal(data.source,'OKX');
  assert.equal(data.change24h,1.25);
  assert.ok(Math.abs(Date.now()-Date.parse(data.asOf))<5000,'Quote must carry actual retrieval time');
  assert.match(res.headers.get('Cache-Control'),/s-maxage=10/);
 }finally{global.fetch=original;}
});
test('invalid symbol is rejected without an upstream request',async()=>{
 const original=global.fetch;let called=false;
 global.fetch=async()=>{called=true;throw Error('must not fetch');};
 try{
  const {default:handler}=await load();
  const res=await handler(new Request('https://test.local/api/ticker?symbol=%3Cscript%3E'));
  assert.equal(res.status,400);assert.equal(called,false);
 }finally{global.fetch=original;}
});
test('all upstream failures stay explicit and are not cached',async()=>{
 const original=global.fetch;global.fetch=async()=>{throw Error('offline');};
 try{
  const {default:handler}=await load();const res=await handler(new Request('https://test.local/api/ticker?symbol=ETH'));
  assert.equal(res.status,502);assert.equal(res.headers.get('Cache-Control'),'no-store');
  const data=await res.json();assert.equal(data.symbol,'ETH');assert.equal(data.price,undefined);
 }finally{global.fetch=original;}
});
