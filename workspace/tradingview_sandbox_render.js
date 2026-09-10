#!/usr/bin/env node
'use strict';

/**
 * Renderiza print de trade no TradingView logado usando layout gerenciado.
 *
 * Contrato operacional atual:
 * - cada setup/timeframe ativo deve apontar para um layout gerenciado;
 * - o layout gerenciado já deve conter o Pine oficial do setup;
 * - o renderer não escolhe layout aleatório e não usa o layout manual Intus;
 * - entrada, stop e alvos são dinâmicos e vêm do payload/env do trade;
 * - linhas/labels são desenhados pela escala real do TradingView;
 * - se layout/Pine/escala falhar, a renderização falha fechada.
 */

const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');

const localRequire = createRequire(path.resolve(__dirname, '..', 'package.json'));
const { chromium } = localRequire('@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const DEFAULT_MANIFEST = path.join(ROOT, 'references', 'pine-setups', 'tradingview-managed-layouts.json');

function env(name, fallback = '') {
  return process.env[name] || fallback;
}

function boolEnv(name, fallback) {
  const raw = process.env[name];
  if (raw == null || raw === '') return Boolean(fallback);
  return ['1', 'true', 'yes', 'sim', 'on'].includes(String(raw).trim().toLowerCase());
}

function num(name, fallback) {
  const v = Number(process.env[name] || fallback);
  return Number.isFinite(v) ? v : fallback;
}

function normalizeSetup(value) {
  return String(value || '').trim().toLowerCase().replace(/_/g, '-');
}

function loadManifest() {
  const manifestPath = path.resolve(env('SETUP_NOTIFY_TRADINGVIEW_LAYOUT_MANIFEST', DEFAULT_MANIFEST));
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  return { manifestPath, manifest };
}

function resolveLayout(manifest) {
  const setupKey = normalizeSetup(
    env('SETUP_NOTIFY_TRADINGVIEW_SETUP_KEY') ||
    env('SETUP_NOTIFY_SETUP_KEY') ||
    env('SETUP_KEY') ||
    'divergence-and-volume-4h'
  );
  const layout = manifest.layouts && manifest.layouts[setupKey];
  if (!layout) throw new Error(`Layout gerenciado não cadastrado para setup ${setupKey}`);
  if (layout.status !== 'ready') {
    throw new Error(`Layout gerenciado ainda não está pronto para setup ${setupKey}: status=${layout.status || 'vazio'}`);
  }
  if (!layout.layout_url) throw new Error(`layout_url vazio para setup ${setupKey}`);
  const forbidden = manifest.contract && manifest.contract.manual_layout_forbidden;
  if (forbidden && forbidden.chart_id && String(layout.layout_url).includes(`/chart/${forbidden.chart_id}/`)) {
    throw new Error(`Layout proibido detectado: ${forbidden.name || forbidden.chart_id}`);
  }
  return { setupKey, layout };
}

function encodeSymbol(raw) {
  return encodeURIComponent(raw).replace(/%2F/g, '%2F');
}

function renderUrl(layout, symbol) {
  const encoded = encodeSymbol(symbol);
  if (String(layout.layout_url).includes('{symbol}')) return String(layout.layout_url).replaceAll('{symbol}', encoded);
  const url = new URL(layout.layout_url);
  url.searchParams.set('symbol', symbol);
  if (layout.interval) url.searchParams.set('interval', String(layout.interval));
  return url.toString();
}

const { manifestPath, manifest } = loadManifest();
const { setupKey, layout } = resolveLayout(manifest);
const defaults = manifest.defaults || {};
const profileDir = env(
  'SETUP_NOTIFY_TRADINGVIEW_PROFILE_DIR',
  String(defaults.profile_default || path.join(process.env.HOME || process.cwd(), '.openclaw/state/trade-automatizado-openclaw/tradingview-profile')).replace(/^~/, process.env.HOME || '')
);
const symbol = env('SETUP_NOTIFY_TRADINGVIEW_SYMBOL', 'BYBIT:XMRUSDT.P');
const pageUrl = renderUrl(layout, symbol);
const outputPath = env(
  'SETUP_NOTIFY_TRADINGVIEW_SANDBOX_OUTPUT',
  path.join(process.env.HOME || process.cwd(), `.openclaw/media/trade-automatizado-openclaw/${setupKey}-managed-layout-render.png`)
);
const pineTitle = env('SETUP_NOTIFY_TRADINGVIEW_SANDBOX_PINE_TITLE', layout.pine_title || '');
const allowRuntimePineInsert = boolEnv('SETUP_NOTIFY_TRADINGVIEW_ALLOW_RUNTIME_PINE_INSERT', defaults.allow_runtime_pine_insert);
const requirePineInLayout = boolEnv('SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE_IN_LAYOUT', defaults.require_pine_in_layout);
const cleanKnownContaminants = boolEnv('SETUP_NOTIFY_TRADINGVIEW_CLEAN_KNOWN_CONTAMINANTS', true);
const closeSidebars = boolEnv('SETUP_NOTIFY_TRADINGVIEW_CLOSE_SIDEBARS', defaults.close_sidebars_before_capture !== false);
const showSummaryBox = boolEnv('SETUP_NOTIFY_TRADINGVIEW_SUMMARY_BOX', false);
const clipToPane = boolEnv('SETUP_NOTIFY_TRADINGVIEW_CLIP_TO_PANE', true);
const maskBottomNav = boolEnv('SETUP_NOTIFY_TRADINGVIEW_MASK_BOTTOM_NAV', false);
const clipBottomCrop = num('SETUP_NOTIFY_TRADINGVIEW_CLIP_BOTTOM_CROP', 80);
const clipLeftCrop = num('SETUP_NOTIFY_TRADINGVIEW_CLIP_LEFT_CROP', 56);
const viewport = {
  width: num('SETUP_NOTIFY_TRADINGVIEW_WIDTH', Number(defaults.viewport && defaults.viewport.width) || 2454),
  height: num('SETUP_NOTIFY_TRADINGVIEW_HEIGHT', Number(defaults.viewport && defaults.viewport.height) || 1280),
};
const trade = {
  setup: pineTitle,
  side: env('SETUP_NOTIFY_TRADINGVIEW_SANDBOX_SIDE', 'LONG'),
  entry: num('SETUP_NOTIFY_TRADINGVIEW_SANDBOX_ENTRY', 318),
  stop: num('SETUP_NOTIFY_TRADINGVIEW_SANDBOX_STOP', 306),
  targets: env('SETUP_NOTIFY_TRADINGVIEW_SANDBOX_TARGETS', '330,336,342,348')
    .split(',')
    .map(x => Number(x.trim()))
    .filter(Number.isFinite),
};

function getModelScript() {
  return `(function(){
    const coll=window.TradingViewApi?._chartWidgetCollection || window._exposed_chartWidgetCollection;
    const activeVal=coll?._activeChartWidgetModel?._value;
    return activeVal?.m_model || activeVal?._chartWidget?.model?.() || coll?._chartModels?._value?.[0] || null;
  })()`;
}

async function sourceNames(page) {
  return page.evaluate((modelExpr) => {
    const model = eval(modelExpr);
    const sourceName = s => {
      try { return String((s.name && s.name()) || (s.title && s.title()) || s._studyName || s._name || ''); }
      catch { return ''; }
    };
    return (model && model.dataSources ? model.dataSources() : []).map(sourceName);
  }, getModelScript());
}

async function ensurePine(page) {
  const names = await sourceNames(page);
  if (names.includes(pineTitle)) return { inserted: false, names };
  if (!allowRuntimePineInsert) {
    throw new Error(`Pine esperado não está no layout gerenciado: ${pineTitle}. Layout=${layout.layout_name}`);
  }
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {
      const r = el.getBoundingClientRect();
      return { el, r, aria: el.getAttribute('aria-label') || '', data: el.getAttribute('data-name') || '' };
    }).filter(x => x.r.width > 0 && x.r.height > 0 && (x.aria === 'Pine' || x.data === 'pine-dialog-button'));
    const active = btns.find(x => /isActive/.test(x.el.className && x.el.className.toString() || ''));
    if (!active && btns[0]) btns[0].el.click();
  });
  await page.waitForTimeout(2500);
  const add = page.locator('button[title="Add to chart"], button:has-text("Add to chart")');
  for (let i = 0; i < await add.count(); i++) {
    if (await add.nth(i).isVisible().catch(() => false)) {
      await add.nth(i).click({ timeout: 5000 });
      await page.waitForTimeout(15000);
      const after = await sourceNames(page);
      if (!after.includes(pineTitle)) throw new Error(`Pine não apareceu no chart model: ${pineTitle}`);
      return { inserted: true, names: after };
    }
  }
  throw new Error('Botão Add to chart não encontrado para inserir Pine salvo');
}

