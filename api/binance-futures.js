/**
 * Vercel Edge Function: POST /api/binance-futures
 *
 * Binance 合约公开行情中转。fapi.binance.com 对美国 IP 返回 HTTP 451，
 * GitHub Actions 的 runner 都在美国，采集脚本直连一律失败（资金雷达长期 0/519 就是这个原因）。
 * 这里把执行区域固定在新加坡，GitHub Actions 改为批量请求本函数。
 *
 * 只转发白名单里的公开 GET 行情端点，不接受任何密钥、下单或账户接口。
 * 只服务本站的采集任务：请求必须带 `X-Relay-Token`，与 Vercel 环境变量 RELAY_TOKEN 一致；
 * 未配置 RELAY_TOKEN 时拒绝一切请求（失败即关闭），避免成为公开的转发器。
 * 请求体: { "requests": [{ "path": "/fapi/v1/premiumIndex", "params": { "symbol": "BTCUSDT" } }] }
 * 返回:   { "region": "...", "results": [{ "status": 200, "body": ... } | { "status": 429, "error": "...", "retryAfter": 60 }] }
 */

export const config = { runtime: 'edge', regions: ['sin1'] };

const HOST = 'https://fapi.binance.com';
const PATHS = new Set([
  '/fapi/v1/exchangeInfo',
  '/fapi/v1/ticker/24hr',
  '/fapi/v1/premiumIndex',
  '/fapi/v1/fundingRate',
  '/fapi/v1/openInterest',
  '/futures/data/openInterestHist',
  '/futures/data/topLongShortPositionRatio',
  '/futures/data/topLongShortAccountRatio',
  '/futures/data/globalLongShortAccountRatio',
  '/futures/data/takerlongshortRatio',
]);
// Binance's published proof-of-reserves wallet list, used to label exchange holders in the radar.
const OTHER_HOSTS = { '/bapi/apex/v1/public/apex/market/por/address': 'https://www.binance.com' };
const PARAMS = new Set(['symbol', 'period', 'limit', 'startTime', 'endTime']);
// Letters of any script: Binance lists contracts such as 币安人生USDT.
const VALUE_RE = /^[\p{L}\p{N}]{1,24}$/u;
const MAX_REQUESTS = 120;
const CONCURRENCY = 8;
// Edge functions must start responding within 25s; stop dispatching well before that.
const BATCH_DEADLINE_MS = 20000;
const REQUEST_TIMEOUT_MS = 8000;
const THROTTLED = new Set([418, 429]);

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...extra },
  });
}

export function buildUrl(request) {
  if (!request || typeof request !== 'object' || typeof request.path !== 'string') return null;
  const host = PATHS.has(request.path) ? HOST : Object.hasOwn(OTHER_HOSTS, request.path) ? OTHER_HOSTS[request.path] : null;
  if (!host) return null;
  const params = new URLSearchParams();
  const given = request.params ?? {};
  if (typeof given !== 'object' || Array.isArray(given)) return null;
  for (const [key, value] of Object.entries(given)) {
    if (!PARAMS.has(key) || !['string', 'number'].includes(typeof value) || !VALUE_RE.test(String(value))) return null;
    params.set(key, String(value));
  }
  const query = params.toString();
  return host + request.path + (query ? '?' + query : '');
}

async function forward(url, remainingMs) {
  if (!url) return { status: 400, error: 'Path or parameter not allowed' };
  try {
    const res = await fetch(url, {
      headers: { 'User-Agent': 'FlowHunt-public-research/1.0' },
      signal: AbortSignal.timeout(Math.max(1000, Math.min(REQUEST_TIMEOUT_MS, remainingMs))),
    });
    if (!res.ok) {
      const retryAfter = Number(res.headers.get('retry-after'));
      return { status: res.status, error: `HTTP ${res.status}`, ...(Number.isFinite(retryAfter) ? { retryAfter } : {}) };
    }
    return { status: 200, body: await res.json() };
  } catch (err) {
    return { status: 502, error: String(err?.name || 'FetchError') };
  }
}

export default async function handler(req) {
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405, { Allow: 'POST' });
  const expected = process.env.RELAY_TOKEN;
  if (!expected) return json({ error: 'Relay not configured' }, 503);
  if (req.headers.get('x-relay-token') !== expected) return json({ error: 'Unauthorized' }, 401);
  let payload;
  try {
    payload = await req.json();
  } catch {
    return json({ error: 'Invalid JSON' }, 400);
  }
  const requests = Array.isArray(payload?.requests) ? payload.requests : null;
  if (!requests || requests.length === 0 || requests.length > MAX_REQUESTS) {
    return json({ error: `requests must contain 1-${MAX_REQUESTS} items` }, 400);
  }
  const urls = requests.map(buildUrl);
  const results = new Array(urls.length);
  const started = Date.now();
  let next = 0;
  let stop = null;
  async function worker() {
    while (next < urls.length) {
      const index = next++;
      const remaining = BATCH_DEADLINE_MS - (Date.now() - started);
      if (stop) { results[index] = { status: stop.status, error: 'skipped after upstream throttling', ...(stop.retryAfter ? { retryAfter: stop.retryAfter } : {}) }; continue; }
      if (remaining <= 0) { results[index] = { status: 504, error: 'relay batch deadline' }; continue; }
      const result = await forward(urls[index], remaining);
      // A 429/418 means Binance wants this IP to back off; sending the rest of the batch prolongs a ban.
      if (THROTTLED.has(result.status) && !stop) stop = result;
      results[index] = result;
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, urls.length) }, worker));
  return json({ region: process.env.VERCEL_REGION || null, results });
}
