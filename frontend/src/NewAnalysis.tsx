import { useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  FileVideo,
  LoaderCircle,
  UploadCloud,
} from 'lucide-react';
import { api, post } from './api';
import GeometryEditor from './GeometryEditor';
import {
  bytes,
  duration,
  ErrorNotice,
  navigate,
  PageHeading,
  Spinner,
} from './ui';
import { useResource } from './hooks';
import type { Configuration, Job, Settings, Video } from './types';
import { VEHICLE_CLASSES } from './types';

export default function NewAnalysis() {
  const settings = useResource<Settings>('/settings');
  const fileInput = useRef<HTMLInputElement>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [geometryValid, setGeometryValid] = useState(true);
  const [config, setConfig] = useState<Configuration>({
    classes: [...VEHICLE_CLASSES],
    confidence: 0.25,
    image_size: 640,
    device: 'cpu',
    roi: [],
    lines: [],
  });
  async function upload(file?: File) {
    if (!file || busy) return;
    setError('');
    const limit = Number(settings.data?.limits.max_bytes);
    if (limit && file.size > limit) {
      setError(`This file exceeds the ${bytes(limit)} upload limit.`);
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const result = await api<Video>('/videos', {
        method: 'POST',
        body: form,
      });
      setVideo(result);
      setConfig((current) => ({
        ...current,
        classes: current.classes.filter((vehicleClass) =>
          settings.data?.classes.includes(vehicleClass),
        ),
        lines: [],
        roi: [],
        device: settings.data?.default_device ?? 'cpu',
      }));
      setGeometryValid(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Upload failed.');
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }
  async function changeVideo() {
    if (!video || busy) return;
    setBusy(true);
    setError('');
    try {
      await api(`/videos/${video.id}`, { method: 'DELETE' });
      setVideo(null);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : 'Could not remove the unused upload.',
      );
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      !video ||
      busy ||
      !config.lines.length ||
      !config.classes.length ||
      !geometryValid
    )
      return;
    setBusy(true);
    setError('');
    try {
      const job = await post<Job>('/jobs', {
        video_id: video.id,
        configuration: config,
      });
      navigate(`/jobs/${job.id}`);
    } catch (error) {
      setError(
        error instanceof Error ? error.message : 'Could not start analysis.',
      );
      setBusy(false);
    }
  }
  if (settings.loading) return <Spinner text="Loading analysis settings…" />;
  if (settings.error || !settings.data)
    return (
      <ErrorNotice
        message={settings.error || 'Settings are unavailable.'}
        retry={settings.reload}
      />
    );
  const available = settings.data.classes;
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE / NEW ANALYSIS"
        title="Make traffic make sense."
        text="Upload a video, define your counting area, and let the analysis do the rest."
      />
      <div className="steps">
        <div className={video ? 'done' : 'current'}>
          <span>{video ? <CheckCircle2 size={16} /> : '1'}</span> Upload video
        </div>
        <i />
        <div className={video ? 'current' : ''}>
          <span>2</span> Configure analysis
        </div>
        <i />
        <div>
          <span>3</span> Review results
        </div>
      </div>
      {error && <ErrorNotice message={error} />}
      {!video ? (
        <div className="upload-layout">
          <section className="card upload-card">
            <div className="card-heading">
              <div>
                <h2>Your source video</h2>
                <p>Start with footage from a stationary camera.</p>
              </div>
              <span className="step-label">STEP 01</span>
            </div>
            <div
              className={`upload-zone ${dragging ? 'dragging' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                void upload(e.dataTransfer.files[0]);
              }}
            >
              <div className="upload-icon">
                {busy ? (
                  <LoaderCircle className="spin" size={32} />
                ) : (
                  <UploadCloud size={32} />
                )}
              </div>
              <h3>
                {busy
                  ? 'Uploading and validating…'
                  : 'Drop your traffic video here'}
              </h3>
              <p>
                {busy
                  ? 'Checking the format, duration, resolution, and decoder.'
                  : 'or browse for a video on your device'}
              </p>
              <button
                className="button primary"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                <FileVideo size={17} /> Choose video
              </button>
              <p className="upload-hint">
                MP4, MOV, AVI, MKV, WebM, OGV · decoder validation required
              </p>
            </div>
            <input
              className="sr-only"
              ref={fileInput}
              type="file"
              accept="video/*,.mkv,.avi,.mov,.ogv"
              aria-label="Upload video"
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                void upload(e.target.files?.[0]);
              }}
            />
          </section>
          <aside className="card tips-card">
            <span className="eyebrow">A BETTER START</span>
            <h2>
              Good footage.
              <br /> Useful insights.
            </h2>
            <div className="tip">
              <span>01</span>
              <div>
                <h3>Keep the camera still</h3>
                <p>
                  A fixed viewpoint keeps your counting geometry consistent.
                </p>
              </div>
            </div>
            <div className="tip">
              <span>02</span>
              <div>
                <h3>Start with a short clip</h3>
                <p>
                  Confirm your line placement on 15–60 seconds before longer
                  runs.
                </p>
              </div>
            </div>
            <div className="tip">
              <span>03</span>
              <div>
                <h3>Make vehicles visible</h3>
                <p>
                  Occlusion, darkness, and small objects can reduce counting
                  accuracy.
                </p>
              </div>
            </div>
            <div className="info-note">
              Use footage you have permission to process. Uploaded files stay in
              your configured private storage.
            </div>
          </aside>
        </div>
      ) : (
        <form onSubmit={submit} className="analysis-layout">
          <div className="analysis-main">
            <section className="card">
              <div className="card-heading">
                <div>
                  <h2>Define where to count</h2>
                  <p>Draw one or more lines across the traffic flow.</p>
                </div>
                <span className="step-label">STEP 02</span>
              </div>
              <div className="video-summary">
                <FileVideo size={21} />
                <div>
                  <strong>{video.filename}</strong>
                  <span>
                    {duration(video.info.duration_seconds)} ·{' '}
                    {video.info.fps.toFixed(2)} fps ·{' '}
                    {bytes(video.info.size_bytes)}
                  </span>
                </div>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => {
                    void changeVideo();
                  }}
                >
                  Change video
                </button>
              </div>
              <GeometryEditor
                key={video.id}
                video={video}
                lines={config.lines}
                roi={config.roi}
                onChange={(lines, roi) => setConfig({ ...config, lines, roi })}
                onValidity={setGeometryValid}
              />
            </section>
          </div>
          <aside>
            <section className="card config-card">
              <div className="card-heading">
                <div>
                  <h2>Analysis settings</h2>
                  <p>Choose what to look for.</p>
                </div>
                <Cpu size={20} />
              </div>
              <fieldset>
                <legend>Vehicle classes</legend>
                <div className="class-options">
                  {VEHICLE_CLASSES.map((cls) => (
                    <label
                      key={cls}
                      className={config.classes.includes(cls) ? 'selected' : ''}
                    >
                      <input
                        type="checkbox"
                        checked={config.classes.includes(cls)}
                        disabled={!available.includes(cls) || busy}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            classes: e.target.checked
                              ? [...config.classes, cls]
                              : config.classes.filter((c) => c !== cls),
                          })
                        }
                      />
                      <span>{cls[0].toUpperCase() + cls.slice(1)}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="field">
                Confidence threshold{' '}
                <span className="field-value">
                  {Math.round(config.confidence * 100)}%
                </span>
                <input
                  type="range"
                  min="0.1"
                  max="0.95"
                  step="0.01"
                  value={config.confidence}
                  onChange={(e) =>
                    setConfig({ ...config, confidence: Number(e.target.value) })
                  }
                />
                <span className="field-help">
                  Lower values include more detections and may increase false
                  positives.
                </span>
              </label>
              <label className="field">
                Inference resolution
                <select
                  value={config.image_size}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      image_size: Number(
                        e.target.value,
                      ) as Configuration['image_size'],
                    })
                  }
                >
                  {[320, 480, 640, 960, 1280].map((size) => (
                    <option key={size} value={size}>
                      {size} px{size === 640 ? ' · balanced' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Processing device
                <select
                  value={config.device}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      device: e.target.value as Configuration['device'],
                    })
                  }
                >
                  {settings.data.devices.map((device) => (
                    <option key={device} value={device}>
                      {device === 'cpu' ? 'CPU' : 'GPU · CUDA 0'}
                    </option>
                  ))}
                </select>
                <span className="field-help">
                  Availability is verified by the worker when analysis starts.
                </span>
              </label>
              <div className="model-note">
                <span className="dot teal" />
                <div>
                  <strong>{settings.data.checkpoint}</strong>
                  <span>Configured pretrained checkpoint</span>
                </div>
              </div>
              <button
                type="submit"
                className="button primary full-width"
                disabled={
                  busy ||
                  !config.lines.length ||
                  !config.classes.length ||
                  !geometryValid
                }
              >
                {busy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <ArrowRight size={17} />
                )}{' '}
                Start analysis
              </button>
              <p className="small muted">
                {!config.lines.length
                  ? 'Click two points on the video to add a counting line.'
                  : !geometryValid
                    ? 'Finish or cancel your current drawing.'
                    : !config.classes.length
                      ? 'Select at least one vehicle class.'
                      : `${config.lines.length} counting line${config.lines.length > 1 ? 's' : ''} · ${config.roi.length ? 'Custom region' : 'Full frame'}`}
              </p>
            </section>
            <div className="info-note">
              A crossing is counted once per track, per line, per direction.
              Counts are not the number of unique vehicles.
            </div>
          </aside>
        </form>
      )}
    </>
  );
}