async function cleanContaminants(page) {
  if (!cleanKnownContaminants) return { before: await sourceNames(page), removed: [], after: await sourceNames(page), ok: true };
  return page.evaluate(async ({ pineTitle, modelExpr }) => {
    const model = eval(modelExpr);
    const sourceName = s => {
      try { return String((s.name && s.name()) || (s.title && s.title()) || s._studyName || s._name || ''); }
      catch { return ''; }
    };
    const before = (model && model.dataSources ? model.dataSources() : []).map(sourceName);
    const contaminantRe = /CRCA Pro|Moving Average Exponential|Relative Strength Index|Slow Stochastic/i;
    const removed = [];
    for (const s of [...(model && model.dataSources ? model.dataSources() : [])]) {
      const name = sourceName(s);
      if (contaminantRe.test(name)) {
        model.removeSource(s);
        removed.push(name);
      }
    }
    await new Promise(resolve => setTimeout(resolve, 5000));
    const after = (model && model.dataSources ? model.dataSources() : []).map(sourceName);
    return { before, removed, after, ok: after.includes(pineTitle) && !after.some(n => contaminantRe.test(n)) };
  }, { pineTitle, modelExpr: getModelScript() });
}

async function closePanels(page) {
  if (!closeSidebars) return [];
  const actions = [];
  async function clickClose() {
    return page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {
        const r = el.getBoundingClientRect();
        return { el, r, aria: el.getAttribute('aria-label') || '' };
      }).filter(x => x.r.width > 0 && x.r.height > 0 && x.aria === 'Close').sort((a, b) => b.r.x - a.r.x);
      if (!btns[0]) return false;
      btns[0].el.click();
      return true;
    });
  }
  async function clickActiveRail(label) {
    return page.evaluate((label) => {
      const btns = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {
        const r = el.getBoundingClientRect();
        return { el, r, aria: el.getAttribute('aria-label') || '', cls: el.className && el.className.toString() || '' };
      }).filter(x => x.r.width > 0 && x.r.height > 0 && x.r.x > window.innerWidth - 80 && x.aria === label && /isActive/.test(x.cls));
      if (!btns[0]) return false;
      btns[0].el.click();
      return true;
    }, label);
  }
  if (await clickClose()) actions.push('close-split-view');
  await page.waitForTimeout(1200);
  if (await clickActiveRail('Watchlist, details, and news')) actions.push('close-watchlist');
  await page.waitForTimeout(1200);
  if (await clickActiveRail('Pine')) actions.push('close-pine');
  await page.waitForTimeout(1800);
  await page.mouse.move(10, 10);
  return actions;
}

