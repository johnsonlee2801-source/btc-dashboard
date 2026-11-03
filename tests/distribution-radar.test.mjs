import test from 'node:test';
import assert from 'node:assert/strict';

const R = await import('../api/distribution-radar.js');
const { okxVolumeToUsd, closedKlines, hourWindow, pairedRatio, resetState } = R;
const handler = R.handleAt;

test('OKX volume units come from the instrument type, not the size of the number', () => {
  // Spot volCcy24h is already USDT, even when small.
  assert.equal(okxVolumeToUsd({ last: '78000', volCcy24h: '5000000' }, 78000, 'spot').quoteVolume, 5_000_000);
  // Swap volCcy24h is BTC, even when large.
  assert.equal(okxVolumeToUsd({ last: '78000', volCcy24h: '20000000' }, 78000, 'swap').quoteVolume, 20_000_000 * 78000);
  assert.equal(okxVolumeToUsd({ last: '78000' }, 78000, 'swap').quoteVolume, null);
});

test('the still-open candle is dropped before the volume comparison', () => {
  const now = 1_800_000_000_000;
  const k = (closeTime) => [0, '1', '1', '1', '1', '1', closeTime, '1'];
  assert.equal(closedKlines([k(now - 1), k(now + 3_000_000)], now).length, 1);
  assert.deepEqual(closedKlines(null, now), []);
});

// ---- handler fixtures: one coherent, current market snapshot ----
const HOUR = 3600000;
const NOW = Date.UTC(2026, 10, 3, 12, 30);
const TOP = Date.UTC(2026, 10, 3, 12); // current, still-open hour

function klines(n = 50, { open = true } = {}) {
  const rows = [];
  const first = TOP - (n - 1) * HOUR;
  for (let i = 0; i < n; i++) {
    const t = first + i * HOUR, p = 78000 + i * 10;
    rows.push([t, String(p), String(p + 50), String(p - 50), String(p + 5), '10', t + HOUR - 1, '1000000', 100, '5', '500000', '0']);
  }
  return open ? rows : rows.slice(0, -1);
}

function payloads(now = NOW) {
  return {
    spotTicker: { symbol: 'BTCUSDT', lastPrice: '78500', quoteVolume: '1000000000', priceChangePercent: '1.2', closeTime: now - 1000 },
    futuresTicker: { symbol: 'BTCUSDT', lastPrice: '78510', quoteVolume: '6000000000', closeTime: now - 1000 },
    okxFuturesTicker: { code: '0', data: [{ instId: 'BTC-USDT-SWAP', last: '78500', volCcy24h: '10000', ts: String(now - 1000) }] },
    bybitFuturesTicker: { retCode: 0, time: now - 1000, result: { list: [{ symbol: 'BTCUSDT', turnover24h: '1000000000' }] } },
    deribitFuturesTicker: { result: { instrument_name: 'BTC-PERPETUAL', last_price: 78500, timestamp: now - 1000, stats: { volume_usd: 500000000 } } },
    okxSpotTicker: { code: '0', data: [{ instId: 'BTC-USDT', last: '78500', volCcy24h: '200000000', ts: String(now - 1000) }] },
    bybitSpotTicker: { retCode: 0, time: now - 1000, result: { list: [{ symbol: 'BTCUSDT', turnover24h: '100000000' }] } },
    premium: { symbol: 'BTCUSDT', markPrice: '78510', indexPrice: '78500', lastFundingRate: '0.0001', time: now - 1000 },
    openInterest: { symbol: 'BTCUSDT', openInterest: '80000', time: now - 1000 },
    spotKlines: klines(),
    futuresKlines: klines(),
    takerLongShort: Array.from({ length: 24 }, (_, i) => ({ buySellRatio: '1.01', timestamp: TOP - (24 - i) * HOUR })),
    coinbaseTicker: { price: '78520', time: new Date(now - 1000).toISOString() },
    coinbaseAdvancedTicker: { trades: [{ price: '78520', time: new Date(now - 1000).toISOString() }] },
    krakenTicker: { error: [], result: { XXBTZUSD: { c: ['78515', '0.1'] } } },
    bitstampTicker: { last: '78510', timestamp: String(Math.floor((now - 1000) / 1000)) },
    geminiTicker: { last: '78510', volume: { timestamp: now - 1000 } },
    krakenUsdtUsd: { error: [], result: { USDTZUSD: { c: ['1.0002', '10'] } } },
  };
}

