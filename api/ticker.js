/**
 * Vercel Edge Function: /api/ticker?symbol=BTC
 *
 * 同源行情中转。api.binance.com 等交易所域名在大陆访问不到，前端直连会一直卡在 "--"；
 * 走自己的域名，由边缘节点同时问几家交易所，谁先答用谁（各地区的封锁不同，并发比串行稳）。
 * CDN 缓存 10 秒，访客再多，上游请求量也被压在每节点每 10 秒一次左右。
 *
 * 返回: { symbol, price, change24h, source }
 */

export const config = { runtime: 'edge' };

const SYMBOL_RE = /^[A-Z0-9]{2,12}$/;

async function getJson(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(4000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function pct(last, open) {
  return open > 0 ? ((last - open) / open) * 100 : null;
}

function valid(q) {
  if (!Number.isFinite(q.price) || q.price <= 0) throw new Error('bad price');
  return q;
}

const SOURCES = [
  async sym => {
    const d = await getJson(`https://www.okx.com/api/v5/market/ticker?instId=${sym}-USDT`);
    const t = d?.data?.[0];
    const last = parseFloat(t?.last);
    return valid({ price: last, change24h: pct(last, parseFloat(t?.open24h)), source: 'OKX' });
  },
  async sym => {
    const d = await getJson(`https://api.binance.com/api/v3/ticker/24hr?symbol=${sym}USDT`);
    return valid({ price: parseFloat(d.lastPrice), change24h: parseFloat(d.priceChangePercent), source: 'Binance' });
  },
  async sym => {
    const d = await getJson(`https://api.exchange.coinbase.com/products/${sym}-USD/stats`);
    const last = parseFloat(d.last);
    return valid({ price: last, change24h: pct(last, parseFloat(d.open)), source: 'Coinbase' });
  },
];

export default async function handler(req) {
  const sym = (new URL(req.url).searchParams.get('symbol') || 'BTC').toUpperCase();
  if (!SYMBOL_RE.test(sym)) {
    return new Response(JSON.stringify({ error: 'Invalid symbol' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const q = await Promise.any(SOURCES.map(fn => fn(sym)));
    const change24h = Number.isFinite(q.change24h) ? q.change24h : null;
    return new Response(JSON.stringify({ symbol: sym, price: q.price, change24h, source: q.source, asOf: new Date().toISOString() }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, s-maxage=10, stale-while-revalidate=30',
      },
    });
  } catch (_) {
    return new Response(JSON.stringify({ error: 'All price sources failed', symbol: sym }), {
      status: 502,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  }
}