async function validatePineVisible(page) {
  if (!requirePineInLayout) return { ok: true, reason: 'pine visibility not required' };
  const body = await page.evaluate(() => document.body.innerText || '');
  const names = await sourceNames(page);
  const inModel = names.includes(pineTitle);
  const inLegend = body.includes(pineTitle);
  if (!inModel || !inLegend) {
    throw new Error(`Pine não validado visualmente. inModel=${inModel} inLegend=${inLegend} pine=${pineTitle}`);
  }
  return { ok: true, inModel, inLegend };
}

async function saveLayout(page) {
  const clicked = await page.evaluate(() => {
    const candidates = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {
      const r = el.getBoundingClientRect();
      const text = (el.innerText || el.textContent || '').trim();
      return { el, r, text, aria: el.getAttribute('aria-label') || '', title: el.getAttribute('title') || '' };
    }).filter(x => x.r.width > 0 && x.r.height > 0 && x.r.y < 60 && /save/i.test([x.text, x.aria, x.title].join(' ')));
    const btn = candidates.find(x => /Save/i.test(x.text) && x.r.width >= 40) || candidates[0];
    if (!btn) return false;
    btn.el.click();
    return true;
  });
  await page.waitForTimeout(clicked ? 7000 : 2500);
  const state = await page.evaluate(() => document.body.innerText.slice(0, 800));
  return { clicked, allChangesSaved: /All changes saved/i.test(state), bodyHead: state };
}

