/**
 * Vercel Edge Function: /api/distribution-radar
 * BTC 派发雷达：用公开市场微结构数据观察“上涨但承接变差 / 合约推动”风险。
 * 仅作市场结构观察，不构成投资建议。
 */

export const config = { runtime: 'edge', regions: ['sin1'] };

const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Access-Control-Allow-Origin': '*',
  'Cache-Control': 's-maxage=45, stale-while-revalidate=120',
};

const ENDPOINTS = {
  spotTicker: 'https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT',
  futuresTicker: 'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT',
  okxFuturesTicker: 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP',
  bybitFuturesTicker: 'https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT',
  deribitFuturesTicker: 'https://www.deribit.com/api/v2/public/ticker?instrument_name=BTC-PERPETUAL',
  okxSpotTicker: 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT',
  bybitSpotTicker: 'https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT',
  premium: 'https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT',
  openInterest: 'https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT',
  spotKlines: 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=50',
  futuresKlines: 'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=50',
  takerLongShort: 'https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=24',
  coinbaseTicker: 'https://api.exchange.coinbase.com/products/BTC-USD/ticker',
  coinbaseAdvancedTicker: 'https://api.coinbase.com/api/v3/brokerage/market/products/BTC-USD/ticker',
  krakenTicker: 'https://api.kraken.com/0/public/Ticker?pair=XBTUSD',
  bitstampTicker: 'https://www.bitstamp.net/api/v2/ticker/btcusd/',
  geminiTicker: 'https://api.gemini.com/v1/pubticker/btcusd',
  krakenUsdtUsd: 'https://api.kraken.com/0/public/Ticker?pair=USDTUSD',
};

// Only real numbers and numeric strings count: Number(null), Number('') and Number(false)
// are all 0, which would turn a missing funding rate into a "healthy" 0%.
function num(v, fallback = null) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : fallback;
  if (typeof v !== 'string' || !v.trim()) return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function clamp(v, min = 0, max = 100) {
  return Math.max(min, Math.min(max, v));
}

function pct(v) {
  return Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '--';
}

function usd(v, digits = 0) {
  if (!Number.isFinite(v)) return '--';
  return `$${v.toLocaleString('en-US', { maximumFractionDigits: digits })}`;
}

const HOUR = 3600000;
// Quotes compared with each other (Binance vs USD venues) must be near-simultaneous: each
// has to be at most five minutes old, so any two are within five minutes of one another.
const TICKER_MAX_AGE_MS = 5 * 60000;
const FUTURE_SKEW_MS = 2 * 60000;

function recent(ms, now, maxAge = TICKER_MAX_AGE_MS) {
  return Number.isFinite(ms) && ms <= now + FUTURE_SKEW_MS && now - ms <= maxAge;
}

// Each source must prove it answered the question asked: the right instrument, a success
// envelope, and a recent observation. HTTP 200 alone is not success.
const binanceTicker = (d, now) => d?.symbol === 'BTCUSDT' && recent(num(d.closeTime), now)
  && positiveNum(d.lastPrice) !== null && positiveNum(d.quoteVolume) !== null;
const okxTicker = instId => (d, now) => d?.code === '0' && d.data?.[0]?.instId === instId && recent(num(d.data[0].ts), now)
  && positiveNum(d.data[0].last) !== null && positiveNum(d.data[0].volCcy24h) !== null;
const bybitOk = (d, now) => d?.retCode === 0 && positiveNum(bybitTicker(d)?.turnover24h) !== null && recent(num(d.time), now);
// Kraken's public Ticker carries no timestamp; it is a live snapshot and is accepted as such.
// It must still contain the pair that was asked for with a positive last price.
const krakenOk = pairs => d => Array.isArray(d?.error) && d.error.length === 0
  && pairs.some(p => positiveNum(d.result?.[p]?.c?.[0]) !== null);
// Shape only for the rows that can enter the window (48 closed + the open hour).
const klineRows = d => Array.isArray(d) && d.length >= 48 && d.slice(-49).every(r => Array.isArray(r) && r.length >= 8);
const takerRowsOk = d => Array.isArray(d) && d.length >= 24
  && d.every(r => r !== null && typeof r === 'object' && num(r.timestamp) !== null && num(r.buySellRatio) !== null);
