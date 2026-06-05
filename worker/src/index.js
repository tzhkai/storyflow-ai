/**
 * StoryFlow API Worker
 * 
 * 部署：wrangler deploy
 * 设置环境变量：wrangler secret put DEEPSEEK_API_KEY（以及其他密钥）
 */

const RATE_LIMIT = new Map();
const RATE_LIMIT_WINDOW = 10000; // 10 秒

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: corsHeaders(),
      });
    }

    try {
      const routes = {
        '/api/health': () => json({ ok: true, version: '1.0' }),
        '/api/v1/chat': () => handleChat(request, env),
        '/api/v1/chat/completions': () => handleChat(request, env),
        '/api/v1/license/sign': () => handleLicenseSign(request, env),
        '/api/v1/license/verify': () => handleLicenseVerify(request, env),
        '/api/v1/afdian/activate': () => handleAfdianActivate(request, env),
        '/api/v1/payment/create-order': () => handleCreateOrder(request, env, url),
        '/api/v1/payment/callback': () => handlePaymentCallback(request, env),
        '/api/v1/payment/check-order': () => handleCheckOrder(request, env),
        '/api/v1/afdian/webhook': () => handleAfdianWebhook(request, env),
        '/api/v1/afdian/key': () => handleAfdianQuery(request, env),
        '/claim': () => handleClaimPage(request, env),
        '/claim/': () => handleClaimPage(request, env),
      };

      const handler = routes[path];
      if (!handler) return json({ error: 'Not Found' }, 404);

      if (request.method !== 'POST' && path !== '/api/health' && path !== '/api/v1/afdian/key' && path !== '/claim' && path !== '/claim/') {
        return json({ error: 'Method Not Allowed' }, 405);
      }

      return await handler();
    } catch (e) {
      return json({ error: e.message }, 500);
    }
  },
};

// ─── DeepSeek API 代理 ───
async function handleChat(request, env) {
  const body = await request.json();
  const { model, messages, max_tokens, temperature, top_p, frequency_penalty, presence_penalty } = body;

  if (!env.DEEPSEEK_API_KEY || env.DEEPSEEK_API_KEY.startsWith('sk-your')) {
    return json({ error: '平台 API 未配置，请联系管理员设置 DEEPSEEK_API_KEY' }, 503);
  }

  // 简单的内存限速（Worker 重启后重置，够用）
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const now = Date.now();
  const lastCall = RATE_LIMIT.get(ip);
  if (lastCall && (now - lastCall) < RATE_LIMIT_WINDOW) {
    return json({ error: '请求过于频繁，请 10 秒后再试' }, 429);
  }
  RATE_LIMIT.set(ip, now);
  // 清理过期条目
  if (RATE_LIMIT.size > 10000) {
    const cutoff = now - 60000;
    for (const [k, v] of RATE_LIMIT) {
      if (v < cutoff) RATE_LIMIT.delete(k);
    }
  }

  const resp = await fetch('https://api.deepseek.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: model || 'deepseek-chat',
      messages,
      max_tokens: max_tokens || 4096,
      temperature: temperature ?? 0.8,
      top_p: top_p ?? 0.95,
      frequency_penalty: frequency_penalty ?? 0.3,
      presence_penalty: presence_penalty ?? 0.3,
    }),
  });

  const data = await resp.json();
  return jsonRaw(data);
}

// ─── License 签名 ───
async function handleLicenseSign(request, env) {
  const body = await request.json();
  const { tier } = body;
  if (!['standard', 'professional'].includes(tier)) {
    return json({ error: '无效版本' }, 400);
  }

  const tierCode = tier === 'standard' ? 'STD' : 'PRO';
  const randomPart = crypto.randomUUID().replace(/-/g, '').slice(0, 12).toUpperCase();
  const keyData = `${tier}-${randomPart}`;
  const sig = await hmacSign(env.LICENSE_SECRET, keyData);

  return json({
    ok: true,
    key: `SF-${tierCode}-${randomPart}-${sig}`,
    tier,
  });
}

