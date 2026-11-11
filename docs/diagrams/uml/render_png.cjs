// Rasterize the <svg> of every diagram page to png/<name>.png (2x).
// Usage: node docs/diagrams/uml/render_png.cjs [--dir agentic] [file-prefix ...]
//   --dir  folder under docs/diagrams (default: uml)
// Uses the Playwright copy installed in frontend/ and the system Microsoft Edge.
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '../../../frontend/node_modules/playwright'));

(async () => {
  const args = process.argv.slice(2);
  let sub = 'uml';
  const di = args.indexOf('--dir');
  if (di >= 0) { sub = args[di + 1]; args.splice(di, 2); }
  const dir = path.join(__dirname, '..', sub);
  const outDir = path.join(dir, 'png');
  fs.mkdirSync(outDir, { recursive: true });
  const files = fs.readdirSync(dir).filter((f) => f.endsWith('.html') && f !== 'index.html')
    .filter((f) => !args.length || args.some((p) => f.startsWith(p)));
  const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'msedge' : undefined });
  const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 2400, height: 1200 } });
  for (const f of files) {
    await page.goto('file://' + path.join(dir, f).replace(/\\/g, '/'), { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    await page.evaluate(() => document.fonts.ready);
    // Wide diagrams sit in an overflow-x scroller: grow the viewport so nothing is clipped.
    const vbw = await page.evaluate(() => document.querySelector('svg').viewBox.baseVal.width);
    if (vbw + 160 > 2400) {
      await page.setViewportSize({ width: Math.ceil(vbw + 160), height: 1200 });
      await page.waitForTimeout(100);
    } else {
      await page.setViewportSize({ width: 2400, height: 1200 });
    }
    await page.locator('svg').first().screenshot({ path: path.join(outDir, f.replace(/\.html$/, '.png')) });
    console.log(`${sub}/png/` + f.replace(/\.html$/, '.png'));
  }
  await browser.close();
})();
