// Xueqiu (雪球) hot posts / keyword search via local Chromium.
// Mode 1 (no cookie needed): hot posts list  — hot
// Mode 2 (works as guest):    keyword search — search "<keyword>"
// Usage:
//   node xueqiu_search.js hot [limit]
//   node xueqiu_search.js search "<keyword>" [limit]
// Config (env):
//   CHROMIUM_PATH   - path to a local Chrome/Chromium executable (required)
//   RSSHUB_ENV_FILE - optional path to a file with `XQ_COOKIE=<full cookie header>`;
//                     hot mode and current guest search work without it
const { chromium } = require('playwright-core');
const fs = require('fs');

const CHROMIUM = process.env.CHROMIUM_PATH || '';
const ENV_FILE = process.env.RSSHUB_ENV_FILE || '';

function loadXqCookie() {
  // optional: XQ_COOKIE=<full cookie header> line in the file at RSSHUB_ENV_FILE
  if (!ENV_FILE) return '';
  const text = fs.readFileSync(ENV_FILE, 'utf-8');
  for (const line of text.split('\n')) {
    if (line.startsWith('XQ_COOKIE=')) return line.slice('XQ_COOKIE='.length).trim();
  }
  return '';
}

async function main() {
  const mode = process.argv[2];
  const keyword = process.argv[3] || '';
  const limit = parseInt(process.argv[4] || '15', 10);
  if (!mode || (mode === 'search' && !keyword)) {
    console.error('usage: node xueqiu_search.js hot [limit] | search "<keyword>" [limit]');
    process.exit(1);
  }
  if (!CHROMIUM) { console.error('CHROMIUM_PATH env not set (path to a local Chrome/Chromium executable)'); process.exit(1); }
  const browser = await chromium.launch({
    executablePath: CHROMIUM,
    headless: false,  // aliyun WAF challenge passes reliably in headed mode
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--window-size=1280,900'],
  });
  try {
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      locale: 'zh-CN',
    });
    const xqCookie = loadXqCookie();
    if (xqCookie) {
      await context.addCookies(xqCookie.split(';').map((pair) => {
        const i = pair.indexOf('=');
        return { name: pair.slice(0, i).trim(), value: pair.slice(i + 1).trim(), domain: '.xueqiu.com', path: '/' };
      }).filter((c) => c.name));
    }
    const page = await context.newPage();
    // establish session on xueqiu.com first (aliyun WAF runs a JS challenge
    // on first hit and sets cookies; wait for it to complete)
    await page.goto('https://xueqiu.com/', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(6000);
    // if WAF challenge reloaded the page, cookies are now set; make a follow-up
    // navigation to be safe (challenge completion often triggers a reload)
    if (await page.evaluate(() => document.body && document.body.innerText.includes('renderData')).catch(() => false)) {
      await page.goto('https://xueqiu.com/', { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
      await page.waitForTimeout(3000);
    }

    let items;
    const robustFetch = async (url, referer) => {
      for (let attempt = 0; attempt < 3; attempt++) {
        const r = await page.evaluate(async ({ u, ref }) => {
          const resp = await fetch(u, { headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'Referer': ref } });
          const text = await resp.text();
          if (text.includes('renderData') || text.includes('aliyun_waf')) return { waf: true, text: text.slice(0, 120) };
          try { return { waf: false, data: JSON.parse(text) }; }
          catch { return { waf: false, text: text.slice(0, 120) }; }
        }, { u: url, ref: referer });
        if (r.waf) { await page.waitForTimeout(3000); continue; }
        return r;
      }
      return { waf: true, text: 'WAF challenge not resolved' };
    };
    if (mode === 'hot') {
      const r = await robustFetch('https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=20', 'https://xueqiu.com/');
      if (r.waf) { items = { error: 'WAF: ' + r.text }; }
      else {
        const data = r.data;
        items = (data && data.items || []).slice(0, limit).map((s) => {
          const os = s.original_status || s;
          const text = (os.description || os.text || '').replace(/<[^>]+>/g, '').trim();
          return {
            text: text.slice(0, 300),
            author: os.user ? os.user.screen_name : '',
            time: os.created_at ? new Date(os.created_at).toISOString() : '',
            url: os.id ? ('https://xueqiu.com/' + os.id) : ('https://xueqiu.com/' + s.id),
            stats: `fav=${os.fav_count ?? ''} retweet=${os.retweet_count ?? ''}`,
          };
        }).filter((x) => x.text);
      }
    } else {
      // search mode: works as guest in current API
      const r = await robustFetch('https://xueqiu.com/query/v1/search/status.json?q=' + encodeURIComponent(keyword) + '&count=20&page=1', 'https://xueqiu.com/k?q=' + encodeURIComponent(keyword));
      if (r.waf) { items = { error: 'WAF: ' + r.text }; }
      else {
        const data = r.data;
        items = (data && data.list || []).slice(0, limit).map((it) => {
          const text = (it.description || it.text || '').replace(/<[^>]+>/g, '').trim();
          return {
            text: text.slice(0, 300),
            author: it.user ? it.user.screen_name : '',
            time: it.created_at ? new Date(it.created_at).toISOString() : '',
            url: 'https://xueqiu.com' + (it.target || '/' + it.id),
            stats: `fav=${it.fav_count ?? ''} reply=${it.reply_count ?? ''}`,
          };
        }).filter((x) => x.text);
      }
    }

    console.log(JSON.stringify({ ok: true, mode, keyword, count: Array.isArray(items) ? items.length : 0, items }, null, 1));
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
