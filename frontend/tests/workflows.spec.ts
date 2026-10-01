import { readFile } from 'node:fs/promises';
import type { Page } from '@playwright/test';
import type { Configuration, Point } from '../src/types';
import { expect, makeJob, summary, test, video } from './mock-api';

const upload = {
  name: video.filename,
  mimeType: 'video/mp4',
  buffer: Buffer.from('mock-video-upload'),
};
const metric = (page: Page, label: string) =>
  page
    .locator('.metric')
    .filter({ has: page.getByText(label, { exact: true }) })
    .locator('.metric-value');
async function signIn(page: Page) {
  await page.getByLabel('Username', { exact: true }).fill('analyst');
  await page.getByLabel('Password', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}
async function point(page: Page, x: number, y: number) {
  const editor = page.getByRole('application', {
    name: /Video geometry editor/,
  });
  await editor.scrollIntoViewIfNeeded();
  const bounds = await editor.boundingBox();
  if (!bounds) throw new Error('Geometry editor has no visible bounds');
  await page.mouse.click(
    bounds.x + bounds.width * x,
    bounds.y + bounds.height * y,
  );
}
function normalized(actual: Point, expected: Point) {
  expect(actual.x).toBeCloseTo(expected.x, 2);
  expect(actual.y).toBeCloseTo(expected.y, 2);
}

test('sign in, upload, draw normalized geometry, and submit the selected configuration', async ({
  page,
  mockApi,
}) => {
  mockApi.authenticated = false;
  await page.goto('/');
  await signIn(page);
  await expect(
    page.getByRole('heading', { name: 'A clearer view of your traffic.' }),
  ).toBeVisible();
  expect(mockApi.matching('POST', '/auth/login')[0].postDataJSON()).toEqual({
    username: 'analyst',
    password: 'test-password',
  });
  await page.getByRole('link', { name: 'New analysis' }).click();
  await page.getByLabel('Upload video').setInputFiles(upload);
  const preview = page.getByAltText(
    'First video frame for defining counting geometry',
  );
  await expect(preview).toBeVisible();
  await expect
    .poll(() =>
      preview.evaluate((image) => (image as HTMLImageElement).naturalWidth),
    )
    .toBe(1920);
  expect(mockApi.matching('POST', '/videos')[0].postData()).toContain(
    'filename="junction.mp4"',
  );
  const start = page.getByRole('button', { name: 'Start analysis' });
  await expect(start).toBeDisabled();
  const guidance = page.locator('.geometry-guidance');
  await expect(guidance).toContainText('Draw a counting line to start');
  await expect(guidance).toContainText('Click two points on the video');
  await point(page, 0.2, 0.4);
  await expect(start).toBeDisabled();
  await expect(guidance).toContainText('First point placed');
  await point(page, 0.8, 0.4);
  await expect(start).toBeEnabled();
  await expect(guidance).toContainText('1 counting line ready');

  // Resizing between line and ROI entry catches accidental storage of display pixels.
  await page.setViewportSize({ width: 1180, height: 920 });
  await page
    .getByRole('button', { name: 'Region of interest', exact: true })
    .click();
  await point(page, 0.1, 0.2);
  await point(page, 0.9, 0.2);
  await expect(start).toBeDisabled();
  await page.getByRole('button', { name: 'Close region' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'at least three vertices',
  );
  await point(page, 0.9, 0.8);
  await point(page, 0.1, 0.8);
  await page.getByRole('button', { name: 'Close region' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'Truck', exact: true }).uncheck();
  await page.getByLabel('Inference resolution').selectOption('960');
  await start.click();
  await expect(page).toHaveURL(/#\/jobs\//);
  await expect(
    page.getByText('Your video is waiting for an available worker.'),
  ).toBeVisible();

  const submissions = mockApi.matching('POST', '/jobs');
  expect(submissions).toHaveLength(1);
  const body = submissions[0].postDataJSON() as {
    video_id: string;
    configuration: Configuration;
  };
  expect(body.video_id).toBe(video.id);
  expect(body.configuration).toMatchObject({
    classes: ['car', 'motorcycle', 'bus'],
    image_size: 960,
    device: 'cpu',
    confidence: 0.25,
  });
  expect(body.configuration.lines).toHaveLength(1);
  normalized(body.configuration.lines[0].start, { x: 0.2, y: 0.4 });
  normalized(body.configuration.lines[0].end, { x: 0.8, y: 0.4 });
  expect(body.configuration.roi).toHaveLength(4);
  [
    { x: 0.1, y: 0.2 },
    { x: 0.9, y: 0.2 },
    { x: 0.9, y: 0.8 },
    { x: 0.1, y: 0.8 },
  ].forEach((expected, index) =>
    normalized(body.configuration.roi[index], expected),
  );
});

test('running analysis requests cancellation, polls the terminal state, and retries the same job', async ({
  page,
  mockApi,
}) => {
  const job = makeJob();
  mockApi.jobs = [job];
  await page.goto(`/#/jobs/${job.id}`);
  await expect(
    page.getByRole('progressbar', { name: 'Analysis progress' }),
  ).toHaveAttribute('value', '0.37');
  await page
    .getByRole('button', { name: 'Cancel analysis', exact: true })
    .click();
  await expect(
    page.getByRole('button', { name: 'Cancel requested', exact: true }),
  ).toBeDisabled();
  expect(mockApi.matching('POST', `/jobs/${job.id}/cancel`)).toHaveLength(1);
  job.status = 'canceled';
  await page.getByRole('button', { name: 'Retry analysis' }).click();
  await expect(
    page.getByText('Your video is waiting for an available worker.'),
  ).toBeVisible();
  await expect(page.getByText(/Created .*Attempt 2/)).toBeVisible();
  await expect(
    page.getByRole('progressbar', { name: 'Analysis progress' }),
  ).toHaveAttribute('value', '0');
  await expect(
    page.getByRole('button', { name: 'Cancel analysis', exact: true }),
  ).toBeEnabled();
  await expect(page).toHaveURL(new RegExp(`#/jobs/${job.id}$`));
  expect(mockApi.matching('POST', `/jobs/${job.id}/retry`)).toHaveLength(1);
});

test('completed results show measured statistics, paginate events, and download CSV and JSON', async ({
  page,
  mockApi,
}) => {
  const job = makeJob({
    status: 'succeeded',
    progress: 1,
    summary,
    processing_seconds: 45,
    throughput_fps: 20,
  });
  mockApi.jobs = [job];
  await page.goto(`/#/jobs/${job.id}`);
  await expect(metric(page, 'Total crossings')).toHaveText('26');
  await expect(metric(page, 'Video duration')).toHaveText('30.0s');
  await expect(metric(page, 'Processing time')).toHaveText('45.0s');
  await expect(metric(page, 'Throughput')).toHaveText('20.0 fps');
  await expect(
    page.getByRole('img', {
      name: 'Crossings per vehicle class and direction',
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('cell', { name: '0.125s', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Previous', exact: true }),
  ).toBeDisabled();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByRole('cell', { name: '#26', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('cell', { name: '25.125s', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Next', exact: true }),
  ).toBeDisabled();
  expect(
    mockApi
      .matching('GET', `/jobs/${job.id}/events`)
      .some(
        (request) => new URL(request.url()).searchParams.get('offset') === '25',
      ),
  ).toBe(true);
  await expect(
    page.getByLabel('Annotated traffic analysis video'),
  ).toHaveAttribute('src', `/api/jobs/${job.id}/video`);
  await expect(
    page.getByRole('link', { name: 'Download video' }),
  ).toHaveAttribute('href', `/api/jobs/${job.id}/video`);
  await expect(page.getByRole('alert')).toContainText(
    'This browser could not play the result video',
  );
  for (const format of ['csv', 'json']) {
    const downloaded = page.waitForEvent('download');
    await page
      .getByRole('link', { name: format.toUpperCase(), exact: true })
      .click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe(
      `trafficvision-${job.id}.${format}`,
    );
    const content = await readFile((await download.path())!, 'utf8');
    if (format === 'json') expect(JSON.parse(content)).toEqual(summary);
    else expect(content).toContain('1,car,line_1,A_to_B,0.125');
  }
});

test('mobile demo stays isolated from real API data and requires sign-in for workspace actions', async ({
  page,
  mockApi,
}) => {
  mockApi.authenticated = false;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Explore the demo' }).click();
  await expect(page.getByText(/Demo .*illustrative data only/)).toBeVisible();
  await expect(metric(page, 'Total crossings')).toHaveText('48');
  await expect(
    page.getByRole('button', { name: 'New analysis', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('link', { name: 'CSV', exact: true }),
  ).toHaveCount(0);
  expect(
    mockApi.requests.every(
      (request) => new URL(request.url()).pathname === '/api/auth/me',
    ),
  ).toBe(true);
  await page
    .getByRole('button', { name: 'Open navigation', exact: true })
    .click();
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Sign in to TrafficVision.' }),
  ).toBeVisible();
  await signIn(page);
  await expect(metric(page, 'Total crossings')).toHaveText('0');
  await expect(metric(page, 'Completed analyses')).toHaveText('0');
  await expect(page.getByText(/illustrative sample/)).toHaveCount(0);
  await expect(
    page.getByText('No analyses yet', { exact: true }),
  ).toBeVisible();
  expect(mockApi.matching('GET', '/jobs').length).toBeGreaterThan(0);
});

test('authentication and upload errors stay actionable without creating an analysis', async ({
  page,
  mockApi,
}) => {
  mockApi.authenticated = false;
  await page.goto('/#/new');
  await page.getByLabel('Username', { exact: true }).fill('analyst');
  await page.getByLabel('Password', { exact: true }).fill('wrong-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Incorrect username or password.',
  );
  await signIn(page);
  mockApi.uploadError =
    'The file is not a supported, fully decodable video. Try an H.264 MP4 file.';
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(page.getByRole('alert')).toContainText(mockApi.uploadError);
  await expect(
    page.getByRole('button', { name: 'Choose video' }),
  ).toBeEnabled();
  expect(mockApi.matching('POST', '/jobs')).toHaveLength(0);
  mockApi.uploadError = '';
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(
    page.getByRole('heading', { name: 'Define where to count' }),
  ).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('the advertised upload limit rejects oversized files before sending them', async ({
  page,
  mockApi,
}) => {
  mockApi.settings.limits.max_bytes = 8;
  await page.goto('/#/new');
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(page.getByRole('alert')).toContainText('upload limit');
  expect(mockApi.matching('POST', '/videos')).toHaveLength(0);
  await expect(
    page.getByRole('button', { name: 'Choose video' }),
  ).toBeEnabled();
  await page
    .getByLabel('Upload video')
    .setInputFiles({ ...upload, buffer: Buffer.from('small') });
  await expect(
    page.getByRole('heading', { name: 'Define where to count' }),
  ).toBeVisible();
  expect(mockApi.matching('POST', '/videos')).toHaveLength(1);
});

test('changing video removes the unused upload and clears geometry', async ({
  page,
  mockApi,
}) => {
  await page.goto('/#/new');
  await expect(page.getByLabel('Upload video')).toHaveAttribute(
    'accept',
    /\.ogv/,
  );
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(
    page.getByAltText('First video frame for defining counting geometry'),
  ).toBeVisible();
  await point(page, 0.2, 0.5);
  await point(page, 0.8, 0.5);
  await page.getByRole('button', { name: 'Change video', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Choose video' }),
  ).toBeVisible();
  expect(mockApi.matching('DELETE', `/videos/${video.id}`)).toHaveLength(1);
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(
    page.getByRole('button', { name: 'Start analysis' }),
  ).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Remove line_1' })).toHaveCount(
    0,
  );
});

test('geometry can be placed with the keyboard and rejects a self-intersecting region', async ({
  page,
  mockApi,
}) => {
  mockApi.settings.classes = ['car', 'bus'];
  await page.goto('/#/new');
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(
    page.getByAltText('First video frame for defining counting geometry'),
  ).toBeVisible();
  const editor = page.getByRole('application', {
    name: /Video geometry editor/,
  });
  await editor.focus();
  await editor.press('Shift+ArrowLeft');
  await editor.press('Enter');
  await editor.press('Shift+ArrowRight');
  await editor.press('Shift+ArrowRight');
  await editor.press('Enter');
  await page
    .getByRole('button', { name: 'Region of interest', exact: true })
    .click();
  for (const [x, y] of [
    [0.1, 0.1],
    [0.9, 0.9],
    [0.9, 0.1],
    [0.1, 0.9],
  ])
    await point(page, x, y);
  await page.getByRole('button', { name: 'Close region' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'must not intersect itself',
  );
  await editor.press('Escape');
  await page.getByRole('button', { name: 'Start analysis' }).click();
  await expect(page).toHaveURL(/#\/jobs\//);
  const config = mockApi.matching('POST', '/jobs')[0].postDataJSON()
    .configuration as Configuration;
  expect(config.classes).toEqual(['car', 'bus']);
  expect(config.roi).toEqual([]);
  normalized(config.lines[0].start, { x: 0.4, y: 0.5 });
  normalized(config.lines[0].end, { x: 0.6, y: 0.5 });
});

test('desktop and mobile layouts keep content in the viewport', async ({
  page,
  mockApi,
}) => {
  const withinViewport = async () => {
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  };
  await page.goto('/#/demo');
  await expect
    .poll(() => mockApi.matching('GET', '/auth/me').length)
    .toBeGreaterThan(0);
  await expect(metric(page, 'Total crossings')).toHaveText('48');
  await expect(page.locator('.recharts-area-area').first()).toHaveAttribute(
    'd',
    /.+/,
  );
  await withinViewport();
  await page.screenshot({
    path: 'test-results/visual/desktop-demo.png',
    fullPage: true,
    animations: 'disabled',
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await withinViewport();
  await page.screenshot({
    path: 'test-results/visual/mobile-demo.png',
    fullPage: true,
    animations: 'disabled',
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/#/new');
  await expect(
    page.getByRole('button', { name: 'Choose video' }),
  ).toBeVisible();
  await page.screenshot({
    path: 'test-results/visual/desktop-upload.png',
    fullPage: true,
    animations: 'disabled',
  });
  await page.getByLabel('Upload video').setInputFiles(upload);
  await expect(
    page.getByAltText('First video frame for defining counting geometry'),
  ).toBeVisible();
  await point(page, 0.2, 0.5);
  await point(page, 0.8, 0.5);
  await withinViewport();
  await page.screenshot({
    path: 'test-results/visual/desktop-new-analysis.png',
    fullPage: true,
    animations: 'disabled',
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await withinViewport();
  await page.screenshot({
    path: 'test-results/visual/mobile-new-analysis.png',
    fullPage: true,
    animations: 'disabled',
  });
});
