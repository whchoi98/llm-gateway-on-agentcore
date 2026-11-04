// PNG export per references/export.md: render the original HTML (fonts load there), screenshot each <svg>.
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
// PLAYWRIGHT_CORE: path to a playwright-core package (default: resolve 'playwright-core').
// CHROMIUM: a Chromium or chrome-headless-shell binary (default: Playwright's own download).
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const [src, outDir, lang] = process.argv.slice(2);
const names = [`architecture.${lang}`, `request-flow.${lang}`, `fallback-sequence.${lang}`, `deploy-order.${lang}`];
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
await page.goto('file://' + path.resolve(src));
await page.waitForLoadState('networkidle');
await page.evaluate(() => document.fonts.ready);
const loaded = await page.evaluate(() => [...document.fonts].filter((f) => f.status === 'loaded').map((f) => `${f.family} ${f.weight}`));
console.log('fonts loaded:', loaded.join(', '));
const svgs = page.locator('figure svg');
for (let i = 0; i < names.length; i++) {
  const out = path.join(outDir, `${names[i]}.png`);
  await svgs.nth(i).screenshot({ path: out, omitBackground: true });
  console.log('wrote', out);
}
await browser.close();
