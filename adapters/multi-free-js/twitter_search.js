// Twitter/X keyword search via local Chromium + user cookie.
// Usage: node twitter_search.js "<keyword>" [limit]
// Config (env):
//   CHROMIUM_PATH   - path to a local Chrome/Chromium executable (required)
//   RSSHUB_ENV_FILE - path to a file containing `TWITTER_COOKIES=<full cookie header>`
//                     (required; the file itself is never read from this repo)
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const CHROMIUM = process.env.CHROMIUM_PATH || '';
const ENV_FILE = process.env.RSSHUB_ENV_FILE || '';

function loadCookies() {
  if (!ENV_FILE) return '';
  const text = fs.readFileSync(ENV_FILE, 'utf-8');
  for (const line of text.split('\n')) {
    if (line.startsWith('TWITTER_COOKIES=')) {
      return line.slice('TWITTER_COOKIES='.length).trim();
    }
  }
  return '';
}

function parseCookieHeader(header) {
  return header.split(';').map((pair) => {
    const idx = pair.indexOf('=');
    const name = pair.slice(0, idx).trim();
    const value = pair.slice(idx + 1).trim();
    return { name, value, domain: '.x.com', path: '/' };
  }).filter((c) => c.name);
}

async function main() {
  const keyword = process.argv[2];
  const limit = parseInt(process.argv[3] || '20', 10);
  if (!keyword) { console.error('usage: node twitter_search.js "<keyword>" [limit]'); process.exit(1); }
  const cookieHeader = loadCookies();
  if (!cookieHeader) { console.error('TWITTER_COOKIES not found. Set RSSHUB_ENV_FILE to a file containing TWITTER_COOKIES=<cookie header>'); process.exit(1); }
  if (!CHROMIUM) { console.error('CHROMIUM_PATH env not set (path to a local Chrome/Chromium executable)'); process.exit(1); }

  const browser = await chromium.launch({
    executablePath: CHROMIUM,
    headless: true,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
  });
  try {
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      locale: 'zh-CN',
    });
    await context.addCookies(parseCookieHeader(cookieHeader));
    const page = await context.newPage();
    const url = 'https://x.com/search?q=' + encodeURIComponent(keyword) + '&f=live';
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    // wait for timeline tweets to render
    await page.waitForSelector('article[data-testid="tweet"]', { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(3500);

    const tweets = await page.evaluate((maxN) => {
      const out = [];
      const articles = document.querySelectorAll('article[data-testid="tweet"]');
      for (const a of articles) {
        if (out.length >= maxN) break;
        const textEl = a.querySelector('[data-testid="tweetText"]');
        const userEl = a.querySelector('[data-testid="User-Name"]');
        const linkEl = a.querySelector('a[href*="/status/"]');
        const timeEl = a.querySelector('time');
        const stats = a.querySelector('[role="group"]');
        out.push({
          text: textEl ? textEl.innerText.replace(/\n+/g, ' ').slice(0, 300) : '',
          author: userEl ? userEl.innerText.replace(/\n+/g, ' ').slice(0, 60) : '',
          time: timeEl ? (timeEl.getAttribute('datetime') || '') : '',
          url: linkEl ? ('https://x.com' + linkEl.getAttribute('href').split('?')[0]) : '',
          stats: stats ? stats.innerText.replace(/\n+/g, ' ') : '',
        });
      }
      return out;
    }, limit);

    console.log(JSON.stringify({ ok: true, keyword, count: tweets.length, tweets }, null, 1));
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
