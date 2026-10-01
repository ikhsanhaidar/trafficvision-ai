import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  FileVideo,
  LoaderCircle,
} from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Job, Summary } from './types';
import { VEHICLE_CLASSES } from './types';

export const duration = (seconds: number | null | undefined) =>
  seconds == null
    ? '—'
    : seconds < 60
      ? `${seconds.toFixed(1)}s`
      : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
export const date = (value: string) =>
  new Date(value).toLocaleString('en', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
export const bytes = (value: number) =>
  `${(value / 1024 / 1024).toFixed(1)} MB`;
export const navigate = (path: string) => {
  window.location.hash = path;
};
export function Spinner({
  text = 'Loading your workspace…',
}: {
  text?: string;
}) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={24} />
      <span>{text}</span>
    </div>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <CircleAlert size={19} />
      <div>
        {message}
        {retry && (
          <button className="text-button" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <FileVideo size={28} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function Status({ status }: { status: Job['status'] }) {
  return (
    <span className={`status ${status}`}>
      <span className="status-dot" />
      {status === 'succeeded'
        ? 'Completed'
        : status[0].toUpperCase() + status.slice(1)}
    </span>
  );
}
export function PageHeading({
  eyebrow,
  title,
  text,
  action,
}: {
  eyebrow: string;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {action}
    </div>
  );
}
export function Metric({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: ReactNode;
  note: string;
  icon: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}
export function Stats({
  summaries,
  jobCount,
}: {
  summaries: Summary[];
  jobCount: number;
}) {
  const count = summaries.reduce((total, s) => total + s.crossing_total, 0);
  const seconds = summaries.reduce(
    (total, s) => total + s.processing_seconds,
    0,
  );
  const frames = summaries.reduce((total, s) => total + s.processed_frames, 0);
  return (
    <div className="metrics">
      <Metric
        label="Total crossings"
        value={count.toLocaleString()}
        note="Across completed analyses"
        icon={<ArrowRight size={19} />}
      />
      <Metric
        label="Completed analyses"
        value={summaries.length}
        note={`${jobCount} analyses in this view`}
        icon={<CheckCircle2 size={19} />}
      />
      <Metric
        label="Video analyzed"
        value={duration(
          summaries.reduce((total, s) => total + s.video.duration_seconds, 0),
        )}
        note="Source video time"
        icon={<FileVideo size={19} />}
      />
      <Metric
        label="Processing throughput"
        value={
          seconds ? (
            <>
              {(frames / seconds).toFixed(1)} <small>fps</small>
            </>
          ) : (
            '—'
          )
        }
        note="Measured frames / processing time"
        icon={<Activity size={19} />}
      />
    </div>
  );
}
export function Charts({
  summaries,
  aggregate = false,
}: {
  summaries: Summary[];
  aggregate?: boolean;
}) {
  const durationSeconds = Math.max(
    0,
    ...summaries.map((s) => s.video.duration_seconds),
  );
  const intervals = new Map<
    number,
    { time: number; 'A → B': number; 'B → A': number }
  >();
  for (let time = 0; time < durationSeconds; time += 10)
    intervals.set(time, { time, 'A → B': 0, 'B → A': 0 });
  const classes = VEHICLE_CLASSES.map((class_name) => ({
    name: class_name[0].toUpperCase() + class_name.slice(1),
    'A → B': 0,
    'B → A': 0,
  }));
  for (const summary of summaries) {
    for (const item of summary.intervals) {
      const point = intervals.get(item.start_seconds) ?? {
        time: item.start_seconds,
        'A → B': 0,
        'B → A': 0,
      };
      point[item.direction === 'A_to_B' ? 'A → B' : 'B → A'] += item.count;
      intervals.set(item.start_seconds, point);
    }
    for (const item of summary.counts) {
      const point = classes.find(
        (c) => c.name.toLowerCase() === item.class_name,
      );
      if (point)
        point[item.direction === 'A_to_B' ? 'A → B' : 'B → A'] += item.count;
    }
  }
  const data = [...intervals.values()].sort((a, b) => a.time - b.time);
  return (
    <div className="chart-grid">
      <section className="card">
        <div className="card-heading">
          <div>
            <h2>Traffic over time</h2>
            <p>
              {aggregate
                ? 'Summed across runs, aligned by elapsed video time'
                : 'Crossings by source video time'}{' '}
              · 10-second intervals
            </p>
          </div>
          <span className="pill">Crossings</span>
        </div>
        <div
          className="chart"
          role="img"
          aria-label="Crossings over video time by direction"
        >
          {summaries.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={data}
                margin={{ top: 10, right: 10, bottom: 4, left: -20 }}
              >
                <defs>
                  <linearGradient id="area-teal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#19a994" stopOpacity={0.2} />
                    <stop offset="100%" stopColor="#19a994" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="#e9eef2" />
                <XAxis
                  dataKey="time"
                  tickFormatter={(value) => `${value}s`}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: '#6f7e8b' }}
                />
                <YAxis
                  allowDecimals={false}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: '#6f7e8b' }}
                />
                <Tooltip
                  labelFormatter={(value) =>
                    `Video ${value}–${Number(value) + 10}s`
                  }
                />
                <Legend iconType="circle" iconSize={7} />
                <Area
                  type="monotone"
                  dataKey="A → B"
                  stroke="#139a87"
                  strokeWidth={2}
                  fill="url(#area-teal)"
                />
                <Area
                  type="monotone"
                  dataKey="B → A"
                  stroke="#527fe6"
                  strokeWidth={2}
                  fill="#527fe60b"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">
              Your first completed analysis will appear here.
            </div>
          )}
        </div>
      </section>
      <section className="card">
        <div className="card-heading">
          <div>
            <h2>Vehicle breakdown</h2>
            <p>Crossings per class and direction</p>
          </div>
        </div>
        <div
          className="chart"
          role="img"
          aria-label="Crossings per vehicle class and direction"
        >
          {summaries.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={classes}
                margin={{ top: 10, right: 4, bottom: 4, left: -20 }}
              >
                <CartesianGrid vertical={false} stroke="#e9eef2" />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: '#6f7e8b' }}
                />
                <YAxis
                  allowDecimals={false}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: '#6f7e8b' }}
                />
                <Tooltip />
                <Legend iconType="circle" iconSize={7} />
                <Bar
                  dataKey="A → B"
                  stackId="a"
                  fill="#20ac98"
                  maxBarSize={34}
                />
                <Bar
                  dataKey="B → A"
                  stackId="a"
                  fill="#6b8ee7"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={34}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">
              Class and direction counts will appear here.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