// ─── License 验证 ───
async function handleLicenseVerify(request, env) {
  const body = await request.json();
  const { key } = body;
  if (!key) return json({ error: '缺少 Key' }, 400);

  const parts = key.toUpperCase().split('-');
  if (parts.length !== 4 || parts[0] !== 'SF') {
    return json({ valid: false, error: '格式错误' });
  }

  const [, tierCode, randomPart, signature] = parts;
  const CODE_MAP = { STD: 'standard', PRO: 'professional' };
  const tier = CODE_MAP[tierCode];
  if (!tier) return json({ valid: false, error: '无效版本' });

  const keyData = `${tier}-${randomPart}`;
  const expected = await hmacSign(env.LICENSE_SECRET, keyData);

  if (signature !== expected) {
    return json({ valid: false, error: 'Key 无效' });
  }

  return json({
    valid: true,
    tier,
    features: TIER_FEATURES[tier],
  });
}

// ─── 支付订单创建 ───
async function handleCreateOrder(request, env, url) {
  const body = await request.json();
  const { tier, pay_type } = body;

  if (!PRICES[tier]) return json({ error: '无效版本' }, 400);
  const typeMap = { alipay: 'alipay', wxpay: 'wxpay', wechat: 'wxpay', native: 'wxpay' };
  if (!typeMap[pay_type]) return json({ error: '无效支付方式' }, 400);

  if (!env.MZ_KEY || env.MZ_KEY === 'your-mzpay-merchant-key') {
    return json({ error: '支付未配置，请联系管理员设置 MZ_KEY' }, 503);
  }

  const orderId = 'SF' + Date.now() + crypto.randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase();
  const origin = `${url.protocol}//${url.host}`;

  const params = {
    pid: env.MZ_PID,
    type: typeMap[pay_type],
    out_trade_no: orderId,
    notify_url: `${origin}/api/v1/payment/callback`,
    return_url: `${origin}/`,
    name: `StoryFlow ${PRICES[tier].label} License`,
    money: PRICES[tier].amount,
    sitename: 'StoryFlow',
  };

  const signStr = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&') + env.MZ_KEY;
  const md5Bytes = await crypto.subtle.digest('MD5', new TextEncoder().encode(signStr));
  params.sign = bufToHex(md5Bytes);
  params.sign_type = 'MD5';

  const formBody = new URLSearchParams(params);
  const mzResp = await fetch(env.MZ_API || 'https://pay.mymzf.com/mapi.php', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formBody,
  });
  const mzResult = await mzResp.json();

  if (mzResult.code !== 200) {
    return json({ error: `支付平台错误: ${mzResult.msg || '未知'}` }, 400);
  }

  return json({
    ok: true,
    order_id: orderId,
    amount: PRICES[tier].amount,
    tier,
    qr_url: mzResult.qrcode || mzResult.code_url || '',
  });
}

// ─── 支付回调 ───
async function handlePaymentCallback(request, env) {
  const formData = await request.formData();
  const params = Object.fromEntries(formData);

  const sign = params.sign || '';
  delete params.sign;
  delete params.sign_type;

  const signStr = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&') + env.MZ_KEY;
  const md5Bytes = await crypto.subtle.digest('MD5', new TextEncoder().encode(signStr));
  const expected = bufToHex(md5Bytes);

  if (sign.toLowerCase() !== expected.toLowerCase()) {
    return new Response('fail', { status: 400 });
  }

  // 回调验证成功——返回 success
  // 注意：无 KV 时无法自动生成 License Key
  // 需要你在后台手动为用户生成
  return new Response('success');
}

// ─── 订单查询 ───
async function handleCheckOrder(request, env) {
  return json({ error: '订单查询需要配置 KV 存储，请联系管理员' }, 501);
}

