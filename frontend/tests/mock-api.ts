import { expect, test as base } from '@playwright/test';
import type { Page, Request } from '@playwright/test';
import type {
  Configuration,
  CrossingEvent,
  Job,
  Settings,
  Summary,
  Video,
} from '../src/types';

export const video: Video = {
  id: '11111111-1111-4111-8111-111111111111',
  filename: 'junction.mp4',
  created_at: '2026-01-15T09:00:00Z',
  info: {
    width: 1920,
    height: 1080,
    duration_seconds: 30,
    fps: 30,
    frame_count: 900,
    codec: 'h264',
    size_bytes: 1024,
    timing: 'source_pts',
  },
};
export const configuration: Configuration = {
  classes: ['car', 'motorcycle', 'bus', 'truck'],
  confidence: 0.25,
  image_size: 640,
  device: 'cpu',
  roi: [],
  lines: [{ id: 'line_1', start: { x: 0.1, y: 0.5 }, end: { x: 0.9, y: 0.5 } }],
};
export const summary: Summary = {
  crossing_total: 26,
  processing_seconds: 45,
  throughput_fps: 20,
  processed_frames: 900,
  video: video.info,
  configuration,
  model: { checkpoint: 'yolo11n.pt' },
  interval_seconds: 10,
  notes: [],
  counts: [
    { class_name: 'car', line_id: 'line_1', direction: 'A_to_B', count: 20 },
    { class_name: 'bus', line_id: 'line_1', direction: 'B_to_A', count: 6 },
  ],
  intervals: [
    { start_seconds: 0, class_name: 'car', direction: 'A_to_B', count: 20 },
    { start_seconds: 10, class_name: 'bus', direction: 'B_to_A', count: 6 },
  ],
};
export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    video_id: video.id,
    filename: video.filename,
    status: 'running',
    configuration: structuredClone(configuration),
    video: video.info,
    progress: 0.37,
    processing_seconds: null,
    throughput_fps: null,
    created_at: video.created_at,
    started_at: video.created_at,
    finished_at: null,
    error: null,
    attempt: 1,
    summary: null,
    cancel_requested: false,
    ...overrides,
  };
}

export class MockApi {
  authenticated = true;
  jobs: Job[] = [];
  requests: Request[] = [];
  unexpected: string[] = [];
  uploadError = '';
  settings: Settings = {
    limits: {
      max_bytes: 10_000_000,
      max_duration_seconds: 600,
      max_dimension: 3840,
      max_pixels: 8_294_400,
      max_frames: 18_000,
    },
    classes: ['car', 'motorcycle', 'bus', 'truck'],
    checkpoint: 'yolo11n.pt',
    devices: ['cpu'],
    default_device: 'cpu',
  };
  events: CrossingEvent[] = Array.from({ length: 26 }, (_, index) => ({
    run_id: '22222222-2222-4222-8222-222222222222',
    track_id: index + 1,
    class_name: index < 20 ? 'car' : 'bus',
    line_id: 'line_1',
    direction: index < 20 ? 'A_to_B' : 'B_to_A',
    timestamp_video: index + 0.125,
  }));

  matching(method: string, path: string) {
    return this.requests.filter(
      (request) =>
        request.method() === method &&
        new URL(request.url()).pathname === `/api${path}`,
    );
  }

  async install(page: Page) {
    await page.context().route('**/api/**', async (route) => {
      const request = route.request();
      this.requests.push(request);
      const url = new URL(request.url());
      const path = url.pathname.slice(4);
      const method = request.method();
      const json = (body: unknown, status = 200) =>
        route.fulfill({ status, json: body });
      if (path === '/auth/me')
        return this.authenticated
          ? json({ username: 'analyst' })
          : json({ detail: 'Not authenticated.' }, 401);
      if (path === '/auth/login' && method === 'POST') {
        if (request.postDataJSON().password !== 'test-password')
          return json({ detail: 'Incorrect username or password.' }, 401);
        this.authenticated = true;
        return json({ username: 'analyst' });
      }
      if (!this.authenticated)
        return json({ detail: 'Not authenticated.' }, 401);
      if (path === '/settings') return json(this.settings);
      if (path === `/videos/${video.id}` && method === 'DELETE')
        return route.fulfill({ status: 204 });
      if (path === '/videos' && method === 'POST')
        return this.uploadError
          ? json({ detail: this.uploadError }, 422)
          : json(video, 201);
      if (path === `/videos/${video.id}/preview`)
        return route.fulfill({
          contentType: 'image/svg+xml',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#394c50"/></svg>',
        });
      if (path === '/jobs' && method === 'GET') {
        const offset = Number(url.searchParams.get('offset') || 0);
        const limit = Number(url.searchParams.get('limit') || 100);
        return json({
          items: this.jobs.slice(offset, offset + limit),
          total: this.jobs.length,
        });
      }
      if (path === '/jobs' && method === 'POST') {
        const body = request.postDataJSON() as {
          video_id: string;
          configuration: Configuration;
        };
        const job = makeJob({ status: 'queued', progress: 0, ...body });
        this.jobs.push(job);
        return json(job, 201);
      }
      const match = path.match(/^\/jobs\/([^/]+)(?:\/(.+))?$/);
      const job = this.jobs.find((item) => item.id === match?.[1]);
      const action = match?.[2];
      if (job && !action && method === 'GET') return json(job);
      if (job && action === 'cancel' && method === 'POST') {
        job.cancel_requested = true;
        if (job.status === 'queued') job.status = 'canceled';
        return json(job);
      }
      if (job && action === 'retry' && method === 'POST') {
        Object.assign(job, {
          status: 'queued',
          attempt: job.attempt + 1,
          progress: 0,
          cancel_requested: false,
          error: null,
        });
        return json(job);
      }
      if (job && action === 'result') return json(summary);
      if (job && action === 'events') {
        const offset = Number(url.searchParams.get('offset'));
        const limit = Number(url.searchParams.get('limit'));
        return json({
          items: this.events.slice(offset, offset + limit),
          total: this.events.length,
        });
      }
      if (job && action === 'export') {
        const csv = url.searchParams.get('format') === 'csv';
        return route.fulfill({
          contentType: csv ? 'text/csv' : 'application/json',
          headers: {
            'Content-Disposition': `attachment; filename="trafficvision-${job.id}.${csv ? 'csv' : 'json'}"`,
          },
          body: csv
            ? 'track_id,class_name,line_id,direction,timestamp_video\n1,car,line_1,A_to_B,0.125\n'
            : JSON.stringify(summary),
        });
      }
      // Media decoding is covered by backend integration tests; these tests verify its URL and fallback.
      if (job && action === 'video')
        return route.fulfill({
          status: 404,
          json: { detail: 'Mock video unavailable.' },
        });
      this.unexpected.push(`${method} ${path}`);
      return json(
        { detail: `Unexpected mock request: ${method} ${path}` },
        500,
      );
    });
  }
}

export const test = base.extend<{ mockApi: MockApi }>({
  mockApi: async ({ page }, use) => {
    const api = new MockApi();
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await api.install(page);
    await use(api);
    expect(
      api.unexpected,
      'Every API request should have an explicit mock',
    ).toEqual([]);
    expect(errors, 'The application should not throw browser errors').toEqual(
      [],
    );
  },
});
export { expect } from '@playwright/test';
