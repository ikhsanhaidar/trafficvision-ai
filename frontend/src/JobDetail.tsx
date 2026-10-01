import { useState } from 'react';
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileVideo,
  RotateCcw,
  Square,
} from 'lucide-react';
import { post } from './api';
import { useResource } from './hooks';
import {
  Charts,
  date,
  duration,
  Empty,
  ErrorNotice,
  ExportLinks,
  Metric,
  navigate,
  PageHeading,
  Spinner,
  Status,
} from './ui';
import type { CrossingEvent, Job, Page, Summary } from './types';

function Events({ id }: { id: string }) {
  const [page, setPage] = useState(0);
  const result = useResource<Page<CrossingEvent>>(
    `/jobs/${id}/events?offset=${page * 25}&limit=25`,
  );
  return (
    <section className="card">
      <div className="card-heading">
        <div>
          <h2>Crossing events</h2>
          <p>Each event uses the source video timestamp.</p>
        </div>
        <span className="pill">{result.data?.total ?? '—'} events</span>
      </div>
      {result.loading ? (
        <Spinner text="Loading events…" />
      ) : result.error ? (
        <ErrorNotice message={result.error} retry={result.reload} />
      ) : result.data?.items.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Video time</th>
                  <th>Track ID</th>
                  <th>Vehicle class</th>
                  <th>Line</th>
                  <th>Direction</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((event, index) => (
                  <tr
                    key={`${event.track_id}-${event.line_id}-${event.direction}-${index}`}
                  >
                    <td className="numeric">
                      {event.timestamp_video.toFixed(3)}s
                    </td>
                    <td>#{event.track_id}</td>
                    <td className="capitalize">{event.class_name}</td>
                    <td>{event.line_id}</td>
                    <td>
                      <span className="direction">
                        {event.direction === 'A_to_B' ? 'A → B' : 'B → A'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span>
              Showing {page * 25 + 1}–{page * 25 + result.data.items.length} of{' '}
              {result.data.total}
            </span>
            <div className="button-row">
              <button
                className="button secondary small-button"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <button
                className="button secondary small-button"
                disabled={(page + 1) * 25 >= result.data.total}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        <Empty
          title="No crossings recorded"
          text="No eligible track crossed a counting line in this run."
        />
      )}
    </section>
  );
}

export default function JobDetail({ id }: { id: string }) {
  const result = useResource<Job>(`/jobs/${id}`, 2000);
  const job = result.data;
  const summaryResult = useResource<Summary>(
    job?.status === 'succeeded' ? `/jobs/${id}/result` : null,
  );
  const summary = summaryResult.data || job?.summary;
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [videoError, setVideoError] = useState(false);
  async function action(kind: 'cancel' | 'retry') {
    setBusy(true);
    setActionError('');
    try {
      const next = await post<Job>(`/jobs/${id}/${kind}`);
      if (next?.id && next.id !== id) navigate(`/jobs/${next.id}`);
      else result.reload();
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : 'The action failed.',
      );
    } finally {
      setBusy(false);
    }
  }
  if (!job && result.loading) return <Spinner text="Loading analysis…" />;
  if (!job)
    return (
      <ErrorNotice
        message={result.error || 'Analysis not found.'}
        retry={result.reload}
      />
    );
  const active = job.status === 'running' || job.status === 'queued';
  return (
    <>
      <button className="back-link" onClick={() => navigate('/history')}>
        <ArrowLeft size={15} /> All analyses
      </button>
      <PageHeading
        eyebrow={`ANALYSIS / ${id.slice(0, 8)}`}
        title={job.filename}
        text={`Created ${date(job.created_at)} · Attempt ${job.attempt}`}
        action={
          <div className="button-row">
            {active && (
              <button
                className="button secondary"
                disabled={busy || job.cancel_requested}
                onClick={() => {
                  void action('cancel');
                }}
              >
                <Square size={15} />
                {job.cancel_requested ? 'Cancel requested' : 'Cancel analysis'}
              </button>
            )}
            {(job.status === 'failed' || job.status === 'canceled') && (
              <button
                className="button primary"
                disabled={busy}
                onClick={() => {
                  void action('retry');
                }}
              >
                <RotateCcw size={16} /> Retry analysis
              </button>
            )}
            {job.status === 'succeeded' && <ExportLinks id={id} />}
          </div>
        }
      />
      {result.error && (
        <ErrorNotice message={result.error} retry={result.reload} />
      )}
      {actionError && <ErrorNotice message={actionError} />}
      <section className={`job-status-card ${job.status}`}>
        <div className="job-status-top">
          <div>
            <Status status={job.status} />
            <p>
              {job.status === 'queued'
                ? 'Your video is waiting for an available worker.'
                : job.status === 'running'
                  ? 'Detecting, tracking, and counting your traffic.'
                  : job.status === 'succeeded'
                    ? 'Analysis complete. Your video and crossing data are ready.'
                    : job.status === 'canceled'
                      ? 'This analysis was canceled. You can retry with the same configuration.'
                      : 'The analysis could not finish. See the error below before retrying.'}
            </p>
          </div>
          {active && (
            <strong className="progress-number">
              {Math.floor(job.progress * 100)}
              <small>%</small>
            </strong>
          )}
        </div>
        {active && (
          <>
            <progress
              value={job.progress}
              max="1"
              aria-label="Analysis progress"
            />
            <p className="small muted">
              {job.cancel_requested
                ? 'The worker will stop at its next cancellation check.'
                : 'Progress refreshes automatically every two seconds. You can leave this page.'}
            </p>
          </>
        )}
        {job.error && (
          <div className="notice error" role="alert">
            {job.error}
          </div>
        )}
      </section>
      <div className="metrics">
        <Metric
          label="Total crossings"
          value={summary?.crossing_total.toLocaleString() ?? '—'}
          note="Per line and direction"
          icon={<ArrowRight size={19} />}
        />
        <Metric
          label="Video duration"
          value={duration(job.video.duration_seconds)}
          note={`${job.video.width} × ${job.video.height} · ${job.video.fps.toFixed(2)} fps`}
          icon={<FileVideo size={19} />}
        />
        <Metric
          label="Processing time"
          value={duration(
            summary?.processing_seconds ?? job.processing_seconds,
          )}
          note="Wall-clock processing duration"
          icon={<Clock3 size={19} />}
        />
        <Metric
          label="Throughput"
          value={
            summary?.throughput_fps != null
              ? `${summary.throughput_fps.toFixed(1)} fps`
              : job.throughput_fps != null
                ? `${job.throughput_fps.toFixed(1)} fps`
                : '—'
          }
          note={`Measured on ${job.configuration.device.toUpperCase()}`}
          icon={<Activity size={19} />}
        />
      </div>
      {job.status === 'succeeded' && (
        <>
          <section className="card result-video">
            <div className="card-heading">
              <div>
                <h2>Annotated video</h2>
                <p>Vehicle classes, track IDs, geometry, and crossing count.</p>
              </div>
              <CheckCircle2 className="teal-text" size={20} />
            </div>
            <video
              controls
              preload="metadata"
              src={`/api/jobs/${id}/video`}
              onError={() => setVideoError(true)}
              aria-label="Annotated traffic analysis video"
            />
            {videoError && (
              <ErrorNotice message="This browser could not play the result video. Download it or try a browser that supports H.264." />
            )}
            <div className="video-footer">
              <span>Source timing preserved · audio omitted</span>
              <a
                href={`/api/jobs/${id}/video`}
                download
                className="text-button"
              >
                Download video
              </a>
            </div>
          </section>
          {summaryResult.error && (
            <ErrorNotice
              message={summaryResult.error}
              retry={summaryResult.reload}
            />
          )}{' '}
          {summary ? (
            <Charts summaries={[summary]} />
          ) : (
            <Spinner text="Loading crossing statistics…" />
          )}
          <Events key={id} id={id} />
        </>
      )}
      <section className="card configuration-summary">
        <div className="card-heading">
          <div>
            <h2>Run configuration</h2>
            <p>Saved with this analysis for reproducibility.</p>
          </div>
        </div>
        <dl className="details-grid">
          <div>
            <dt>Vehicle classes</dt>
            <dd>{job.configuration.classes.join(', ')}</dd>
          </div>
          <div>
            <dt>Confidence</dt>
            <dd>{Math.round(job.configuration.confidence * 100)}%</dd>
          </div>
          <div>
            <dt>Inference resolution</dt>
            <dd>{job.configuration.image_size} px</dd>
          </div>
          <div>
            <dt>Device</dt>
            <dd>{job.configuration.device}</dd>
          </div>
          <div>
            <dt>Region of interest</dt>
            <dd>
              {job.configuration.roi.length
                ? `${job.configuration.roi.length} vertices`
                : 'Entire frame'}
            </dd>
          </div>
          <div>
            <dt>Counting lines</dt>
            <dd>{job.configuration.lines.map((line) => line.id).join(', ')}</dd>
          </div>
          <div>
            <dt>Hysteresis</dt>
            <dd>{job.configuration.hysteresis ?? 0.008}</dd>
          </div>
          <div>
            <dt>Minimum track age</dt>
            <dd>{job.configuration.min_track_age ?? 3} observations</dd>
          </div>
        </dl>
        <details>
          <summary>Geometry and model metadata</summary>
          <pre>
            {JSON.stringify(
              {
                lines: job.configuration.lines,
                roi: job.configuration.roi,
                model:
                  summary?.model ?? 'Available after successful completion',
              },
              null,
              2,
            )}
          </pre>
        </details>
        <p className="info-note">
          Counts represent crossings, not unique vehicles. A track is counted at
          most once per line per direction. ID switches and returning vehicles
          can affect the result. Event times refer to the video, independently
          of processing time.
        </p>
      </section>
    </>
  );
}