const KEY_BY_URL = [
  ['api.binance.com/api/v3/ticker', 'spotTicker'], ['fapi/v1/ticker', 'futuresTicker'],
  ['BTC-USDT-SWAP', 'okxFuturesTicker'], ['category=linear', 'bybitFuturesTicker'],
  ['deribit', 'deribitFuturesTicker'], ['instId=BTC-USDT', 'okxSpotTicker'], ['category=spot', 'bybitSpotTicker'],
  ['premiumIndex', 'premium'], ['openInterest', 'openInterest'], ['api/v3/klines', 'spotKlines'],
  ['fapi/v1/klines', 'futuresKlines'], ['takerlongshort', 'takerLongShort'], ['exchange.coinbase', 'coinbaseTicker'],
  ['brokerage', 'coinbaseAdvancedTicker'], ['pair=XBTUSD', 'krakenTicker'], ['bitstamp', 'bitstampTicker'],
  ['gemini', 'geminiTicker'], ['pair=USDTUSD', 'krakenUsdtUsd'],
];
const keyOf = url => KEY_BY_URL.find(([frag]) => url.includes(frag))[1];

// override(key) may return: undefined (normal payload), an object (replacement JSON),
// a Response, or an Error to throw.
async function run(override = () => undefined, now = NOW) {
  resetState();
  const base = payloads(now);
  const calls = [];
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const key = keyOf(String(url));
    calls.push(key);
    const o = override(key, base[key]);
    if (o instanceof Error) throw o;
    if (o instanceof Response) return o;
    return new Response(JSON.stringify(o === undefined ? base[key] : o), { status: 200 });
  };
  try {
    const res = await handler(new Request('https://x/api/distribution-radar'), now);
    return { res, body: await res.json(), calls };
  } finally { globalThis.fetch = orig; }
}
const metric = (body, id) => body.metrics.find(m => m.id === id);

test('a complete current snapshot scores with full coverage and no failed sources', async () => {
  const { body } = await run();
  assert.equal(typeof body.score, 'number');
  assert.equal(body.coverage, 100);
  assert.deepEqual(body.raw.sourcesFailed, []);
  assert.deepEqual(body.raw.ratioExchanges, ['Binance', 'OKX', 'Bybit']);
});

test('complete upstream failure is "数据不足", not a mid-range score', async () => {
  const { res, body } = await run(() => new TypeError('fetch failed'));
  assert.equal(res.status, 200);
  assert.equal(body.score, null);
  assert.equal(body.level.code, 'unavailable');
  assert.equal(body.raw.sourcesFailed.length, 18);
  assert.ok(body.raw.sourcesFailed.every(f => f.error === 'network'));
});

test('losing one side of an exchange removes that exchange from both sides of the ratio', async () => {
  const { body } = await run(k => (k === 'okxSpotTicker' || k === 'bybitSpotTicker' ? new TypeError('x') : undefined));
  assert.deepEqual(body.raw.ratioExchanges, ['Binance']);
  assert.ok(Math.abs(body.raw.globalFuturesSpotRatio - 6) < 1e-9, 'Binance 6e9 / 1e9, not all futures / Binance spot');
});

test('losing one exchange falls back to the fixed Binance universe, not a two-exchange mix', async () => {
  const { body } = await run(k => (k === 'okxSpotTicker' ? new TypeError('x') : undefined));
  assert.deepEqual(body.raw.ratioExchanges, ['Binance']);
  assert.ok(Math.abs(body.raw.globalFuturesSpotRatio - 6) < 1e-9);
  assert.match(metric(body, 'futures_spot_volume_ratio').detail, /Binance 单家口径/);
});

test('payloads missing the numbers they exist for are failures', async () => {
  const { body } = await run((k, d) => {
    if (k === 'openInterest') return { ...d, openInterest: null };
    if (k === 'krakenUsdtUsd') return { error: [], result: {} };
    if (k === 'takerLongShort') return [];
    return undefined;
  });
  const failed = body.raw.sourcesFailed.map(f => f.key).sort();
  assert.deepEqual(failed, ['krakenUsdtUsd', 'openInterest', 'takerLongShort']);
  assert.match(metric(body, 'coinbase_premium').detail, /USDT\/USD/);
});

