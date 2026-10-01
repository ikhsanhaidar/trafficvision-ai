import { useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { MousePointer2, Pentagon, Plus, Trash2, Undo2 } from 'lucide-react';
import type { CountLine, Point, Video } from './types';

type Props = {
  video: Video;
  lines: CountLine[];
  roi: Point[];
  onChange: (lines: CountLine[], roi: Point[]) => void;
  onValidity: (valid: boolean) => void;
};
const cross = (a: Point, b: Point, p: Point) =>
  (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
function touching(a: Point, b: Point, c: Point, d: Point) {
  const on = (p: Point, q: Point, r: Point) =>
    Math.abs(cross(p, q, r)) < 1e-10 &&
    r.x >= Math.min(p.x, q.x) &&
    r.x <= Math.max(p.x, q.x) &&
    r.y >= Math.min(p.y, q.y) &&
    r.y <= Math.max(p.y, q.y);
  return (
    on(a, b, c) ||
    on(a, b, d) ||
    on(c, d, a) ||
    on(c, d, b) ||
    (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0)
  );
}
function polygonError(points: Point[]): string | null {
  if (points.length < 3)
    return 'Add at least three vertices before closing the region.';
  if (new Set(points.map((p) => `${p.x},${p.y}`)).size !== points.length)
    return 'Each region vertex must be different.';
  for (let i = 0; i < points.length; i++)
    for (let j = i + 1; j < points.length; j++) {
      if (j === i + 1 || (i === 0 && j === points.length - 1)) continue;
      if (
        touching(
          points[i],
          points[(i + 1) % points.length],
          points[j],
          points[(j + 1) % points.length],
        )
      )
        return 'The region must not intersect itself. Undo a vertex and try again.';
    }
  const area =
    Math.abs(
      points.reduce(
        (a, p, i) =>
          a +
          p.x * points[(i + 1) % points.length].y -
          points[(i + 1) % points.length].x * p.y,
        0,
      ),
    ) / 2;
  return area < 0.0001 ? 'The region must enclose a visible area.' : null;
}

export default function GeometryEditor({
  video,
  lines,
  roi,
  onChange,
  onValidity,
}: Props) {
  const [mode, setMode] = useState<'line' | 'roi'>('line');
  const [draft, setDraft] = useState<Point[]>([]);
  const [error, setError] = useState('');
  const [cursor, setCursor] = useState<Point>({ x: 0.5, y: 0.5 });
  const [imageReady, setImageReady] = useState(false);
  const [manual, setManual] = useState({ x1: 10, y1: 50, x2: 90, y2: 50 });
  const { width, height } = video.info;
  const scale = Math.min(width, height) / 600;
  function changeMode(next: 'line' | 'roi') {
    setMode(next);
    setDraft([]);
    setError('');
    onValidity(imageReady);
  }
  function addLine(start: Point, end: Point) {
    if (lines.length >= 8) {
      setError('You can add up to eight counting lines.');
      return false;
    }
    if (Math.hypot(end.x - start.x, end.y - start.y) < 0.01) {
      setError('Place the end at least 1% of the frame away from the start.');
      return false;
    }
    let index = 1;
    while (lines.some((line) => line.id === `line_${index}`)) index++;
    onChange([...lines, { id: `line_${index}`, start, end }], roi);
    setError('');
    return true;
  }
  function add(point: Point) {
    if (!imageReady) return;
    if (mode === 'line') {
      if (!draft.length) {
        setDraft([point]);
        onValidity(false);
      } else if (addLine(draft[0], point)) {
        setDraft([]);
        onValidity(true);
      }
    } else {
      if (draft.length >= 30) {
        setError(
          'The region supports up to 30 vertices. Close the region to continue.',
        );
        return;
      }
      setDraft([...draft, point]);
      onValidity(false);
      setError('');
    }
  }
  function pointer(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    add({
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    });
  }
  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    const step = event.shiftKey ? 0.1 : 0.01;
    if (event.key.startsWith('Arrow')) {
      event.preventDefault();
      setCursor((p) => ({
        x: Math.max(
          0,
          Math.min(
            1,
            p.x +
              (event.key === 'ArrowRight'
                ? step
                : event.key === 'ArrowLeft'
                  ? -step
                  : 0),
          ),
        ),
        y: Math.max(
          0,
          Math.min(
            1,
            p.y +
              (event.key === 'ArrowDown'
                ? step
                : event.key === 'ArrowUp'
                  ? -step
                  : 0),
          ),
        ),
      }));
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      add(cursor);
    } else if (event.key === 'Escape') {
      setDraft([]);
      onValidity(true);
      setError('');
    }
  }
  const toPoints = (points: Point[]) =>
    points.map((p) => `${p.x * width},${p.y * height}`).join(' ');
  return (
    <div className="geometry-editor">
      <div className="toolbar">
        <div className="segmented">
          <button
            type="button"
            aria-pressed={mode === 'line'}
            onClick={() => changeMode('line')}
          >
            <MousePointer2 size={16} /> Counting line
          </button>
          <button
            type="button"
            aria-pressed={mode === 'roi'}
            onClick={() => changeMode('roi')}
          >
            <Pentagon size={16} /> Region of interest
          </button>
        </div>
        <span className="muted small">
          {width} × {height} · original ratio
        </span>
      </div>
      <div className="geometry-guidance" role="status" aria-live="polite">
        <MousePointer2 size={18} aria-hidden="true" />
        <div>
          <strong>
            {mode === 'roi'
              ? 'Region of interest is optional'
              : draft.length
                ? 'First point placed'
                : lines.length
                  ? `${lines.length} counting line${lines.length === 1 ? '' : 's'} ready`
                  : 'Draw a counting line to start'}
          </strong>
          <p>
            {mode === 'roi'
              ? 'Click around the area, then choose Close region. Leave it empty to analyze the full frame.'
              : draft.length
                ? 'Click a second point on the video to finish the line.'
                : 'Click two points on the video: where the line starts, then where it ends.'}
          </p>
        </div>
      </div>
      <div
        className="frame-editor"
        style={{ aspectRatio: `${width}/${height}` }}
      >
        <img
          src={`/api/videos/${video.id}/preview`}
          alt="First video frame for defining counting geometry"
          onLoad={() => setImageReady(true)}
          onError={() => {
            setImageReady(false);
            setError(
              'The preview could not load. Upload the video again or check your session.',
            );
            onValidity(false);
          }}
        />
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="geometry-overlay"
          tabIndex={0}
          role="application"
          aria-label="Video geometry editor. Use arrow keys to move, Enter to place a point, Escape to cancel."
          onPointerDown={pointer}
          onKeyDown={keyboard}
        >
          <defs>
            <marker
              id="line-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8" fill="#f9cc68" />
            </marker>
          </defs>
          {roi.length > 0 && (
            <polygon
              points={toPoints(roi)}
              fill="#38d6b92c"
              stroke="#65edce"
              strokeWidth={2 * scale}
            />
          )}
          {lines.map((line) => {
            const dx = (line.end.x - line.start.x) * width,
              dy = (line.end.y - line.start.y) * height;
            const length = Math.hypot(dx, dy),
              mx = ((line.start.x + line.end.x) * width) / 2,
              my = ((line.start.y + line.end.y) * height) / 2;
            return (
              <g key={line.id}>
                <line
                  x1={line.start.x * width}
                  y1={line.start.y * height}
                  x2={line.end.x * width}
                  y2={line.end.y * height}
                  stroke="#f9cc68"
                  strokeWidth={3 * scale}
                  markerEnd="url(#line-arrow)"
                />
                <circle
                  cx={line.start.x * width}
                  cy={line.start.y * height}
                  r={4 * scale}
                  fill="#f9cc68"
                />
                <text
                  className="geometry-label"
                  x={line.start.x * width + 7 * scale}
                  y={line.start.y * height - 10 * scale}
                  fontSize={17 * scale}
                >
                  {line.id}
                </text>
                <text
                  className="geometry-label"
                  textAnchor="middle"
                  x={mx + (dy / length) * 23 * scale}
                  y={my - (dx / length) * 23 * scale + 5 * scale}
                  fontSize={18 * scale}
                >
                  A
                </text>
                <text
                  className="geometry-label"
                  textAnchor="middle"
                  x={mx - (dy / length) * 23 * scale}
                  y={my + (dx / length) * 23 * scale + 5 * scale}
                  fontSize={18 * scale}
                >
                  B
                </text>
              </g>
            );
          })}
          {draft.length > 1 && (
            <polyline
              points={toPoints(draft)}
              fill="none"
              stroke="#65edce"
              strokeDasharray={`${5 * scale}`}
              strokeWidth={2 * scale}
            />
          )}
          {draft.map((p, i) => (
            <circle
              key={i}
              cx={p.x * width}
              cy={p.y * height}
              r={5 * scale}
              fill="#65edce"
            />
          ))}
          <g className="keyboard-cursor" stroke="white" strokeWidth={2 * scale}>
            <circle
              cx={cursor.x * width}
              cy={cursor.y * height}
              r={9 * scale}
              fill="none"
            />
            <path
              d={`M${cursor.x * width - 15 * scale},${cursor.y * height}h${30 * scale} M${cursor.x * width},${cursor.y * height - 15 * scale}v${30 * scale}`}
            />
          </g>
        </svg>
      </div>
      {draft.length > 0 && (
        <div className="button-row">
          {mode === 'roi' && (
            <button
              type="button"
              className="button secondary small-button"
              onClick={() => {
                const message = polygonError(draft);
                if (message) {
                  setError(message);
                  return;
                }
                onChange(lines, draft);
                setDraft([]);
                setError('');
                onValidity(true);
              }}
            >
              Close region
            </button>
          )}
          <button
            type="button"
            className="button ghost small-button"
            onClick={() => {
              setDraft(draft.slice(0, -1));
              if (draft.length === 1) onValidity(true);
              setError('');
            }}
          >
            <Undo2 size={15} /> Undo point
          </button>
          <button
            type="button"
            className="button ghost small-button"
            onClick={() => {
              setDraft([]);
              setError('');
              onValidity(true);
            }}
          >
            Cancel drawing
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <div className="geometry-list">
        {lines.map((line) => (
          <div key={line.id} className="geometry-item">
            <span>
              <span className="dot amber" />
              {line.id} <span className="muted">· A ↔ B</span>
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label={`Remove ${line.id}`}
              onClick={() =>
                onChange(
                  lines.filter((item) => item.id !== line.id),
                  roi,
                )
              }
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {roi.length > 0 && (
          <div className="geometry-item">
            <span>
              <span className="dot teal" />
              Region · {roi.length} vertices
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label="Remove region"
              onClick={() => onChange(lines, [])}
            >
              <Trash2 size={15} />
            </button>
          </div>
        )}
      </div>
      <details className="manual-coordinates">
        <summary>Enter line coordinates manually</summary>
        <p className="small muted">
          Percentages of the original frame. Origin: top left.
        </p>
        <div className="coordinate-inputs">
          {(['x1', 'y1', 'x2', 'y2'] as const).map((key) => (
            <label key={key}>
              {key.toUpperCase()} (%)
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={manual[key]}
                onChange={(e) =>
                  setManual({ ...manual, [key]: Number(e.target.value) })
                }
              />
            </label>
          ))}
        </div>
        <button
          type="button"
          className="button secondary small-button"
          disabled={!imageReady || lines.length >= 8}
          onClick={() => {
            if (
              Object.values(manual).some(
                (v) => !Number.isFinite(v) || v < 0 || v > 100,
              )
            ) {
              setError('Coordinates must be between 0 and 100.');
              return;
            }
            addLine(
              { x: manual.x1 / 100, y: manual.y1 / 100 },
              { x: manual.x2 / 100, y: manual.y2 / 100 },
            );
          }}
        >
          <Plus size={14} /> Add line
        </button>
      </details>
      <div className="info-note">
        The arrow points from the first point to the second. Side A is the
        negative cross-product side; B is positive. For a left-to-right
        horizontal line, A is above and B is below. Counts record A → B and B →
        A separately.
      </div>
    </div>
  );
}