const VALIDATORS = {
  spotTicker: binanceTicker,
  futuresTicker: binanceTicker,
  okxFuturesTicker: okxTicker('BTC-USDT-SWAP'),
  bybitFuturesTicker: bybitOk,
  deribitFuturesTicker: (d, now) => d?.result?.instrument_name === 'BTC-PERPETUAL' && recent(num(d.result.timestamp), now)
    && (positiveNum(d.result.stats?.volume_usd) !== null || positiveNum(d.result.stats?.volume) !== null),
  okxSpotTicker: okxTicker('BTC-USDT'),
  bybitSpotTicker: bybitOk,
  premium: (d, now) => d?.symbol === 'BTCUSDT' && recent(num(d.time), now)
    && positiveNum(d.markPrice) !== null && num(d.lastFundingRate) !== null,
  openInterest: (d, now) => d?.symbol === 'BTCUSDT' && recent(num(d.time), now) && positiveNum(d.openInterest) !== null,
  spotKlines: klineRows,
  futuresKlines: klineRows,
  takerLongShort: takerRowsOk,
  coinbaseTicker: (d, now) => positiveNum(d?.price) !== null && recent(Date.parse(d.time), now),
  coinbaseAdvancedTicker: (d, now) => positiveNum(d?.trades?.[0]?.price) !== null && recent(Date.parse(d.trades[0].time), now),
  krakenTicker: krakenOk(['XXBTZUSD', 'XBTUSD']),
  bitstampTicker: (d, now) => positiveNum(d?.last) !== null && recent(num(d.timestamp) * 1000, now),
  geminiTicker: (d, now) => positiveNum(d?.last) !== null && recent(num(d.volume?.timestamp), now),
  krakenUsdtUsd: krakenOk(['USDTZUSD', 'USDTUSD']),
};

// Observation time of each timestamped source, published so a reader can see what was compared.
const OBSERVED = {
  spotTicker: d => num(d.closeTime), futuresTicker: d => num(d.closeTime),
  okxFuturesTicker: d => num(d.data[0].ts), okxSpotTicker: d => num(d.data[0].ts),
  bybitFuturesTicker: d => num(d.time), bybitSpotTicker: d => num(d.time),
  deribitFuturesTicker: d => num(d.result.timestamp), premium: d => num(d.time), openInterest: d => num(d.time),
  coinbaseTicker: d => Date.parse(d.time), coinbaseAdvancedTicker: d => Date.parse(d.trades[0].time),
  bitstampTicker: d => num(d.timestamp) * 1000, geminiTicker: d => num(d.volume.timestamp),
};

function parseFiatSpotTicker(data) {
  const sources = [
    {
      key: 'coinbaseTicker',
      source: 'Coinbase',
      price: positiveNum(data.coinbaseTicker?.price),
    },
    {
      key: 'coinbaseAdvancedTicker',
      source: 'Coinbase',
      price: positiveNum(data.coinbaseAdvancedTicker?.trades?.[0]?.price),
    },
    {
      key: 'krakenTicker',
      source: 'Kraken',
      price: positiveNum(data.krakenTicker?.result?.XXBTZUSD?.c?.[0] ?? data.krakenTicker?.result?.XBTUSD?.c?.[0]),
    },
    {
      key: 'bitstampTicker',
      source: 'Bitstamp',
      price: positiveNum(data.bitstampTicker?.last),
    },
    {
      key: 'geminiTicker',
      source: 'Gemini',
      price: positiveNum(data.geminiTicker?.last),
    },
  ];

  return sources.find(s => s.price !== null) || { key: null, source: null, price: null };
}