test('a missing Binance price is blamed on Binance, not on the USDT conversion', async () => {
  const { body } = await run((k, d) => {
    if (k === 'spotTicker' || k === 'premium' || k === 'spotKlines') return new TypeError('x');
    return undefined;
  });
  assert.match(metric(body, 'coinbase_premium').detail, /Binance 现货报价不可用/);
});

test('a taker ratio of 0 is an observation; duplicate hours count once', async () => {
  const rows = Array.from({ length: 24 }, (_, i) => ({ buySellRatio: '0', timestamp: TOP - (24 - i) * HOUR }));
  let { body } = await run(k => (k === 'takerLongShort' ? rows : undefined));
  assert.equal(body.raw.takerBuySellRatio, 0);
  assert.equal(metric(body, 'active_buy_quality').available, true);
  const dup = Array.from({ length: 24 }, () => ({ buySellRatio: '1', timestamp: TOP - HOUR }));
  ({ body } = await run(k => (k === 'takerLongShort' ? dup : undefined)));
  assert.equal(metric(body, 'active_buy_quality').available, false, 'one hour repeated 24 times is not 24 hours');
});

test('a damaged candle outside the 48-hour window does not void the window', async () => {
  const { body } = await run((k, d) => (k === 'spotKlines' || k === 'futuresKlines' ? [null, ...d.slice(1)] : undefined));
  assert.equal(metric(body, 'spot_volume_divergence').available, true);
  assert.equal(metric(body, 'upper_wick_pullback').available, true);
});

test('a candle whose close does not match its open hour is rejected', () => {
  const k = klines(50); k[30] = [...k[30]]; k[30][0] = TOP + 10 * HOUR;
  assert.equal(hourWindow(k, NOW), null);
});

test('concurrent cold requests share one upstream round', async () => {
  resetState();
  const base = payloads();
  let calls = 0;
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => { calls++; await new Promise(r => setTimeout(r, 5)); return new Response(JSON.stringify(base[keyOf(String(url))]), { status: 200 }); };
  try {
    const res = await Promise.all([1, 2, 3].map(() => handler(new Request('https://x/'), NOW)));
    assert.equal(calls, 18);
    assert.ok(res.every(r => r.status === 200));
  } finally { globalThis.fetch = orig; resetState(); }
});

test('an HTTP-date Retry-After sets the back-off', async () => {
  resetState();
  const base = payloads();
  let gemini = 0;
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('gemini')) { gemini++; return new Response('{}', { status: 429, headers: { 'Retry-After': new Date(NOW + 300000).toUTCString() } }); }
    return new Response(JSON.stringify(base[keyOf(String(url))]), { status: 200 });
  };
  try {
    await handler(new Request('https://x/'), NOW);
    await handler(new Request('https://x/'), NOW + 200000);
    assert.equal(gemini, 1, 'still inside the 300 s window');
  } finally { globalThis.fetch = orig; resetState(); }
});

test('stale observations are rejected per source', async () => {
  const { body } = await run((k, d) => (k === 'premium' ? { ...d, time: NOW - 3 * HOUR } : undefined));
  assert.deepEqual(body.raw.sourcesFailed, [{ key: 'premium', error: 'bad_or_stale_payload' }]);
  assert.equal(metric(body, 'funding_heat').available, false);
});

test('klines that stopped hours ago cannot describe the last 48 hours', async () => {
  const { body } = await run(() => undefined, NOW + 5 * HOUR);
  assert.equal(metric(body, 'spot_volume_divergence').available, false);
  assert.equal(metric(body, 'upper_wick_pullback').available, false);
});

test('null funding is missing, not a healthy 0%', async () => {
  const { body } = await run((k, d) => (k === 'premium' ? { ...d, lastFundingRate: null } : undefined));
  assert.equal(body.raw.fundingRatePct, null);
  assert.equal(metric(body, 'funding_heat').available, false);
});

test('exchange error envelopes and wrong instruments are failures', async () => {
  const { body } = await run(k => {
    if (k === 'okxSpotTicker') return { code: '50011', msg: 'Too Many Requests', data: [] };
    if (k === 'bybitSpotTicker') return { retCode: 0, time: NOW, result: { list: [{ symbol: 'ETHUSDT', turnover24h: '9' }] } };
    return undefined;
  });
  const failed = body.raw.sourcesFailed.map(f => f.key).sort();
  assert.deepEqual(failed, ['bybitSpotTicker', 'okxSpotTicker']);
  assert.ok(!body.raw.sourcesOk.includes('okxSpotTicker'));
});