export function JobTable({
  jobs,
  actions,
  demo = false,
}: {
  jobs: Job[];
  actions?: (job: Job) => ReactNode;
  demo?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Video</th>
            <th>Status</th>
            <th>Crossings</th>
            <th>Duration</th>
            <th>Created</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <div className="file-cell">
                  <span className="file-icon">
                    <FileVideo size={19} />
                  </span>
                  <div>
                    {demo ? (
                      <strong>{job.filename}</strong>
                    ) : (
                      <button
                        className="file-link"
                        onClick={() => navigate(`/jobs/${job.id}`)}
                      >
                        {job.filename}
                      </button>
                    )}
                    <span className="file-meta">
                      {job.video.width} × {job.video.height} ·{' '}
                      {job.configuration.device.toUpperCase()}
                    </span>
                  </div>
                </div>
              </td>
              <td>
                <Status status={job.status} />
                {job.status === 'running' && (
                  <div className="mini-progress">
                    <span style={{ width: `${job.progress * 100}%` }} />
                  </div>
                )}
              </td>
              <td className="numeric">
                {job.summary?.crossing_total.toLocaleString() ?? '—'}
              </td>
              <td>{duration(job.video.duration_seconds)}</td>
              <td className="muted">{date(job.created_at)}</td>
              <td>
                {actions
                  ? actions(job)
                  : !demo && (
                      <button
                        className="icon-button"
                        aria-label={`Open ${job.filename}`}
                        onClick={() => navigate(`/jobs/${job.id}`)}
                      >
                        <ArrowRight size={17} />
                      </button>
                    )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function ExportLinks({ id }: { id: string }) {
  return (
    <div className="button-row">
      <a
        className="button secondary"
        href={`/api/jobs/${id}/export?format=csv`}
      >
        <ArrowDownToLine size={16} /> CSV
      </a>
      <a
        className="button secondary"
        href={`/api/jobs/${id}/export?format=json`}
      >
        <ArrowDownToLine size={16} /> JSON
      </a>
    </div>
  );
}