function positiveNum(v) {
  const n = num(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

// OKX v5 /market/ticker: for SPOT volCcy24h is quote currency (USDT); for SWAP it is the
// base currency (BTC) and must be multiplied by price. No size heuristic: a guessed unit
// can be off by the BTC price (~10^5x).
export function okxVolumeToUsd(ticker, fallbackPrice, kind) {
  const last = positiveNum(ticker?.last) || positiveNum(fallbackPrice);
  const volCcy24h = positiveNum(ticker?.volCcy24h);
  if (volCcy24h && kind === 'spot') return { quoteVolume: volCcy24h, note: 'OKX spot volCcy24h (USDT).' };
  if (volCcy24h && kind === 'swap' && last) return { quoteVolume: volCcy24h * last, note: 'OKX swap volCcy24h (BTC) × last.' };
  return { quoteVolume: null, note: 'OKX volume fields unavailable or unit could not be converted.' };
}

function venue(exchange, venueName, quoteVolume, ok = true, note = undefined) {
  const qv = positiveNum(quoteVolume);
  return { exchange, venue: venueName, quoteVolume: qv, ok: Boolean(ok && qv), ...(note ? { note } : {}) };
}

function venueFailed(exchange, venueName, note) {
  return { exchange, venue: venueName, quoteVolume: null, ok: false, note };
}

// Exact instrument only: list[0] could be another coin's volume.
function bybitTicker(data, expectedSymbol = 'BTCUSDT') {
  const list = data?.result?.list;
  if (!Array.isArray(list)) return null;
  return list.find(item => item?.symbol === expectedSymbol) || null;
}

// The ratio is computed on one of two FIXED universes, never on whatever happened to load:
// all three exchanges with both sides, or else Binance alone. A partial set (say Binance+OKX)
// is a different market mix, and its ratio moves without any change in the market.
export const RATIO_UNIVERSE = ['Binance', 'OKX', 'Bybit'];
export function pairedRatio(futuresVenues, spotVenues) {
  const spot = new Map(spotVenues.filter(v => v.ok).map(v => [v.exchange, v.quoteVolume]));
  const both = futuresVenues.filter(v => v.ok && spot.has(v.exchange) && RATIO_UNIVERSE.includes(v.exchange));
  const pairs = both.length === RATIO_UNIVERSE.length ? both : both.filter(v => v.exchange === 'Binance');
  if (!pairs.length) return { ratio: null, exchanges: [], futures: null, spot: null };
  const futures = pairs.reduce((s, v) => s + v.quoteVolume, 0);
  const spotSum = pairs.reduce((s, v) => s + spot.get(v.exchange), 0);
  return { ratio: futures / spotSum, exchanges: pairs.map(v => v.exchange), futures, spot: spotSum };
}

function buildVolumeAggregation(data, spotPrice, futuresQuoteVolume, spotQuoteVolume) {
  const futuresVenues = [];
  const spotVenues = [];

  futuresVenues.push(venue('Binance', 'Binance BTCUSDT perpetual', futuresQuoteVolume));

  const okxFutures = data.okxFuturesTicker?.data?.[0];
  if (okxFutures) {
    const parsed = okxVolumeToUsd(okxFutures, spotPrice, 'swap');
    futuresVenues.push(venue('OKX', 'OKX BTC-USDT-SWAP', parsed.quoteVolume, true, parsed.note));
  } else {
    futuresVenues.push(venueFailed('OKX', 'OKX BTC-USDT-SWAP', 'ticker unavailable'));
  }

  const bybitFutures = bybitTicker(data.bybitFuturesTicker);
  futuresVenues.push(bybitFutures
    ? venue('Bybit', 'Bybit linear BTCUSDT', positiveNum(bybitFutures.turnover24h), true, 'Bybit turnover24h parsed as quote/USDT notional.')
    : venueFailed('Bybit', 'Bybit linear BTCUSDT', 'ticker unavailable'));

  const deribit = data.deribitFuturesTicker?.result;
  const deribitPrice = positiveNum(deribit?.last_price) || positiveNum(spotPrice);
  const deribitVolumeUsd = positiveNum(deribit?.stats?.volume_usd)
    || (positiveNum(deribit?.stats?.volume) && deribitPrice ? positiveNum(deribit.stats.volume) * deribitPrice : null);
  futuresVenues.push(deribit
    ? venue('Deribit', 'Deribit BTC-PERPETUAL', deribitVolumeUsd, true, deribit?.stats?.volume_usd ? 'Deribit stats.volume_usd parsed as USD notional.' : 'Deribit volume fallback × price; approximate USD notional.')
    : venueFailed('Deribit', 'Deribit BTC-PERPETUAL', 'ticker unavailable'));

  spotVenues.push(venue('Binance', 'Binance BTCUSDT spot', spotQuoteVolume));

  const okxSpot = data.okxSpotTicker?.data?.[0];
  if (okxSpot) {
    const parsed = okxVolumeToUsd(okxSpot, spotPrice, 'spot');
    spotVenues.push(venue('OKX', 'OKX BTC-USDT spot', parsed.quoteVolume, true, parsed.note));
  } else {
    spotVenues.push(venueFailed('OKX', 'OKX BTC-USDT spot', 'ticker unavailable'));
  }

  const bybitSpot = bybitTicker(data.bybitSpotTicker);
  spotVenues.push(bybitSpot
    ? venue('Bybit', 'Bybit spot BTCUSDT', positiveNum(bybitSpot.turnover24h), true, 'Bybit turnover24h parsed as quote/USDT notional.')
    : venueFailed('Bybit', 'Bybit spot BTCUSDT', 'ticker unavailable'));

  const globalFuturesQuoteVolume = futuresVenues.reduce((sum, v) => sum + (v.ok ? v.quoteVolume : 0), 0) || null;
  const globalSpotQuoteVolume = spotVenues.reduce((sum, v) => sum + (v.ok ? v.quoteVolume : 0), 0) || null;
  const paired = pairedRatio(futuresVenues, spotVenues);

  return { futuresVenues, spotVenues, globalFuturesQuoteVolume, globalSpotQuoteVolume, paired };
}

// Per-isolate protection: equivalent requests within MEMO_MS reuse one computation, and a
// host that answered 418/429 is not called again until its back-off expires.
const MEMO_MS = 30000;
const backoff = new Map();
let memo = null;
let inflight = null;
export function resetState() { backoff.clear(); memo = null; inflight = null; }

// Retry-After is either delta-seconds or an HTTP date.
function retryAfterSeconds(value, now) {
  const secs = num(value);
  if (secs !== null) return secs;
  const at = Date.parse(value || '');
  return Number.isFinite(at) ? (at - now) / 1000 : 60;
}

// Errors are reduced to fixed codes: upstream bodies (possibly HTML) never reach the page.
async function safeFetchJson(key, url, now, timeout = 6500) {
  const host = new URL(url).host;
  if ((backoff.get(host) || 0) > now) return { key, ok: false, error: 'backoff' };
  let res;
  try {
    res = await fetch(url, {
      headers: { 'Accept': 'application/json', 'User-Agent': 'btc-distribution-radar/1.0' },
      signal: AbortSignal.timeout(timeout),
    });
  } catch (err) {
    return { key, ok: false, error: err?.name === 'TimeoutError' ? 'timeout' : 'network' };
  }
  if (res.status === 418 || res.status === 429) {
    const wait = Math.min(Math.max(retryAfterSeconds(res.headers.get('retry-after'), now), 1), 3600);
    // Never shorten a back-off another response already asked for.
    backoff.set(host, Math.max(backoff.get(host) || 0, now + wait * 1000));
  }
  if (!res.ok) return { key, ok: false, error: `http_${res.status}` };
  let data;
  try { data = await res.json(); } catch { return { key, ok: false, error: 'bad_json' }; }
  const valid = VALIDATORS[key] ? VALIDATORS[key](data, now) : true;
  return valid ? { key, ok: true, data } : { key, ok: false, error: 'bad_or_stale_payload' };
}

// A complete row with a coherent OHLC shape and a one-hour span, or null. Missing volume is not zero volume.
function parseKline(k) {
  if (!Array.isArray(k)) return null;
  const openTime = num(k[0]), closeTime = num(k[6]);
  if (openTime === null || closeTime !== openTime + HOUR - 1) return null;
  const open = positiveNum(k[1]), high = positiveNum(k[2]), low = positiveNum(k[3]), close = positiveNum(k[4]);
  const quoteVolume = num(k[7]);
  if (![openTime, closeTime, open, high, low, close, quoteVolume].every(Number.isFinite) || quoteVolume < 0) return null;
  if (high < Math.max(open, close) || low > Math.min(open, close)) return null;
  return { openTime, closeTime, open, high, low, close, quoteVolume };
}

// Binance returns the still-open hour last; its partial volume would read as a volume collapse.
export function closedKlines(klines, now = Date.now()) {
  return Array.isArray(klines) ? klines.filter(k => Array.isArray(k) && num(k[6]) !== null && num(k[6]) < now) : [];
}

// Exactly `hours` consecutive closed hourly candles ending within the last two hours, or null.
export function hourWindow(klines, now = Date.now(), hours = 48) {
  // Only the rows actually used are judged: a damaged surplus row outside the window is irrelevant.
  const win = closedKlines(klines, now).slice(-hours).map(parseKline);
  if (win.length < hours || win.some(r => r === null)) return null;
  for (let i = 1; i < win.length; i++) if (win[i].openTime - win[i - 1].openTime !== HOUR) return null;
  return now - win[win.length - 1].closeTime <= 2 * HOUR ? win : null;
}

function splitTrend(candles) {
  if (!candles) return null;
  const half = candles.length / 2;
  const first = candles.slice(0, half);
  const second = candles.slice(half);
  const start = first[0].open;
  const end = second[second.length - 1].close;
  const priceChangePct = (end / start - 1) * 100;
  const firstVol = first.reduce((s, c) => s + c.quoteVolume, 0) / first.length;
  const secondVol = second.reduce((s, c) => s + c.quoteVolume, 0) / second.length;
  const volumeChangePct = firstVol > 0 ? (secondVol / firstVol - 1) * 100 : null;
  return { priceChangePct, volumeChangePct, firstVol, secondVol, latest: candles[candles.length - 1] };
}

function wickStats(candles) {
  if (!candles) return null;
  const recentRows = candles.slice(-12);
  const ratios = recentRows.map(c => {
    const range = c.high - c.low;
    const upper = c.high - Math.max(c.open, c.close);
    return range > 0 ? upper / range : 0;
  });
  const avgUpperWickPct = ratios.reduce((a, b) => a + b, 0) / ratios.length * 100;
  const latest = candles[candles.length - 1];
  const latestPullbackPct = (latest.high - latest.close) / latest.high * 100;
  return { avgUpperWickPct, latestPullbackPct };
}

function addMetric(metrics, metric) {
  metrics.push({
    ...metric,
    score: clamp(Math.round(metric.score || 0), 0, metric.maxScore || 100),
    status: metric.status || 'neutral',
    available: metric.available !== false,
  });
}

function levelFromScore(score) {
  if (score <= 34) return { code: 'healthy', label: '承接正常', tone: 'good' };
  if (score <= 64) return { code: 'watch', label: '派发苗头', tone: 'warn' };
  return { code: 'distribution', label: '强派发嫌疑', tone: 'danger' };
}

// Below this share of metric weight backed by real data the page states "数据不足"
// instead of a score assembled mostly from neutral placeholders.
const MIN_COVERAGE = 70;

// Vercel calls handler(request, context): the second argument is the runtime context, never a
// clock. Tests drive handleAt() with a fixed time instead.
export default function handler(req) {
  return handleAt(req, Date.now());
}

export async function handleAt(req, now) {
  if (req.method !== 'GET' && req.method !== 'OPTIONS') {
    return new Response(JSON.stringify({ error: 'Method Not Allowed' }), { status: 405, headers: { ...JSON_HEADERS, Allow: 'GET, OPTIONS' } });
  }
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: JSON_HEADERS });
  if (memo && now - memo.at >= 0 && now - memo.at < MEMO_MS) return new Response(memo.body, { status: 200, headers: JSON_HEADERS });
  // Concurrent cold requests share one upstream round instead of each starting 18 fetches.
  if (!inflight) inflight = compute(now).finally(() => { inflight = null; });
  const body = await inflight;
  return new Response(body, { status: 200, headers: JSON_HEADERS });
}