test('upstream HTML never reaches the notes', async () => {
  const { body } = await run(k => (k === 'gemini' || k === 'geminiTicker'
    ? new Response('<svg/onload=alert(1)>', { status: 200 }) : undefined));
  assert.deepEqual(body.raw.sourcesFailed, [{ key: 'geminiTicker', error: 'bad_json' }]);
  assert.ok(!JSON.stringify(body).includes('<svg'));
});

test('a malformed candle makes the window unavailable instead of crashing', async () => {
  const { res, body } = await run((k, d) => (k === 'spotKlines' ? [...d.slice(0, 10), null, ...d.slice(11)] : undefined));
  assert.equal(res.status, 200);
  assert.equal(metric(body, 'spot_volume_divergence').available, false);
  assert.equal(metric(body, 'upper_wick_pullback').available, true, 'futures candles still serve the wick metric');
});

test('an empty futures candle list falls back to spot candles for wicks', async () => {
  const { body } = await run(k => (k === 'futuresKlines' ? [] : undefined));
  assert.equal(metric(body, 'upper_wick_pullback').available, true);
});

test('exactly 48 consecutive closed hours, split 24/24', () => {
  const win = hourWindow(klines(50), NOW);
  assert.equal(win.length, 48);
  assert.equal(win[47].closeTime, TOP - 1, 'the open hour is excluded');
  const gap = klines(50); gap.splice(20, 1);
  assert.equal(hourWindow(gap, NOW), null, 'a missing hour breaks the window');
  assert.equal(hourWindow(klines(48), NOW), null, '47 closed hours are not 48');
});

test('pairedRatio uses all three exchanges or Binance alone, never a partial mix', () => {
  const v = (exchange, q) => ({ exchange, quoteVolume: q, ok: q !== null });
  const fut = [v('Binance', 60), v('OKX', 20), v('Bybit', 10), v('Deribit', 5)];
  const full = pairedRatio(fut, [v('Binance', 10), v('OKX', 4), v('Bybit', 1)]);
  assert.deepEqual(full.exchanges, ['Binance', 'OKX', 'Bybit']);
  assert.equal(full.ratio, 90 / 15, 'Deribit has no spot side and stays out');
  assert.deepEqual(pairedRatio(fut, [v('Binance', 10), v('OKX', 4), v('Bybit', null)]).exchanges, ['Binance']);
  assert.equal(pairedRatio(fut, [v('Binance', null), v('OKX', 4), v('Bybit', 1)]).ratio, null);
});

test('equivalent requests reuse one computation; a 429 host is backed off', async () => {
  resetState();
  const base = payloads();
  let calls = 0;
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls++;
    if (String(url).includes('gemini')) return new Response('{}', { status: 429, headers: { 'Retry-After': '120' } });
    return new Response(JSON.stringify(base[keyOf(String(url))]), { status: 200 });
  };
  try {
    await handler(new Request('https://x/'), NOW);
    assert.equal(calls, 18);
    await handler(new Request('https://x/'), NOW + 1000);
    assert.equal(calls, 18, 'memoised');
    const res = await handler(new Request('https://x/'), NOW + 60000);
    assert.equal(calls, 35, 'gemini skipped during back-off');
    const body = await res.json();
    assert.deepEqual(body.raw.sourcesFailed, [{ key: 'geminiTicker', error: 'backoff' }]);
  } finally { globalThis.fetch = orig; resetState(); }
});

test('the Vercel entry point treats its second argument as context, not a clock', async () => {
  resetState();
  const base = payloads(Date.now());
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => new Response(JSON.stringify(base[keyOf(String(url))]), { status: 200 });
  try {
    const res = await R.default(new Request('https://x/'), { waitUntil() {} });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.ok(Math.abs(Date.parse(body.generatedAt) - Date.now()) < 60000);
  } finally { globalThis.fetch = orig; resetState(); }
});

test('taker rows bunched into minutes are not 24 hours', async () => {
  const rows = Array.from({ length: 24 }, (_, i) => ({ buySellRatio: '1', timestamp: TOP - HOUR + i * 1000 }));
  const { body } = await run(k => (k === 'takerLongShort' ? rows : undefined));
  assert.equal(metric(body, 'active_buy_quality').available, false);
});

