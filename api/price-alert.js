/**
 * Vercel Serverless Function: /api/price-alert
 *
 * 两种调用方式：
 * 1. Vercel Cron（每5分钟）: GET /api/price-alert  — 自动拉价格，对所有alerts检查并推送
 * 2. 前端手动触发:            POST /api/price-alert — body: { alerts, serverChanKey }
 *
 * Alert 格式:
 * { id, symbol, condition, targetPrice, label, triggered, serverChanKey }
 * condition: 'below' | 'above'
 * symbol: 'BTC' | 'ETH' | 任意 CoinGecko id
 */

const COINGECKO_IDS = {
  BTC: 'bitcoin',
  ETH: 'ethereum',
  BNB: 'binancecoin',
  SOL: 'solana',
  XRP: 'ripple',
  ADA: 'cardano',
  DOGE: 'dogecoin',
  AVAX: 'avalanche-2',
  DOT: 'polkadot',
  MATIC: 'matic-network',
  LINK: 'chainlink',
  UNI: 'uniswap',
};

async function getPrice(symbol) {
  const cgId = COINGECKO_IDS[symbol.toUpperCase()] || symbol.toLowerCase();

  // 先试 Binance（BTC/ETH/BNB/SOL等主流币快）
  try {
    const pair = symbol.toUpperCase() + 'USDT';
    const res = await fetch(`https://api.binance.com/api/v3/ticker/price?symbol=${pair}`, {
      signal: AbortSignal.timeout(4000),
    });
    if (res.ok) {
      const d = await res.json();
      const p = parseFloat(d.price);
      if (!isNaN(p) && p > 0) return { price: p, source: 'Binance' };
    }
  } catch (_) {}

  // 备用 CoinGecko
  const res = await fetch(
    `https://api.coingecko.com/api/v3/simple/price?ids=${cgId}&vs_currencies=usd`,
    { signal: AbortSignal.timeout(8000) }
  );
  if (!res.ok) throw new Error(`CoinGecko HTTP ${res.status}`);
  const d = await res.json();
  const p = d?.[cgId]?.usd;
  if (!p) throw new Error(`No price for ${symbol}`);
  return { price: p, source: 'CoinGecko' };
}

// Server酱 SendKey 只含字母数字；拦住拼进 URL 路径的其它字符
const SENDKEY_RE = /^[A-Za-z0-9]{8,80}$/;
const SYMBOL_RE = /^[A-Za-z0-9]{2,12}$/;
const MAX_ALERTS = 20;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function isValidAlert(a) {
  return a && typeof a === 'object' &&
    typeof a.symbol === 'string' && SYMBOL_RE.test(a.symbol) &&
    (a.condition === 'below' || a.condition === 'above') &&
    typeof a.targetPrice === 'number' && Number.isFinite(a.targetPrice);
}

async function sendServerChan(key, title, desp) {
  if (!SENDKEY_RE.test(key)) throw new Error('Invalid SendKey');
  const url = `https://sctapi.ftqq.com/${key}.send`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ title, desp }),
    signal: AbortSignal.timeout(8000),
  });
  const d = await res.json();
  return d;
}

export default async function handler(req) {
  const isCron = req.method === 'GET';

  let alerts = [];
  let serverChanKey = '';

  if (isCron) {
    // Cron 模式：Vercel 会带上 Authorization: Bearer <CRON_SECRET>，
    // 没配 CRON_SECRET 或对不上就拒绝，免得任何人 GET 一下就触发推送
    const secret = process.env.CRON_SECRET;
    if (!secret || req.headers.get('authorization') !== `Bearer ${secret}`) {
      return json({ error: 'Unauthorized' }, 401);
    }
    // 从环境变量读 key 和 alerts
    serverChanKey = process.env.SERVER_CHAN_KEY || '';
    const raw = process.env.PRICE_ALERTS || '[]';
    try { alerts = JSON.parse(raw); } catch (_) { alerts = []; }
  } else {
    // 前端 POST 模式
    try {
      const body = await req.json();
      alerts = body.alerts || [];
      // 前端必须自带 key；绝不回退到站长的 SERVER_CHAN_KEY，否则谁都能往站长微信发消息
      serverChanKey = typeof body.serverChanKey === 'string' ? body.serverChanKey : '';
    } catch (_) {
      return json({ error: 'Invalid JSON body' }, 400);
    }
    if (!SENDKEY_RE.test(serverChanKey)) {
      return json({ error: 'serverChanKey required' }, 400);
    }
  }

  alerts = (Array.isArray(alerts) ? alerts : []).filter(isValidAlert).slice(0, MAX_ALERTS);

  if (!alerts.length) {
    return new Response(JSON.stringify({ ok: true, checked: 0, triggered: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // 按 symbol 分组，批量拉价格
  const symbols = [...new Set(alerts.map(a => a.symbol.toUpperCase()))];
  const prices = {};
  await Promise.all(symbols.map(async sym => {
    try {
      const { price } = await getPrice(sym);
      prices[sym] = price;
    } catch (e) {
      prices[sym] = null;
      console.error(`Price fetch failed for ${sym}:`, e.message);
    }
  }));

  const triggered = [];

  for (const alert of alerts) {
    if (alert.triggered) continue; // 已触发，跳过
    const sym = alert.symbol.toUpperCase();
    const current = prices[sym];
    if (current === null) continue;

    const hit =
      (alert.condition === 'below' && current <= alert.targetPrice) ||
      (alert.condition === 'above' && current >= alert.targetPrice);

    if (hit) {
      triggered.push({ ...alert, currentPrice: current });

      // 推送微信
      const key = isCron ? (alert.serverChanKey || serverChanKey) : serverChanKey;
      if (key) {
        const dir = alert.condition === 'below' ? '📉 跌破' : '📈 突破';
        const title = `🔔 ${sym} 价格提醒 | ${dir} $${alert.targetPrice.toLocaleString()}`;
        const desp = [
          `**标的：** ${sym}`,
          `**目标价：** $${alert.targetPrice.toLocaleString()}`,
          `**当前价：** $${current.toLocaleString()}`,
          `**条件：** ${dir} 目标价`,
          alert.label ? `**备注：** ${alert.label}` : '',
          '',
          `[点击查看仪表盘](https://btc.flowhunt.net)`,
        ].filter(Boolean).join('\n\n');

        try {
          await sendServerChan(key, title, desp);
        } catch (e) {
          console.error('Server酱推送失败:', e.message);
        }
      }
    }
  }

  return new Response(
    JSON.stringify({ ok: true, checked: alerts.length, triggered, prices }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    }
  );
}

export const config = {
  runtime: 'edge',
};