async function compute(now) {
  const results = await Promise.all(Object.entries(ENDPOINTS).map(([key, url]) => safeFetchJson(key, url, now)));
  const data = {};
  const notes = [];
  const sourcesFailed = [];
  for (const r of results) {
    if (r.ok) data[r.key] = r.data;
    else sourcesFailed.push({ key: r.key, error: r.error });
  }

  const spotTicker = data.spotTicker || {};
  const futuresTicker = data.futuresTicker || {};
  const premium = data.premium || {};
  const openInterest = data.openInterest || {};
  const spotWindow = hourWindow(data.spotKlines, now);
  const futuresWindow = hourWindow(data.futuresKlines, now);
  const spotTrend = splitTrend(spotWindow);
  const wick = wickStats(futuresWindow) || wickStats(spotWindow);

  const spotPrice = positiveNum(spotTicker.lastPrice) || positiveNum(premium.indexPrice) || (spotTrend?.latest?.close ?? null);
  const markPrice = positiveNum(premium.markPrice) || spotPrice;
  const spotQuoteVolume = positiveNum(spotTicker.quoteVolume);
  const futuresQuoteVolume = positiveNum(futuresTicker.quoteVolume);
  const price24hPct = num(spotTicker.priceChangePercent);
  const price48hPct = spotTrend?.priceChangePct ?? null;
  const rawFundingRate = num(premium.lastFundingRate);
  const fundingRatePct = Number.isFinite(rawFundingRate) ? rawFundingRate * 100 : null;
  const oiBtc = positiveNum(openInterest.openInterest);
  const oiNotional = oiBtc && markPrice ? oiBtc * markPrice : null;
  const futuresSpotRatio = spotQuoteVolume && futuresQuoteVolume ? futuresQuoteVolume / spotQuoteVolume : null;
  const {
    futuresVenues,
    spotVenues,
    globalFuturesQuoteVolume,
    globalSpotQuoteVolume,
    paired,
  } = buildVolumeAggregation(data, spotPrice, futuresQuoteVolume, spotQuoteVolume);
  const ratioForMetric = paired.ratio;
  const globalFuturesSpotRatio = paired.ratio;
  const oiToFuturesVolume = oiNotional && futuresQuoteVolume ? oiNotional / futuresQuoteVolume : null;
  const fiatSpot = parseFiatSpotTicker(data);
  const fiatSpotPrice = fiatSpot.price;
  const fiatSpotSource = fiatSpot.source;
  // Binance quotes in USDT, which itself drifts around $1 by ±0.1%. Convert before comparing with USD venues,
  // otherwise the "premium" mostly measures the USDT/USD basis.
  const usdtUsd = positiveNum(data.krakenUsdtUsd?.result?.USDTZUSD?.c?.[0] ?? data.krakenUsdtUsd?.result?.USDTUSD?.c?.[0]);
  // The premium compares the Binance spot quote itself, never the futures index fallback.
  const binanceSpotLast = positiveNum(spotTicker.lastPrice);
  const spotPriceUsd = binanceSpotLast && usdtUsd && usdtUsd > 0.97 && usdtUsd < 1.03 ? binanceSpotLast * usdtUsd : null;
  // The two quotes must be within five minutes of each other (Kraken has no timestamp: accepted as live).
  const fiatAt = fiatSpot.key && OBSERVED[fiatSpot.key] ? OBSERVED[fiatSpot.key](data[fiatSpot.key]) : null;
  const spotAt = binanceSpotLast ? OBSERVED.spotTicker(spotTicker) : null;
  const aligned = fiatAt === null || (spotAt !== null && Math.abs(fiatAt - spotAt) <= TICKER_MAX_AGE_MS);
  const fiatSpotPremiumPct = fiatSpotPrice && spotPriceUsd && aligned ? (fiatSpotPrice / spotPriceUsd - 1) * 100 : null;
  // Backward-compatible aliases for older frontends/consumers.
  const coinbasePrice = fiatSpotPrice;
  const coinbasePremiumPct = fiatSpotPremiumPct;

  // Last 24 hourly rows ending within two hours; each needs a timestamp and a positive ratio.
  // A ratio of 0 (no taker buying at all) is a real observation; one row per whole hour, so
  // 24 rows bunched into a few minutes cannot pose as a day.
  const takerByHour = new Map();
  for (const r of Array.isArray(data.takerLongShort) ? data.takerLongShort : []) {
    const t = num(r?.timestamp), v = num(r?.buySellRatio);
    if (t !== null && t % HOUR === 0 && v !== null && v >= 0 && t <= now + FUTURE_SKEW_MS && now - t <= 26 * HOUR) takerByHour.set(t, v);
  }
  const takerRows = [...takerByHour].map(([t, v]) => ({ t, v }));
  // Exactly the last 24 consecutive hours, ending within two hours: no interior gaps.
  takerRows.sort((a, b) => a.t - b.t);
  const lastTaker = takerRows.length ? takerRows[takerRows.length - 1].t : null;
  const takerFresh = takerRows.length >= 24 && now - lastTaker <= 2 * HOUR
    && takerRows.slice(-24).every((r, i, a) => i === 0 || r.t - a[i - 1].t === HOUR);
  if (takerFresh) takerRows.splice(0, takerRows.length - 24);
  const takerBuySellRatio = takerFresh ? takerRows.reduce((a, r) => a + r.v, 0) / takerRows.length : null;

  const metrics = [];

  // 1) 价格趋势与成交量背离（权重 18）
  let divScore = 7;
  if (spotTrend && Number.isFinite(spotTrend.priceChangePct) && Number.isFinite(spotTrend.volumeChangePct)) {
    if (spotTrend.priceChangePct > 2 && spotTrend.volumeChangePct < -25) divScore = 18;
    else if (spotTrend.priceChangePct > 1 && spotTrend.volumeChangePct < -10) divScore = 13;
    else if (spotTrend.priceChangePct > 0 && spotTrend.volumeChangePct < 0) divScore = 9;
    else if (spotTrend.priceChangePct > 0 && spotTrend.volumeChangePct > 15) divScore = 3;
    else divScore = 6;
    addMetric(metrics, {
      id: 'spot_volume_divergence', name: '价格趋势与现货成交量背离', maxScore: 18, score: divScore,
      status: divScore >= 13 ? 'risk' : divScore <= 5 ? 'healthy' : 'neutral',
      value: `${pct(spotTrend.priceChangePct)} / 量 ${pct(spotTrend.volumeChangePct)}`,
      detail: '对比最近 48 根 1h 现货K线前后两段：价格上涨但成交额下降，代表承接质量变弱。',
    });
  } else {
    addMetric(metrics, { id: 'spot_volume_divergence', name: '价格趋势与现货成交量背离', maxScore: 18, score: 7, status: 'neutral', value: '待接入', detail: '最近 48 根已收盘 1h 现货K线不完整或过期，按中性处理。', available: false });
  }

  // 2) 全市场合约/现货成交比（权重 16）——只用合约、现货两边都拿到的交易所
  let ratioScore = 7;
  if (Number.isFinite(ratioForMetric)) {
    // BTC derivatives volume normally runs 4-10x spot; only clearly elevated levels score high.
    ratioScore = ratioForMetric > 14 ? 16 : ratioForMetric > 10 ? 12 : ratioForMetric > 6 ? 8 : 4;
    const complete = paired.exchanges.length === 3;
    addMetric(metrics, {
      id: 'futures_spot_volume_ratio', name: '全市场合约 / 现货成交比', maxScore: 16, score: ratioScore,
      status: ratioScore >= 12 ? 'risk' : ratioScore <= 5 ? 'healthy' : 'neutral',
      value: `${ratioForMetric.toFixed(2)}x（${paired.exchanges.join('/')}）`,
      detail: `同一组交易所（${paired.exchanges.join('、')}）的 24h 成交额：合约 ${usd(paired.futures)}，现货 ${usd(paired.spot)}。${complete ? '' : 'OKX 或 Bybit 缺一侧数据，本次退回固定的 Binance 单家口径，与三家口径不完全可比。'}Deribit 没有现货，只列在合约明细里、不进比值。比值越高，越像合约推着价格走。`,
    });
  } else {
    addMetric(metrics, { id: 'futures_spot_volume_ratio', name: '全市场合约 / 现货成交比', maxScore: 16, score: 7, status: 'neutral', value: '待接入', available: false, detail: '没有任何一家交易所同时拿到合约和现货 24h 成交额，按中性处理。' });
  }

  // 3) OI 杠杆压力（权重 16）
  let oiScore = 7;
  if (Number.isFinite(oiToFuturesVolume)) {
    oiScore = oiToFuturesVolume > 0.45 ? 16 : oiToFuturesVolume > 0.28 ? 12 : oiToFuturesVolume > 0.16 ? 8 : 4;
    if ((price24hPct ?? 0) > 2 && Number.isFinite(fundingRatePct) && fundingRatePct > 0.02) oiScore = Math.min(16, oiScore + 2);
    addMetric(metrics, {
      id: 'open_interest_pressure', name: 'OI 规模 / 杠杆拥挤度', maxScore: 16, score: oiScore,
      status: oiScore >= 12 ? 'risk' : oiScore <= 5 ? 'healthy' : 'neutral',
      value: `${usd(oiNotional)} / 24h量 ${(oiToFuturesVolume * 100).toFixed(1)}%`,
      detail: '当前 BTCUSDT 永续 OI 折美元后对比 24h 合约成交额；价格上涨时 OI 拥挤说明杠杆资金占比偏高。',
    });
  } else {
    addMetric(metrics, { id: 'open_interest_pressure', name: 'OI 规模 / 杠杆拥挤度', maxScore: 16, score: 7, status: 'neutral', value: '待接入', available: false, detail: 'Open Interest 或合约成交额获取失败，按中性处理。' });
  }

  // 4) Funding 热度（权重 14）
  if (Number.isFinite(fundingRatePct)) {
    const fundingScore = fundingRatePct > 0.06 ? 14 : fundingRatePct > 0.03 ? 10 : fundingRatePct > 0.015 ? 6 : fundingRatePct < -0.01 ? 2 : 4;
    addMetric(metrics, {
      id: 'funding_heat', name: 'Funding 多头付费热度', maxScore: 14, score: fundingScore,
      status: fundingScore >= 10 ? 'risk' : fundingScore <= 4 ? 'healthy' : 'neutral',
      value: `${fundingRatePct.toFixed(4)}% / 8h`,
      detail: 'Funding 越高，说明追多资金越拥挤；上涨主要由高 funding 推动时，冲高回落风险上升。',
    });
  } else {
    addMetric(metrics, {
      id: 'funding_heat', name: 'Funding 多头付费热度', maxScore: 14, score: 6,
      status: 'neutral', value: '待接入 / 中性', available: false,
      detail: 'Funding 接口获取失败，不能判断多头拥挤度，暂按中性处理。',
    });
  }

  // 5) 上影线 / 冲高回落（权重 14）
  let wickScore = 6;
  if (wick) {
    wickScore = wick.avgUpperWickPct > 38 || wick.latestPullbackPct > 1.2 ? 14 : wick.avgUpperWickPct > 28 || wick.latestPullbackPct > 0.7 ? 10 : wick.avgUpperWickPct > 20 ? 7 : 3;
    addMetric(metrics, {
      id: 'upper_wick_pullback', name: '上影线 / 冲高回落', maxScore: 14, score: wickScore,
      status: wickScore >= 10 ? 'risk' : wickScore <= 4 ? 'healthy' : 'neutral',
      value: `均上影 ${wick.avgUpperWickPct.toFixed(1)}% / 最新回落 ${wick.latestPullbackPct.toFixed(2)}%`,
      detail: '统计最近 12 根 1h K线的上影占比与最新K线距高点回落幅度。上影多代表高位抛压增强。',
    });
  } else {
    addMetric(metrics, { id: 'upper_wick_pullback', name: '上影线 / 冲高回落', maxScore: 14, score: 6, status: 'neutral', value: '待接入', detail: '合约与现货 1h K线均不完整或过期，按中性处理。', available: false });
  }

  // 6) 美元现货溢价（权重 12）
  let cbScore = 5;
  if (Number.isFinite(fiatSpotPremiumPct)) {
    cbScore = fiatSpotPremiumPct < -0.15 ? 12 : fiatSpotPremiumPct < -0.05 ? 9 : fiatSpotPremiumPct < 0.05 ? 6 : 2;
    if ((price24hPct ?? price48hPct ?? 0) > 1 && fiatSpotPremiumPct < 0.02) cbScore = Math.min(12, cbScore + 2);
    addMetric(metrics, {
      id: 'coinbase_premium', name: '美元现货溢价', maxScore: 12, score: cbScore,
      status: cbScore >= 9 ? 'risk' : cbScore <= 3 ? 'healthy' : 'neutral',
      value: `${fiatSpotPremiumPct >= 0 ? '+' : ''}${fiatSpotPremiumPct.toFixed(3)}% (${fiatSpotSource})`,
      detail: `${fiatSpotSource} BTC/USD ${usd(fiatSpotPrice, 2)} vs Binance BTCUSDT ${usd(binanceSpotLast, 2)} × USDT/USD ${usdtUsd?.toFixed(4)}（Kraken）。先扣除 USDT 自身的溢价/折价，再比较美元现货买盘强弱。`,
    });
  } else {
    const why = !fiatSpotPrice ? 'Coinbase/Kraken/Bitstamp/Gemini 美元现货 ticker 均不可用'
      : !binanceSpotLast ? 'Binance 现货报价不可用或已过期'
      : !aligned ? 'Binance 与美元现货报价时间相差超过 5 分钟'
      : 'Kraken USDT/USD 不可用或偏离 1 美元过多，无法扣除 USDT 基差';
    notes.push(`美元现货溢价暂缺：${why}，按中性处理。`);
    addMetric(metrics, { id: 'coinbase_premium', name: '美元现货溢价', maxScore: 12, score: 5, status: 'neutral', value: '待接入', available: false, detail: `${why}，按中性处理。` });
  }

  // 7) 主动买盘质量（权重 10）
  let takerScore = 5;
  if (Number.isFinite(takerBuySellRatio)) {
    takerScore = takerBuySellRatio < 0.9 ? 10 : takerBuySellRatio < 0.98 ? 7 : takerBuySellRatio < 1.08 ? 4 : 2;
    addMetric(metrics, {
      id: 'active_buy_quality', name: '主动买盘质量', maxScore: 10, score: takerScore,
      status: takerScore >= 7 ? 'risk' : takerScore <= 3 ? 'healthy' : 'neutral',
      value: `买卖比 ${takerBuySellRatio.toFixed(2)}`,
      detail: 'Binance futures taker long/short buy-sell ratio 最近 24 小时均值；上涨时主动买盘偏弱，是承接不足信号。',
    });
  } else {
    addMetric(metrics, { id: 'active_buy_quality', name: '主动买盘质量', maxScore: 10, score: 5, status: 'neutral', value: '待接入 / 中性', detail: '公开接口可能限流或不可用，暂按中性处理。', available: false });
  }

  const coverage = metrics.reduce((sum, m) => sum + (m.available ? m.maxScore : 0), 0);
  const enough = coverage >= MIN_COVERAGE && Number.isFinite(spotPrice);
  const score = enough ? clamp(metrics.reduce((sum, m) => sum + (m.score || 0), 0), 0, 100) : null;
  const level = enough ? levelFromScore(score) : { code: 'unavailable', label: '数据不足', tone: 'warn' };
  const riskNames = metrics.filter(m => m.status === 'risk').map(m => m.name).slice(0, 3);
  const summary = !enough
    ? `可用数据只覆盖 ${coverage}% 的指标权重（需 ≥${MIN_COVERAGE}%），本次不给出判断。`
    : riskNames.length
      ? `当前风险点集中在：${riskNames.join('、')}。该页面只观察“上涨质量”，不判断方向。`
      : '当前未见明显派发结构，现货承接与衍生品热度暂未出现极端背离。';
  if (sourcesFailed.length) notes.push(`本次 ${sourcesFailed.length} 个数据源不可用：${sourcesFailed.map(f => f.key).join('、')}。`);

  const okSources = Object.keys(data);
  const body = JSON.stringify({
    generatedAt: new Date(now).toISOString(),
    score,
    level,
    summary,
    coverage,
    metrics,
    raw: {
      price: spotPrice,
      priceChange24hPct: price24hPct,
      priceChange48hPct: price48hPct,
      spotQuoteVolume,
      futuresQuoteVolume,
      futuresSpotRatio,
      globalFuturesQuoteVolume,
      globalSpotQuoteVolume,
      globalFuturesSpotRatio,
      futuresVenues,
      spotVenues,
      openInterestBtc: oiBtc,
      openInterestNotionalUsd: oiNotional,
      fundingRatePct,
      fiatSpotPrice,
      fiatSpotSource,
      fiatSpotPremiumPct,
      coinbasePrice,
      coinbasePremiumPct,
      takerBuySellRatio,
      ratioExchanges: paired.exchanges,
      observedAt: Object.fromEntries(Object.keys(OBSERVED).filter(k => data[k]).map(k => [k, new Date(OBSERVED[k](data[k])).toISOString()])),
      latestTakerHour: takerFresh ? new Date(Math.max(...takerRows.map(r => r.t))).toISOString() : null,
      latestClosedHour: spotWindow ? new Date(spotWindow[spotWindow.length - 1].closeTime + 1).toISOString() : null,
      sourcesOk: okSources,
      sourcesFailed,
    },
    notes: [
      '仅作为市场结构观察，不构成投资建议。',
      '合约/现货成交比固定用 Binance / OKX / Bybit 三家（合约、现货两侧都要拿到）；任一家缺失时退回 Binance 单家口径。Deribit 只列入合约明细，不进比值。',
      'Coinbase/Kraken/Bitstamp/Gemini 美元现货价格用于溢价，Binance USDT 价格先按 Kraken USDT/USD 折算成美元。',
      `每个数据源要通过品种、成功码和时效校验才算可用（Kraken 行情接口不带时间戳，按实时快照接受）；缺失的指标按中性处理，有数据的指标权重不足 ${MIN_COVERAGE}% 时不出分。`,
      ...notes,
    ],
  }, null, 2);
  memo = { at: now, body };
  return body;
}