test('arrays of nulls and tickers without volume are failed sources', async () => {
  const { body } = await run((k, d) => {
    if (k === 'spotKlines' || k === 'takerLongShort') return [null];
    if (k === 'okxSpotTicker') return { ...d, data: [{ ...d.data[0], volCcy24h: undefined }] };
    return undefined;
  });
  assert.deepEqual(body.raw.sourcesFailed.map(f => f.key).sort(), ['okxSpotTicker', 'spotKlines', 'takerLongShort']);
});

test('quotes compared with each other are at most five minutes old', async () => {
  const { body } = await run((k, d) => (k === 'spotTicker' ? { ...d, closeTime: NOW - 14 * 60000 } : undefined));
  assert.deepEqual(body.raw.sourcesFailed, [{ key: 'spotTicker', error: 'bad_or_stale_payload' }]);
  assert.equal(metric(body, 'coinbase_premium').available, false, 'no premium from a 14-minute-old Binance quote');
});

test('observation times are published', async () => {
  const { body } = await run();
  assert.equal(body.raw.observedAt.spotTicker, new Date(NOW - 1000).toISOString());
  assert.equal(body.raw.latestTakerHour, new Date(TOP - HOUR).toISOString());
});

test('a one-hour Retry-After is honoured, not capped at ten minutes', async () => {
  resetState();
  const base = payloads();
  let gemini = 0;
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('gemini')) { gemini++; return new Response('{}', { status: 429, headers: { 'Retry-After': '3600' } }); }
    return new Response(JSON.stringify(base[keyOf(String(url))]), { status: 200 });
  };
  try {
    await handler(new Request('https://x/'), NOW);
    await handler(new Request('https://x/'), NOW + 700000);
    assert.equal(gemini, 1);
  } finally { globalThis.fetch = orig; resetState(); }
});

test('taker hours with an interior gap are not a full day', async () => {
  const rows = Array.from({ length: 28 }, (_, i) => ({ buySellRatio: '1', timestamp: TOP - (28 - i) * HOUR }))
    .filter((_, i) => i < 20 || i > 23);
  const { body } = await run(k => (k === 'takerLongShort' ? rows : undefined));
  assert.equal(metric(body, 'active_buy_quality').available, false);
});

test('rows that are empty shells are failed sources', async () => {
  const { body } = await run(k => {
    if (k === 'spotKlines') return Array.from({ length: 48 }, () => []);
    if (k === 'takerLongShort') return Array.from({ length: 24 }, () => ({}));
    return undefined;
  });
  assert.deepEqual(body.raw.sourcesFailed.map(f => f.key).sort(), ['spotKlines', 'takerLongShort']);
});

test('a short Retry-After never shortens a longer back-off on the same host', async () => {
  resetState();
  const base = payloads();
  const seen = [];
  const orig = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const key = keyOf(String(url));
    if (String(url).includes('fapi.binance.com')) {
      seen.push(key);
      return new Response('{}', { status: 429, headers: { 'Retry-After': key === 'premium' ? '3600' : '1' } });
    }
    return new Response(JSON.stringify(base[key]), { status: 200 });
  };
  try {
    await handler(new Request('https://x/'), NOW);
    const first = seen.length;
    await handler(new Request('https://x/'), NOW + 60000);
    assert.equal(seen.length, first, 'the one-hour back-off stands');
  } finally { globalThis.fetch = orig; resetState(); }
});

test('a Binance quote and a USD quote minutes apart are not compared', async () => {
  const { body } = await run((k, d) => {
    if (k === 'spotTicker') return { ...d, closeTime: NOW - 4 * 60000 };
    if (k === 'coinbaseTicker') return { ...d, time: new Date(NOW + 90000).toISOString() };
    return undefined;
  });
  assert.equal(metric(body, 'coinbase_premium').available, false);
  assert.match(metric(body, 'coinbase_premium').detail, /相差超过 5 分钟/);
});

test('non-GET methods are refused with an Allow header', async () => {
  const res = await handler(new Request('https://x/', { method: 'POST' }));
  assert.equal(res.status, 405);
  assert.match(res.headers.get('Allow'), /GET/);
});