// ─── 爱发电 Webhook ───
async function handleAfdianWebhook(request, env) {
  const body = await request.json();

  if (body.ec !== 200 || !body.data || body.data.type !== 'order') {
    return json({ ec: 200, em: 'ignored' });
  }

  const order = body.data.order;
  if (order.status !== 2) {
    return json({ ec: 200, em: 'not paid' });
  }

  const outTradeNo = order.out_trade_no;
  const userName = order.user_name || '未知用户';
  const planTitle = order.plan_title || '未知方案';
  const amount = parseFloat(order.total_amount);

  const existing = await env.STORE.get(`afdian:${outTradeNo}`);
  if (existing) {
    return json({ ec: 200, em: 'ok', key: JSON.parse(existing).key });
  }

  let tier = 'standard';
  if (amount >= 189) tier = 'professional';
  else if (amount < 69) return json({ ec: 200, em: 'unknown tier' });

  const tierCN = tier === 'professional' ? '专业版' : '标准版';
  const tierCode = tier === 'standard' ? 'STD' : 'PRO';
  const randomPart = crypto.randomUUID().replace(/-/g, '').slice(0, 12).toUpperCase();
  const keyData = `${tier}-${randomPart}`;
  const sig = await hmacSign(env.LICENSE_SECRET, keyData);
  const licenseKey = `SF-${tierCode}-${randomPart}-${sig}`;

  await env.STORE.put(`afdian:${outTradeNo}`, JSON.stringify({
    key: licenseKey, tier, out_trade_no: outTradeNo, created_at: Date.now()
  }));

  // Telegram 通知
  const botToken = env.TG_BOT_TOKEN;
  const chatId = env.TG_CHAT_ID || '1072902323';
  if (botToken) {
    const msg = encodeURIComponent(
      `🛒 新订单\n━━━━━━━━━━━━\n👤 ${userName}\n📦 ${planTitle} (${tierCN})\n💰 ¥${amount}\n🆔 ${outTradeNo}\n🔑 ${licenseKey}`
    );
    try {
      await fetch(`https://api.telegram.org/bot${botToken}/sendMessage?chat_id=${chatId}&text=${msg}`, { method: 'GET' });
    } catch (_) {}
  }

  return json({ ec: 200, em: 'ok', key: licenseKey, tier });
}

// ─── 爱发电 Key 查询 ───
async function handleAfdianQuery(request, env) {
  const url = new URL(request.url);
  const outTradeNo = url.searchParams.get('out_trade_no');
  if (!outTradeNo) return json({ error: '缺少 out_trade_no' }, 400);

  const record = await env.STORE.get(`afdian:${outTradeNo}`);
  if (!record) return json({ error: '未找到' }, 404);

  return json(JSON.parse(record));
}

// ─── 爱发电订单激活验证 ───
async function handleAfdianActivate(request, env) {
  const body = await request.json();
  const orderId = (body.order_id || '').trim();
  if (!orderId) return json({ ok: false, error: '缺少订单号' });

  const record = await env.STORE.get(`afdian:${orderId}`);
  if (!record) return json({ ok: false, error: '订单号无效' });

  const data = JSON.parse(record);
  return json({
    ok: true,
    key: data.key,
    tier: data.tier,
    info: TIER_FEATURES[data.tier],
  });
}

// ─── HMAC-SHA256 签名 ───
async function hmacSign(secret, data) {
  const encoder = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    'raw', encoder.encode(secret || 'default-secret'),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sigBytes = await crypto.subtle.sign('HMAC', cryptoKey, encoder.encode(data));
  return bufToHex(sigBytes).slice(0, 24).toUpperCase();
}

