// The real edge handler in api/binance-futures.js, with fetch mocked.
import test from 'node:test';
import assert from 'node:assert/strict';

const mod = await import('../api/binance-futures.js');
const handler = mod.default;
const post = (body, token = 'secret') => new Request('https://x/api/binance-futures', {
  method: 'POST', headers: token ? { 'x-relay-token': token } : {}, body: typeof body === 'string' ? body : JSON.stringify(body),
});

function withEnv(token, fn) {
  return async () => {
    const before = process.env.RELAY_TOKEN;
    if (token === undefined) delete process.env.RELAY_TOKEN; else process.env.RELAY_TOKEN = token;
    try { await fn(); } finally { if (before === undefined) delete process.env.RELAY_TOKEN; else process.env.RELAY_TOKEN = before; }
  };
}
function mockFetch(impl) {
  const real = globalThis.fetch; const calls = [];
  globalThis.fetch = async (url, opts) => { calls.push(url); return impl(url, opts); };
  return { calls, restore: () => { globalThis.fetch = real; } };
}

test('fails closed without a configured token', withEnv(undefined, async () => {
  const res = await handler(post({ requests: [{ path: '/fapi/v1/premiumIndex' }] }));
  assert.equal(res.status, 503);
}));

test('rejects a wrong token and non-POST with Allow', withEnv('secret', async () => {
  assert.equal((await handler(post({ requests: [] }, 'nope'))).status, 401);
  const get = await handler(new Request('https://x'));
  assert.equal(get.status, 405);
  assert.equal(get.headers.get('allow'), 'POST');
}));

test('malformed entries get a per-item 400 instead of crashing the batch', withEnv('secret', async () => {
  const m = mockFetch(async () => new Response('{"ok":1}', { status: 200 }));
  try {
    const res = await handler(post({ requests: [
      { path: { toString: null } }, { path: '/fapi/v1/premiumIndex', params: { symbol: { toString: null } } },
      { path: '/fapi/v1/order', params: { symbol: 'BTCUSDT' } }, { path: '/fapi/v1/premiumIndex', params: { symbol: 'BTC&x=1' } },
      { path: 'constructor' }, { path: '/fapi/v1/premiumIndex', params: { symbol: '币安人生USDT' } }] }));
    const { results } = await res.json();
    assert.deepEqual(results.map(r => r.status), [400, 400, 400, 400, 400, 200]);
    assert.equal(m.calls.length, 1);
    assert.match(m.calls[0], /^https:\/\/fapi\.binance\.com\/fapi\/v1\/premiumIndex\?symbol=/);
  } finally { m.restore(); }
}));

test('a 429 stops the rest of the batch and carries Retry-After', withEnv('secret', async () => {
  const m = mockFetch(async () => new Response('', { status: 429, headers: { 'retry-after': '60' } }));
  try {
    const reqs = Array.from({ length: 40 }, () => ({ path: '/fapi/v1/premiumIndex', params: { symbol: 'BTCUSDT' } }));
    const { results } = await (await handler(post({ requests: reqs }))).json();
    assert.ok(m.calls.length <= 8, `dispatched ${m.calls.length} after throttling`);
    assert.ok(results.every(r => r.status === 429));
    assert.equal(results.at(-1).retryAfter, 60);
  } finally { m.restore(); }
}));

test('proof-of-reserves path goes to www.binance.com', withEnv('secret', async () => {
  const m = mockFetch(async () => new Response('{"code":"000000","data":[]}', { status: 200 }));
  try {
    await handler(post({ requests: [{ path: '/bapi/apex/v1/public/apex/market/por/address' }] }));
    assert.equal(m.calls[0], 'https://www.binance.com/bapi/apex/v1/public/apex/market/por/address');
  } finally { m.restore(); }
}));
