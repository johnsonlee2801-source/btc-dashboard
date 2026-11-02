/**
 * Vercel Edge Function: POST /api/binance-futures
 *
 * Binance 合约公开行情中转。fapi.binance.com 对美国 IP 返回 HTTP 451，
 * GitHub Actions 的 runner 都在美国，采集脚本直连一律失败（资金雷达长期 0/519 就是这个原因）。
 * 这里把执行区域固定在新加坡，GitHub Actions 改为批量请求本函数。
 *
 * 只转发白名单里的公开 GET 行情端点，不接受任何密钥、下单或账户接口。
 * 请求体: { "requests": [{ "path": "/fapi/v1/premiumIndex", "params": { "symbol": "BTCUSDT" } }] }
 * 返回:   { "region": "...", "results": [{ "status": 200, "body": ... } | { "status": 451, "error": "..." }] }
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
const PARAMS = new Set(['symbol', 'period', 'limit', 'startTime', 'endTime']);
// Letters of any script: Binance lists contracts such as 币安人生USDT.
const VALUE_RE = /^[\p{L}\p{N}]{1,24}$/u;
const MAX_REQUESTS = 120;
const CONCURRENCY = 8;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

function buildUrl(request) {
  if (!request || typeof request !== 'object' || !PATHS.has(request.path)) return null;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(request.params || {})) {
    if (!PARAMS.has(key) || !VALUE_RE.test(String(value))) return null;
    params.set(key, String(value));
  }
  const query = params.toString();
  return HOST + request.path + (query ? '?' + query : '');
}

async function forward(url) {
  if (!url) return { status: 400, error: 'Path or parameter not allowed' };
  try {
    const res = await fetch(url, {
      headers: { 'User-Agent': 'FlowHunt-public-research/1.0' },
      signal: AbortSignal.timeout(12000),
    });
    if (!res.ok) return { status: res.status, error: `HTTP ${res.status}` };
    return { status: 200, body: await res.json() };
  } catch (err) {
    return { status: 502, error: String(err?.name || 'FetchError') };
  }
}

export default async function handler(req) {
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
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
  let next = 0;
  async function worker() {
    while (next < urls.length) {
      const index = next++;
      results[index] = await forward(urls[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, urls.length) }, worker));
  return json({ region: process.env.VERCEL_REGION || null, results });
}