// ─── 自助领取页面 ───
async function handleClaimPage(request, env) {
  const url = new URL(request.url);
  const orderId = url.searchParams.get('order_id') || '';

  let key = null;
  let tier = null;
  let found = false;
  let error = '';

  if (orderId) {
    const record = await env.STORE.get(`afdian:${orderId}`);
    if (record) {
      const data = JSON.parse(record);
      key = data.key;
      tier = data.tier === 'professional' ? '专业版' : '标准版';
      found = true;
    } else {
      error = '未找到该订单的 Key，请确认订单号正确';
    }
  }

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StoryFlow - 领取授权码</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#121218;color:#e8e8ed;min-height:100vh;display:flex;align-items:center;justify-content:center}
.box{background:#1a1a26;border:1px solid #2a2a3a;border-radius:16px;padding:40px;width:420px;max-width:90vw;text-align:center}
h1{font-size:22px;margin-bottom:6px}
.sub{color:#888;font-size:13px;margin-bottom:24px}
input{width:100%;padding:12px 16px;border-radius:10px;border:1px solid #2a2a3a;background:#121218;color:#e8e8ed;font-size:15px;outline:none;margin-bottom:12px}
input:focus{border-color:#6c5ce7}
.btn{width:100%;padding:12px;border-radius:10px;border:none;background:#6c5ce7;color:#fff;font-size:15px;cursor:pointer;transition:.15s}
.btn:hover{background:#5a4bd1}
.key-box{background:#0d0d15;border:1px solid #2a2a3a;border-radius:10px;padding:16px;margin-top:16px;word-break:break-all;font-family:monospace;font-size:14px}
.tier-badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;margin-top:12px}
.tier-badge.standard{background:#10b98120;color:#10b981;border:1px solid #10b98140}
.tier-badge.professional{background:#f59e0b20;color:#f59e0b;border:1px solid #f59e0b40}
.error{color:#ef4444;font-size:13px;margin-top:8px}
.copy-btn{background:#2a2a3a;color:#e8e8ed;border:1px solid #3a3a4a;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:13px;margin-top:12px;transition:.15s}
.copy-btn:hover{background:#3a3a4a}
.help{font-size:12px;color:#666;margin-top:20px;line-height:1.6}
</style>
</head>
<body>
<div class="box">
<h1>🔑 StoryFlow</h1>
<p class="sub">输入爱发电订单号领取授权码</p>
<form method="get" action="/claim">
<input type="text" name="order_id" placeholder="请输入订单号" value="${orderId}" required>
<button class="btn" type="submit">查询授权码</button>
</form>
${found ? `
<div class="key-box">${key}</div>
<div class="tier-badge ${tier === '专业版' ? 'professional' : 'standard'}">${tier}</div>
<button class="copy-btn" onclick="navigator.clipboard.writeText('${key}').then(()=>this.textContent='已复制！').catch(()=>{})">复制授权码</button>
` : ''}
${error ? `<div class="error">${error}</div>` : ''}
<div class="help">订单号可在爱发电 → 我的 → 购买记录 中找到</div>
</div>
</body>
</html>`;
  return new Response(html, {
    headers: { 'Content-Type': 'text/html;charset=utf-8' },
  });
}

// ─── 工具函数 ───
function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

function jsonRaw(data) {
  return new Response(JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

function bufToHex(buf) {
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

const PRICES = {
  standard: { amount: '69.00', label: '标准版' },
  professional: { amount: '189.00', label: '专业版' },
};

const TIER_FEATURES = {
  free: {
    name: '免费版', max_flows: 1, max_daily_generations: 3,
    export_formats: ['txt'], writing_styles: ['literary', 'colloquial'],
    anti_ai_level: 'basic', max_template_calls: 3, template_types: ['genre'],
  },
  standard: {
    name: '标准版', max_flows: 5, max_daily_generations: 50,
    export_formats: ['txt', 'pdf'],
    writing_styles: ['literary', 'colloquial', 'hardcore', 'poetic'],
    anti_ai_level: 'full', platform_api: true, platform_api_tokens: 1000000,
    max_template_calls: 50, template_types: ['genre', 'outline'],
  },
  professional: {
    name: '专业版', max_flows: 999, max_daily_generations: 999,
    export_formats: ['txt', 'pdf', 'epub', 'docx'],
    writing_styles: ['literary', 'colloquial', 'hardcore', 'poetic', 'custom'],
    anti_ai_level: 'custom', platform_api: true, platform_api_tokens: 5000000,
    max_template_calls: 999,
    template_types: ['genre', 'world', 'protagonist', 'outline', 'conflict', 'style',
                      'setting_detail', 'romance', 'chapter', 'characters', 'pov', 'custom'],
  },
};
