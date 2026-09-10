const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

const rootDir = path.resolve(__dirname, '../..');
const fixtureBuilder = path.join(rootDir, 'tests/e2e/fixtures/build_dashboard_fixture.py');

function toFileUrl(filePath) {
  return `file://${filePath}`;
}

function buildDashboardFixture() {
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'openclaw-dashboard-'));
  const stdout = execFileSync('python3', [fixtureBuilder, outputDir], {
    cwd: rootDir,
    encoding: 'utf8',
  });
  const htmlPath = stdout.trim().split(/\r?\n/).pop();
  if (!htmlPath || !fs.existsSync(htmlPath)) {
    throw new Error(`dashboard fixture was not created: ${stdout}`);
  }
  return { outputDir, htmlPath };
}

test.describe('trade dashboard', () => {
  let fixture;

  test.beforeAll(() => {
    fixture = buildDashboardFixture();
  });

  test('renders operational KPIs and filters trade history', async ({ page }) => {
    await page.goto(toFileUrl(fixture.htmlPath));

    await expect(page.getByRole('heading', { name: 'Painel operacional de trades' })).toBeVisible();
    await expect(page.locator('#operationalTrades')).toHaveText('2');
    await expect(page.locator('#winsValue')).toHaveText('1');
    await expect(page.locator('#scannerSignals')).toHaveText('1');
    await expect(page.locator('#winRate')).toHaveText('100.0%');
    await expect(page.locator('#recentTrades')).toContainText('BTC/USDT');
    await expect(page.locator('#recentTrades')).toContainText('SOL/USDT');

    await page.getByRole('button', { name: 'Scanner' }).click();
    await expect(page.locator('#recentTrades')).toContainText('SOL/USDT');
    await expect(page.locator('#recentTrades')).not.toContainText('BTC/USDT');
  });

  test('renders the 24h cost benchmark tab', async ({ page }) => {
    await page.goto(toFileUrl(fixture.htmlPath));

    await page.getByRole('button', { name: 'Benchmark custo 24h' }).click();

    await expect(page.locator('[data-view-panel="cost"]')).toHaveClass(/active/);
    await expect(page.locator('#costWinrate')).toHaveText('100.0%');
    await expect(page.locator('#prdReport')).toContainText('A skill consegue rodar 24/7 sem LLM');

    await page.locator('#costCyclesInput').fill('10');
    await page.locator('#costInputTokens').fill('1000');
    await page.locator('#costOutputTokens').fill('200');
    await expect(page.locator('#calcMonthlyUsd')).not.toHaveText('-');
  });
});