async function cleanScreenshotChrome(page) {
  await page.keyboard.press('Escape').catch(() => {});
  await page.mouse.move(5, 5).catch(() => {});
  await page.evaluate(() => {
    const style = document.createElement('style');
    style.id = 'aspira-clean-screenshot-style';
    style.textContent = `
      [role="toolbar"],
      [data-name*="toolbar"],
      [class*="toolbar"],
      [class*="Toolbar"] {
        visibility: hidden !important;
      }
    `;
    document.head.appendChild(style);
    const hide = (el) => {
      el.dataset.aspiraHiddenForScreenshot = '1';
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
    };
    for (const el of document.querySelectorAll('div,span,section')) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const text = (el.innerText || el.textContent || '').trim();
      if (/Logged in as|Active layout:/i.test(text)) {
        hide(el);
        continue;
      }
      const buttonCount = el.querySelectorAll('button,[role="button"]').length;
      const looksLikeFloatingDrawingToolbar = r.y > 40 && r.y < 170 && r.x > 420 && r.x < window.innerWidth - 420 && r.width > 160 && r.width < 760 && r.height > 24 && r.height < 95 && buttonCount >= 3 && !/XMR|Aspira|Volume|ENTRADA|STOP|ALVO/i.test(text);
      const looksLikeBottomNavToolbar = r.y > window.innerHeight - 260 && r.x > 420 && r.x < window.innerWidth - 420 && r.width > 90 && r.width < 420 && r.height > 18 && r.height < 80 && buttonCount >= 3 && !/XMR|Aspira|Volume|ENTRADA|STOP|ALVO/i.test(text);
      if (looksLikeFloatingDrawingToolbar || looksLikeBottomNavToolbar) hide(el);
    }
    const pane = document.querySelector('[data-qa-id="pane"]');
    if (pane) {
      const pr = pane.getBoundingClientRect();
      for (const dx of [-130, -80, -30, 30, 80, 130]) {
        for (const dy of [-150, -115, -80, -45, -20]) {
          const x = pr.left + pr.width / 2 + dx;
          const y = pr.bottom + dy;
          for (const hit of document.elementsFromPoint(x, y)) {
            if (!hit || hit.id === 'aspira-final-overlay' || hit.closest?.('#aspira-final-overlay')) continue;
            let cur = hit;
            for (let depth = 0; cur && depth < 5; depth += 1, cur = cur.parentElement) {
              const cr = cur.getBoundingClientRect();
              const text = (cur.innerText || cur.textContent || '').trim();
              const buttons = cur.querySelectorAll?.('button,[role="button"]').length || 0;
              const buttonish = cur.matches?.('button,[role="button"]') || buttons >= 2;
              const centerBottomUi = buttonish && cr.y > pr.bottom - 190 && cr.y < pr.bottom + 20 && cr.x > pr.left + 120 && cr.x < pr.right - 120 && cr.width < 520 && cr.height < 120 && !/XMR|Aspira|Volume|ENTRADA|STOP|ALVO/i.test(text);
              if (centerBottomUi) hide(cur);
            }
          }
        }
      }
    }
  });
  await page.waitForTimeout(400);
}

