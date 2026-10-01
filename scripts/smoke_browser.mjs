/** Real browser + real Compose + licensed footage. Credentials never enter screenshots/logs. */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';

const base = process.env.TRAFFICVISION_SMOKE_URL || 'http://localhost:18080';
const output = 'artifacts/browser';
await mkdir(output, { recursive: true });
const credentials = JSON.parse(await readFile('artifacts/stack/credentials.json', 'utf8'));
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || (existsSync(edge) ? edge : undefined),
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(30_000);
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));
try {
  await page.goto(base);
  await page.getByLabel('Username', { exact: true }).fill(credentials.username);
  await page.getByLabel('Password', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('heading', { name: 'A clearer view of your traffic.' }).waitFor();
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'New analysis' }).click();
  await page.getByLabel('Upload video').setInputFiles('artifacts/browser/source.mp4');
  const editor = page.getByRole('application');
  await editor.waitFor({ state: 'visible', timeout: 180_000 });
  await page.waitForFunction(() => {
    const image = document.querySelector('.frame-editor img');
    return image?.complete && image.naturalWidth > 0;
  });
  const bounds = await editor.boundingBox();
  assert(bounds && bounds.width > 100 && bounds.height > 100);
  await editor.click({ position: { x: bounds.width * 0.1, y: bounds.height * 0.55 } });
  await editor.click({ position: { x: bounds.width * 0.9, y: bounds.height * 0.55 } });
  await page.getByRole('button', { name: 'Region of interest', exact: true }).click();
  for (const [x, y] of [[0.02, 0.02], [0.98, 0.02], [0.98, 0.98], [0.02, 0.98]]) {
    await editor.click({ position: { x: bounds.width * x, y: bounds.height * y } });
  }
  await page.getByRole('button', { name: 'Close region', exact: true }).click();
  await page.screenshot({ path: `${output}/new-analysis.png`, fullPage: true });
  const createdPromise = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Start analysis', exact: true }).click();
  const created = await createdPromise;
  assert.equal(created.status(), 201);
  const job = await created.json();
  assert.equal(job.configuration.roi.length, 4);
  assert(Math.abs(job.configuration.lines[0].start.x - 0.1) < 0.005);
  console.log(`Browser started real analysis ${job.id}`);
  await page.getByRole('heading', { name: 'Annotated video', exact: true }).waitFor({ timeout: 600_000 });
  const video = page.getByLabel('Annotated traffic analysis video');
  await video.evaluate(async element => { element.muted = true; await element.play(); });
  await page.waitForFunction(() => document.querySelector('video')?.currentTime > 0.5, { timeout: 30_000 });
  const videoState = await video.evaluate(element => ({ duration: element.duration, width: element.videoWidth, height: element.videoHeight, currentTime: element.currentTime }));
  assert(Math.abs(videoState.duration - job.video.duration_seconds) < 0.1);
  assert.equal(videoState.width, 640);
  await video.evaluate(element => element.pause());
  await page.screenshot({ path: `${output}/job-detail.png`, fullPage: true });
  for (const format of ['JSON', 'CSV']) {
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('link', { name: format, exact: true }).click();
    const download = await downloadPromise;
    await download.saveAs(`${output}/export.${format.toLowerCase()}`);
  }
  const exported = JSON.parse(await readFile(`${output}/export.json`, 'utf8'));
  assert.equal(exported.events.length, exported.crossing_total);
  assert.equal(exported.configuration.roi.length, 4);
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'History', exact: true }).click();
  await page.getByRole('heading', { name: 'Analysis history', exact: true }).waitFor();
  await page.screenshot({ path: `${output}/history.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300); // Allow the responsive drawer transition to settle.
  await page.screenshot({ path: `${output}/mobile-history.png`, fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  assert.deepEqual(pageErrors, []);
  const report = { status: 'passed', real_browser: true, real_model: true, real_video: true, job_id: job.id, crossings: exported.crossing_total, playback: videoState, page_errors: pageErrors };
  await writeFile(`${output}/verification.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  throw error;
} finally {
  await browser.close();
}
