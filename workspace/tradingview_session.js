#!/usr/bin/env node
'use strict';

const { createRequire } = require('module');
const path = require('path');

const localRequire = createRequire(path.resolve(__dirname, '..', 'package.json'));
let chromium;
try {
  chromium = localRequire('@playwright/test').chromium;
} catch (err) {
  const mod = process.env.SETUP_NOTIFY_PLAYWRIGHT_NODE_MODULE || '';
  if (!mod) throw err;
  const loaded = require(mod);
  chromium = loaded.chromium || require(path.join(mod, 'index.js')).chromium;
}

function arg(name, fallback = '') {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx >= 0 && process.argv[idx + 1]) return process.argv[idx + 1];
  return fallback;
}

async function main() {
  const action = process.argv[2] || 'check';
  const profileDir = arg('profile-dir', process.env.SETUP_NOTIFY_TRADINGVIEW_PROFILE_DIR || path.join(process.env.HOME || process.cwd(), '.openclaw/state/trade-automatizado-openclaw/tradingview-profile'));
  const headless = (arg('headless', process.env.TRADINGVIEW_SESSION_HEADLESS || (action === 'login' ? 'false' : 'true')).toLowerCase() !== 'false');
  const timeoutMs = Number(arg('timeout-ms', process.env.TRADINGVIEW_SESSION_TIMEOUT_MS || '180000'));
  const context = await chromium.launchPersistentContext(profileDir, {
    headless,
    viewport: { width: 1440, height: 960 },
    colorScheme: 'dark',
  });
  try {
    const page = context.pages()[0] || await context.newPage();
    await page.goto('https://www.tradingview.com/', { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (action === 'login') {
      console.error('Login assistido aberto. Conclua o login no navegador e mantenha a janela aberta até a validação terminar.');
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        const loggedIn = await isLoggedIn(page, context);
        if (loggedIn.ok) {
          console.log(JSON.stringify({ ok: true, action, profileDir, loggedIn: true, signals: loggedIn.signals }, null, 2));
          return;
        }
        await page.waitForTimeout(3000);
      }
      throw new Error('login TradingView nao validado antes do timeout');
    }
    if (action === 'login-auto') {
      await loginWithCredentials(page, context, timeoutMs);
      const loggedIn = await isLoggedIn(page, context);
      console.log(JSON.stringify({ ok: loggedIn.ok, action, profileDir, loggedIn: loggedIn.ok, signals: loggedIn.signals }, null, 2));
      if (!loggedIn.ok) process.exitCode = 2;
      return;
    }
    const loggedIn = await isLoggedIn(page, context);
    console.log(JSON.stringify({ ok: loggedIn.ok, action, profileDir, loggedIn: loggedIn.ok, signals: loggedIn.signals }, null, 2));
    if (!loggedIn.ok) process.exitCode = 2;
  } finally {
    await context.close();
  }
}

async function loginWithCredentials(page, context, timeoutMs) {
  const username = process.env.TRADINGVIEW_USERNAME || process.env.TRADINGVIEW_EMAIL || '';
  const password = process.env.TRADINGVIEW_PASSWORD || '';
  if (!username || !password) throw new Error('TRADINGVIEW_USERNAME/TRADINGVIEW_PASSWORD ausentes no ambiente');
  const deadline = Date.now() + timeoutMs;
  await page.goto('https://www.tradingview.com/accounts/signin/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  let loggedIn = await isLoggedIn(page, context);
  if (loggedIn.ok) return;
  await clickFirst(page, [
    'button[name="Email"]',
    'button:has-text("Email")',
    'button:has-text("E-mail")',
    '[data-name="email-signin-button"]',
    'text=/^Email$/i',
    'text=/^E-mail$/i',
  ], 12000).catch(async () => {
    await clickFirst(page, [
      'button:has-text("Show more options")',
      'button:has-text("Mostrar mais opções")',
      'button:has-text("Mais opções")',
    ], 5000).catch(() => {});
    await clickFirst(page, [
      'button[name="Email"]',
      'button:has-text("Email")',
      'button:has-text("E-mail")',
      '[data-name="email-signin-button"]',
      'text=/^Email$/i',
      'text=/^E-mail$/i',
    ], 12000);
  });
  const userInput = await fillFirst(page, [
    'input[name="id_username"]',
    'input#id_username',
    'input[name="username"]',
    'input[name="email"]',
    'input[type="email"]',
    'input[autocomplete="username"]',
  ], username, 10000);
  const passInput = await fillFirst(page, [
    'input[name="id_password"]',
    'input#id_password',
    'input[name="password"]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
  ], password, 10000);
  if (!userInput || !passInput) throw new Error('campos de login TradingView nao encontrados');
  await clickFirst(page, [
    'button[type="submit"]',
    'button:has-text("Sign in")',
    'button:has-text("Entrar")',
    'text=/^Sign in$/i',
    'text=/^Entrar$/i',
  ], 10000);
  while (Date.now() < deadline) {
    loggedIn = await isLoggedIn(page, context);
    if (loggedIn.ok) return;
    const challenge = await page.evaluate(() => /captcha|verification|2fa|two-factor|código|verifica/i.test(document.body?.innerText || ''));
    if (challenge) throw new Error('TradingView exigiu captcha/2FA/verificacao manual; login automatico interrompido');
    await page.waitForTimeout(3000);
  }
  throw new Error('login automatico TradingView nao validado antes do timeout');
}

async function clickFirst(page, selectors, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const loc = page.locator(selector).first();
      if (await loc.count().catch(() => 0)) {
        try { await loc.click({ timeout: 1500 }); return true; } catch (_) {}
      }
    }
    await page.waitForTimeout(300);
  }
  throw new Error('elemento nao encontrado: ' + selectors.join(' | '));
}

async function fillFirst(page, selectors, value, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const loc = page.locator(selector).first();
      if (await loc.count().catch(() => 0)) {
        try { await loc.fill(value, { timeout: 1500 }); return true; } catch (_) {}
      }
    }
    await page.waitForTimeout(300);
  }
  return false;
}

async function isLoggedIn(page, context) {
  const cookies = await context.cookies('https://www.tradingview.com/');
  const cookieNames = cookies.map(c => c.name).sort();
  const hasSessionCookie = cookieNames.some(name => /session|auth|id_token/i.test(name));
  const dom = await page.evaluate(() => {
    const signInButton = Boolean(document.querySelector('button[data-name="header-user-menu-sign-in"], [data-name="header-user-menu-sign-in"]'));
    const userMenu = Boolean(document.querySelector('[data-name="header-user-menu"], button[aria-label*="menu" i], button[aria-label*="profile" i]'));
    const bodyText = document.body ? document.body.innerText.slice(0, 3000) : '';
    return { signInButton, userMenu, textHasSignIn: /sign in|entrar/i.test(bodyText) };
  });
  return {
    ok: hasSessionCookie && !dom.signInButton,
    signals: {
      cookieNames,
      hasSessionCookie,
      signInButtonVisible: dom.signInButton,
      userMenuVisible: dom.userMenu,
      textHasSignIn: dom.textHasSignIn,
    },
  };
}

main().catch(err => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