async function injectOverlay(page) {
  return page.evaluate(({ trade, modelExpr, showSummaryBox, maskBottomNav }) => {
    document.getElementById('aspira-final-overlay')?.remove();
    const model = eval(modelExpr);
    const main = (model && typeof model.mainSeries === 'function' && model.mainSeries()) || (model && model._mainSeries);
    const priceScale = (main && typeof main.priceScale === 'function' && main.priceScale()) || (main && main._priceScale);
    const firstValue = main && typeof main.firstValue === 'function' ? main.firstValue() : main && main.firstValue;
    if (!priceScale || typeof priceScale.priceToCoordinate !== 'function') throw new Error('priceToCoordinate real indisponível');
    const pane = document.querySelector('[data-qa-id="pane"]');
    if (!pane) throw new Error('pane principal não encontrado');
    const rect = pane.getBoundingClientRect();
    const root = document.createElement('div');
    root.id = 'aspira-final-overlay';
    root.style.position = 'absolute';
    root.style.inset = '0';
    root.style.pointerEvents = 'none';
    root.style.zIndex = '2147483647';
    root.style.fontFamily = 'Arial,sans-serif';
    document.body.appendChild(root);
    const levels = [
      { label: 'ENTRADA', p: trade.entry, c: '#22c55e', w: 3 },
      { label: 'STOP', p: trade.stop, c: '#ef4444', w: 3 },
      ...trade.targets.map((p, i) => ({ label: `ALVO ${i + 1}`, p, c: '#f2c94c', w: 2 })),
    ];
    const placed = [];
    for (const level of levels) {
      const yRel = priceScale.priceToCoordinate(level.p, firstValue);
      if (!Number.isFinite(yRel)) throw new Error(`nível fora da escala visível: ${level.label} ${level.p}`);
      const yy = rect.top + yRel;
      if (yy < rect.top - 8 || yy > rect.bottom + 8) throw new Error(`nível fora do pane visível: ${level.label} ${level.p}`);
      const line = document.createElement('div');
      line.style.position = 'absolute';
      line.style.left = `${rect.left + 6}px`;
      line.style.top = `${yy}px`;
      line.style.width = `${rect.width - 18}px`;
      line.style.borderTop = `${level.w}px ${level.label.startsWith('ALVO') ? 'dashed' : 'solid'} ${level.c}`;
      line.style.boxShadow = '0 0 8px rgba(0,0,0,.75)';
      root.appendChild(line);
      const tag = document.createElement('div');
      tag.textContent = `${level.label} $${level.p.toFixed(4)}`;
      tag.style.position = 'absolute';
      tag.style.left = `${rect.right - 255}px`;
      tag.style.top = `${yy - 14}px`;
      tag.style.background = 'rgba(0,0,0,.78)';
      tag.style.border = `1px solid ${level.c}`;
      tag.style.borderRadius = '7px';
      tag.style.color = level.c;
      tag.style.font = '800 15px Arial';
      tag.style.padding = '5px 9px';
      tag.style.boxShadow = '0 0 7px rgba(0,0,0,.8)';
      root.appendChild(tag);
      placed.push({ label: level.label, price: level.p, y: yy });
    }
    if (maskBottomNav) {
      const mask = document.createElement('div');
      mask.style.position = 'absolute';
      mask.style.left = `${rect.left + rect.width / 2 - 180}px`;
      mask.style.top = `${rect.bottom - 190}px`;
      mask.style.width = '360px';
      mask.style.height = '92px';
      mask.style.background = '#131722';
      mask.style.borderRadius = '12px';
      mask.style.pointerEvents = 'none';
      root.appendChild(mask);
    }
    if (showSummaryBox) {
      const box = document.createElement('div');
      box.innerHTML = `<b>${trade.setup}</b><br>${trade.side} · Pine oficial do layout<br>Entrada ${trade.entry} · Stop ${trade.stop}<br>Alvos ${trade.targets.join(' / ')}`;
      box.style.position = 'absolute';
      box.style.left = `${rect.left + 22}px`;
      box.style.top = `${rect.top + 38}px`;
      box.style.background = 'rgba(5,7,10,.84)';
      box.style.border = '1px solid #334155';
      box.style.borderRadius = '10px';
      box.style.color = '#e8eef5';
      box.style.font = '700 15px Arial';
      box.style.padding = '10px 13px';
      box.style.boxShadow = '0 0 12px rgba(0,0,0,.65)';
      root.appendChild(box);
    }
    return placed;
  }, { trade, modelExpr: getModelScript(), showSummaryBox, maskBottomNav });
}

(async () => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const context = await chromium.launchPersistentContext(profileDir, { headless: true, viewport, colorScheme: 'dark' });
  const page = context.pages()[0] || await context.newPage();
  try {
    await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(num('SETUP_NOTIFY_TRADINGVIEW_INITIAL_WAIT_MS', 12000));
    const pine = await ensurePine(page);
    const validation = await cleanContaminants(page);
    if (!validation.ok) throw new Error(`Validação do layout falhou: ${JSON.stringify(validation)}`);
    const save = (pine.inserted || (validation.removed && validation.removed.length)) ? await saveLayout(page) : { clicked: false, skipped: true };
    const panelActions = await closePanels(page);
    const pineVisible = await validatePineVisible(page);
    const placed = await injectOverlay(page);
    await cleanScreenshotChrome(page);
    await page.waitForTimeout(1000);
    let screenshotOptions = { path: outputPath, fullPage: false };
    if (clipToPane) {
      const clip = await page.evaluate(({ clipBottomCrop, clipLeftCrop }) => {
        const pane = document.querySelector('[data-qa-id="pane"]');
        if (!pane) return null;
        const r = pane.getBoundingClientRect();
        return {
          x: Math.max(0, Math.floor(r.left + clipLeftCrop)),
          y: Math.max(0, Math.floor(r.top)),
          width: Math.max(1, Math.floor(Math.min(r.width, window.innerWidth - r.left) - clipLeftCrop)),
          height: Math.max(1, Math.floor(Math.min(r.height, window.innerHeight - r.top) - clipBottomCrop)),
        };
      }, { clipBottomCrop, clipLeftCrop });
      if (clip && clip.width > 100 && clip.height > 100) screenshotOptions = { path: outputPath, clip };
    }
    await page.screenshot(screenshotOptions);
    console.log(JSON.stringify({
      ok: true,
      manifestPath,
      setupKey,
      layoutName: layout.layout_name,
      tradingviewActualLayoutName: layout.tradingview_actual_layout_name || null,
      pageUrl,
      outputPath,
      pineTitle,
      pine,
      pineVisible,
      save,
      panelActions,
      validation,
      placed,
      viewport,
    }, null, 2));
  } finally {
    await context.close();
  }
})().catch(err => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
