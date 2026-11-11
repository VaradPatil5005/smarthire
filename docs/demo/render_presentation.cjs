/* Render the offline slides with the project's existing Playwright Chromium. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '../..');
const { chromium } = require(process.argv[3] || path.join(
  root, '.venv/Lib/site-packages/playwright/driver/package'));

(async () => {
  const htmlPath = path.resolve(process.argv[2] || path.join(__dirname,
    'SmartHireAI_Final_Presentation.html'));
  const review = path.join(root, '.cache/submission-audit/presentation');
  fs.mkdirSync(review, { recursive: true });
  const browser = await chromium.launch({ timeout: 15000 });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto(pathToFileURL(htmlPath).href);
  await page.evaluate(() => document.fonts.ready);
  const slideCount = await page.locator('.slide').count();
  for (let index = 0; index < slideCount; index += 1) {
    await page.screenshot({path: path.join(review,
      `slide-${String(index + 1).padStart(2, '0')}.png`)});
    if (index + 1 < slideCount) await page.keyboard.press('ArrowRight');
  }
  const lastLabel = await page.locator('#position').textContent();
  await page.keyboard.press('Home');
  const firstLabel = await page.locator('#position').textContent();
  await page.locator('#notes').click();
  const notesOpened = await page.locator('#speaker-notes').isVisible();
  await page.keyboard.press('Escape');
  const notesClosed = !(await page.locator('#speaker-notes').isVisible());
  await page.pdf({
    path: path.join(__dirname, 'SmartHireAI_Final_Presentation.pdf'),
    width: '13.333333in', height: '7.5in', preferCSSPageSize: true,
    printBackground: true, margin: { top: '0', right: '0', bottom: '0', left: '0' }
  });
  await browser.close();
  const result = {slideCount, firstLabel, lastLabel, notesOpened, notesClosed, errors};
  console.log(JSON.stringify(result));
  if (slideCount !== 10 || firstLabel !== '1 / 10' || lastLabel !== '10 / 10'
      || !notesOpened || !notesClosed || errors.length) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
