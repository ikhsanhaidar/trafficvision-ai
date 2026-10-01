import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import {
  Activity,
  ArrowRight,
  ChartNoAxesCombined,
  ChevronRight,
  CircleHelp,
  Clapperboard,
  FlaskConical,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Route,
  Settings2,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import { api, ApiError, post } from './api';
import { useResource } from './hooks';
import {
  Charts,
  Empty,
  ErrorNotice,
  JobTable,
  navigate,
  PageHeading,
  Spinner,
  Stats,
} from './ui';
import type { Job, Page, Settings } from './types';
import { demoJob, demoSummary } from './demo';
import JobDetail from './JobDetail';
import NewAnalysis from './NewAnalysis';

function Overview({ demo = false }: { demo?: boolean }) {
  const result = useResource<Page<Job>>(
    demo ? null : '/jobs?limit=100&offset=0',
    demo ? 0 : 5000,
  );
  if (!demo && result.loading && !result.data) return <Spinner />;
  if (!demo && result.error && !result.data)
    return <ErrorNotice message={result.error} retry={result.reload} />;
  const jobs = demo ? [demoJob] : (result.data?.items ?? []);
  const summaries = demo
    ? [demoSummary]
    : jobs.flatMap((job) =>
        job.status === 'succeeded' && job.summary ? [job.summary] : [],
      );
  return (
    <>
      <PageHeading
        eyebrow={demo ? 'WORKSPACE / DEMO' : 'WORKSPACE / OVERVIEW'}
        title="A clearer view of your traffic."
        text="From footage to flow. All your traffic analyses in one place."
        action={
          !demo && (
            <button className="button primary" onClick={() => navigate('/new')}>
              <Plus size={17} /> New analysis
            </button>
          )
        }
      />
      {demo && (
        <div className="notice demo-notice">
          <FlaskConical size={21} />
          <div>
            <strong>Demo · illustrative data only</strong>
            <p>
              This isolated example shows the dashboard layout. Counts and
              throughput are fictional, not model benchmarks or your analysis
              results.
            </p>
          </div>
        </div>
      )}
      {result.error && !demo && (
        <ErrorNotice message={result.error} retry={result.reload} />
      )}
      <Stats summaries={summaries} jobCount={jobs.length} />
      {!jobs.length ? (
        <section className="card start-card">
          <div className="start-visual">
            <Route size={45} />
          </div>
          <div>
            <span className="eyebrow">YOUR FIRST INSIGHT STARTS HERE</span>
            <h2>Turn a traffic video into a story.</h2>
            <p>
              Define a counting line, track the vehicles that cross it, and
              explore their direction of travel.
            </p>
            <button className="button primary" onClick={() => navigate('/new')}>
              Create your first analysis <ArrowRight size={16} />
            </button>
          </div>
        </section>
      ) : null}
      <Charts summaries={summaries} aggregate />
      <section className="card">
        <div className="card-heading">
          <div>
            <h2>Recent analyses</h2>
            <p>
              {demo
                ? 'Illustrative sample run'
                : 'Your latest uploads and their analysis status'}
            </p>
          </div>
          {!demo && (
            <button
              className="text-button"
              onClick={() => navigate('/history')}
            >
              View history <ArrowRight size={15} />
            </button>
          )}
        </div>
        {jobs.length ? (
          <JobTable jobs={jobs.slice(0, 5)} demo={demo} />
        ) : (
          <Empty
            title="No analyses yet"
            text="Completed and in-progress analyses will appear here."
          />
        )}
      </section>
      <div className="workspace-footnote">
        <ShieldCheck size={15} />
        <span>
          {!demo && (result.data?.total ?? 0) > 100
            ? 'Overview shows the latest 100 analyses. '
            : ''}
          Crossings are counted per track, line, and direction.{' '}
          {demo
            ? 'Demo data is kept separate from your workspace.'
            : 'All statistics come from completed runs.'}
        </span>
      </div>
    </>
  );
}

function HistoryPage() {
  const [page, setPage] = useState(0);
  const result = useResource<Page<Job>>(
    `/jobs?limit=10&offset=${page * 10}`,
    5000,
  );
  const [deleting, setDeleting] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const dialog = deleteDialog.current;
    if (!dialog) return;
    if (deleting) {
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
      if (deleteTrigger.current?.isConnected) deleteTrigger.current.focus();
      else document.getElementById('main-content')?.focus();
    }
  }, [deleting]);
  async function remove() {
    if (!deleting) return;
    setBusy(true);
    setError('');
    try {
      await api(`/jobs/${deleting.id}`, { method: 'DELETE' });
      deleteTrigger.current = null;
      setDeleting(null);
      if (result.data?.items.length === 1 && page > 0) setPage(page - 1);
      else result.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Deletion failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE / HISTORY"
        title="Every analysis, in one place."
        text="Revisit results, check progress, and manage your saved runs."
        action={
          <button className="button primary" onClick={() => navigate('/new')}>
            <Plus size={17} /> New analysis
          </button>
        }
      />
      {result.error && (
        <ErrorNotice message={result.error} retry={result.reload} />
      )}
      {error && <ErrorNotice message={error} />}
      <section className="card">
        <div className="card-heading">
          <div>
            <h2>Analysis history</h2>
            <p>{result.data?.total ?? 0} saved analyses</p>
          </div>
          <span className="pill">All statuses</span>
        </div>
        {result.loading && !result.data ? (
          <Spinner />
        ) : result.data?.items.length ? (
          <>
            <JobTable
              jobs={result.data.items}
              actions={(job) => (
                <div className="button-row">
                  <button
                    className="icon-button"
                    title="View analysis"
                    aria-label={`Open ${job.filename}`}
                    onClick={() => navigate(`/jobs/${job.id}`)}
                  >
                    <ArrowRight size={16} />
                  </button>
                  <button
                    className="icon-button danger-text"
                    aria-label={`Delete ${job.filename}`}
                    disabled={
                      job.status === 'running' || job.status === 'queued'
                    }
                    title={
                      job.status === 'running' || job.status === 'queued'
                        ? 'Cancel the active analysis before deleting it'
                        : 'Delete analysis'
                    }
                    onClick={(event) => {
                      deleteTrigger.current = event.currentTarget;
                      setError('');
                      setDeleting(job);
                    }}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )}
            />
            <div className="pagination">
              <span>
                Showing {page * 10 + 1}–{page * 10 + result.data.items.length}{' '}
                of {result.data.total}
              </span>
              <div className="button-row">
                <button
                  className="button secondary small-button"
                  disabled={!page}
                  onClick={() => setPage(page - 1)}
                >
                  Previous
                </button>
                <button
                  className="button secondary small-button"
                  disabled={(page + 1) * 10 >= result.data.total}
                  onClick={() => setPage(page + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        ) : (
          <Empty
            title="Your history starts with one video"
            text="Upload a clip to create your first traffic analysis."
            action={
              <button
                className="button primary"
                onClick={() => navigate('/new')}
              >
                New analysis
              </button>
            }
          />
        )}
      </section>
      <dialog
        ref={deleteDialog}
        className="modal"
        aria-labelledby="delete-title"
        aria-describedby="delete-description"
        aria-busy={busy}
        onCancel={(event) => {
          event.preventDefault();
          if (!busy) setDeleting(null);
        }}
      >
        {deleting && (
          <>
            <div className="empty-icon">
              <Trash2 size={25} />
            </div>
            <h2 id="delete-title">Delete this analysis?</h2>
            <p id="delete-description">
              This analysis of “{deleting.filename}” and its saved results will
              be permanently deleted. The uploaded source video will be
              retained. Deleting the analysis cannot be undone.
            </p>
            {error && <ErrorNotice message={error} />}
            <div className="button-row">
              <button
                className="button secondary"
                autoFocus
                disabled={busy}
                onClick={() => setDeleting(null)}
              >
                Keep analysis
              </button>
              <button
                className="button danger"
                disabled={busy}
                onClick={() => {
                  void remove();
                }}
              >
                {busy ? 'Deleting…' : 'Delete analysis'}
              </button>
            </div>
          </>
        )}
      </dialog>
    </>
  );
}

function SettingsPage({
  username,
  logout,
}: {
  username: string;
  logout: () => void;
}) {
  const result = useResource<Settings>('/settings');
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE / SETTINGS"
        title="Your analysis environment."
        text="The model, runtime limits, and counting policy used by this workspace."
      />
      {result.loading ? (
        <Spinner />
      ) : result.error || !result.data ? (
        <ErrorNotice message={result.error} retry={result.reload} />
      ) : (
        <div className="settings-layout">
          <section className="card">
            <div className="card-heading">
              <div>
                <h2>Model & processing</h2>
                <p>Managed through server configuration.</p>
              </div>
              <Activity size={20} />
            </div>
            <dl className="settings-list">
              <div>
                <dt>Checkpoint</dt>
                <dd>{result.data.checkpoint}</dd>
              </div>
              <div>
                <dt>Supported classes</dt>
                <dd>{result.data.classes.join(', ')}</dd>
              </div>
              <div>
                <dt>Available devices</dt>
                <dd>{result.data.devices.join(', ')}</dd>
              </div>
              <div>
                <dt>Default device</dt>
                <dd>{result.data.default_device}</dd>
              </div>
              <div>
                <dt>Tracking</dt>
                <dd>ByteTrack · isolated per run</dd>
              </div>
            </dl>
          </section>
          <section className="card">
            <div className="card-heading">
              <div>
                <h2>Server limits</h2>
                <p>Video uploads are validated before analysis.</p>
              </div>
              <ShieldCheck size={20} />
            </div>
            <dl className="settings-list">
              {Object.entries(result.data.limits).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll('_', ' ')}</dt>
                  <dd>
                    {typeof value === 'number' ? value.toLocaleString() : value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="card policy-card">
            <div className="card-heading">
              <div>
                <h2>What a crossing means</h2>
                <p>A transparent counting policy.</p>
              </div>
              <Route size={20} />
            </div>
            <p>
              We follow the bottom-center of each tracked vehicle. A crossing is
              recorded when its path switches sides and intersects a finite
              counting line, after the hysteresis and minimum track-age checks.
            </p>
            <p>
              Each track can count once per line in each direction during a run.
              Class labels are stabilized per track. Occlusion, ID switches, and
              vehicles re-entering the scene can affect counts.
            </p>
            <p>
              Source video timestamps determine event time. Processing
              throughput is measured separately on the selected device. Speed
              estimation requires calibration and is outside this MVP.
            </p>
          </section>
          <section className="card">
            <div className="card-heading">
              <div>
                <h2>Your session</h2>
                <p>Signed in as {username}.</p>
              </div>
              <ShieldCheck size={20} />
            </div>
            <div className="session-content">
              <p>
                Delete completed, failed, or canceled analyses from History to
                remove their saved results.
              </p>
              <button className="button secondary" onClick={logout}>
                <LogOut size={16} /> Sign out
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function Brand() {
  return (
    <div className="brand">
      <span className="brand-symbol">
        <Route size={24} />
      </span>
      <span>
        TrafficVision<span className="brand-ai">AI</span>
        <small>VIDEO INTELLIGENCE</small>
      </span>
    </div>
  );
}
function Login({
  onLogin,
  onDemo,
  initialError = '',
}: {
  onLogin: (username: string) => void;
  onDemo: () => void;
  initialError?: string;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const user = await post<{ username: string }>('/auth/login', {
        username,
        password,
      });
      onLogin(user.username);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-intro">
        <Brand />
        <div className="login-copy">
          <span className="eyebrow">FROM FOOTAGE TO FLOW</span>
          <h1>
            Every crossing.
            <br /> A clearer picture.
          </h1>
          <p>
            Detect, track, and understand vehicle movement with a focused
            workspace for traffic video analysis.
          </p>
          <div className="login-road" aria-hidden="true">
            <span />
            <span />
            <span />
            <i />
            <i />
            <i />
          </div>
          <div className="login-features">
            <span>
              <ShieldCheck size={17} /> Private workspace
            </span>
            <span>
              <ChartNoAxesCombined size={17} /> Directional insights
            </span>
          </div>
        </div>
        <span className="login-footer">
          TrafficVision AI · Video intelligence, made practical.
        </span>
      </div>
      <main className="login-main">
        <form onSubmit={login} className="login-form">
          <span className="eyebrow">WELCOME TO YOUR WORKSPACE</span>
          <h2>Sign in to TrafficVision.</h2>
          <p>Use the administrator account configured for this deployment.</p>
          {error && <ErrorNotice message={error} />}
          <label className="field">
            Username
            <input
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </label>
          <label className="field">
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <button
            className="button primary full-width"
            type="submit"
            disabled={busy}
          >
            {busy ? 'Signing in…' : 'Sign in'}
            <ArrowRight size={17} />
          </button>
          <div className="login-divider">
            <span>Just exploring?</span>
          </div>
          <button
            type="button"
            className="button secondary full-width"
            onClick={onDemo}
          >
            <FlaskConical size={16} /> Explore the demo
          </button>
          <p className="small muted">
            The demo uses clearly labeled illustrative data.
          </p>
        </form>
      </main>
    </div>
  );
}

export default function App() {
  const [username, setUsername] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState('');
  const [path, setPath] = useState(window.location.hash.slice(1) || '/');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileViewport, setMobileViewport] = useState(
    () => window.matchMedia('(max-width: 760px)').matches,
  );
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [logoutError, setLogoutError] = useState('');
  const demo = path === '/demo';
  const navigationOpen = mobileViewport && mobileOpen;
  useEffect(() => {
    const query = window.matchMedia('(max-width: 760px)');
    const resize = () => {
      if (query.matches && sidebar.current?.contains(document.activeElement))
        menuButton.current?.focus();
      setMobileViewport(query.matches);
      if (!query.matches) setMobileOpen(false);
    };
    query.addEventListener('change', resize);
    return () => query.removeEventListener('change', resize);
  }, []);
  useEffect(() => {
    if (!navigationOpen) return;
    sidebar.current?.querySelector<HTMLButtonElement>('.mobile-close')?.focus();
    return () => {
      if (menuButton.current?.getClientRects().length)
        menuButton.current.focus();
      else sidebar.current?.querySelector<HTMLAnchorElement>('nav a')?.focus();
    };
  }, [navigationOpen]);
  useEffect(() => {
    const controller = new AbortController();
    api<{ username: string }>('/auth/me', { signal: controller.signal })
      .then((user) => setUsername(user.username))
      .catch((error) => {
        if (
          !(error instanceof ApiError && error.status === 401) &&
          !(error instanceof DOMException && error.name === 'AbortError')
        )
          setAuthError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setReady(true);
      });
    const hash = () => {
      setPath(window.location.hash.slice(1) || '/');
      setMobileOpen(false);
      window.scrollTo(0, 0);
    };
    const expired = () => {
      setUsername(null);
      setMobileOpen(false);
      setAuthError('Your session has expired. Sign in to continue.');
    };
    window.addEventListener('hashchange', hash);
    window.addEventListener('session-expired', expired);
    return () => {
      controller.abort();
      window.removeEventListener('hashchange', hash);
      window.removeEventListener('session-expired', expired);
    };
  }, []);
  async function logout() {
    setLogoutError('');
    try {
      await post('/auth/logout');
      setUsername(null);
      setMobileOpen(false);
      setAuthError('');
      navigate('/');
    } catch (error) {
      setLogoutError(
        error instanceof Error ? error.message : 'Sign-out failed.',
      );
    }
  }
  if (!ready)
    return (
      <div className="app-loading">
        <Spinner />
      </div>
    );
  if (!username && !demo)
    return (
      <Login
        initialError={authError}
        onLogin={(name) => {
          setUsername(name);
          setAuthError('');
        }}
        onDemo={() => navigate('/demo')}
      />
    );
  const nav = [
    { path: '/', label: 'Overview', icon: LayoutDashboard },
    { path: '/new', label: 'New analysis', icon: Plus },
    { path: '/history', label: 'History', icon: History },
    { path: '/settings', label: 'Settings', icon: Settings2 },
  ];
  const title = path.startsWith('/jobs/')
    ? 'Analysis detail'
    : demo
      ? 'Demo workspace'
      : (nav.find((item) => item.path === path)?.label ?? 'Overview');
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        inert={navigationOpen}
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
      >
        Skip to content
      </a>
      {navigationOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          aria-hidden="true"
          tabIndex={-1}
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        id="workspace-navigation"
        ref={sidebar}
        className={`sidebar ${navigationOpen ? 'open' : ''}`}
        inert={mobileViewport && !navigationOpen}
        role={navigationOpen ? 'dialog' : undefined}
        aria-modal={navigationOpen ? true : undefined}
        aria-label={navigationOpen ? 'Workspace navigation' : undefined}
        onKeyDown={(event) => {
          if (!navigationOpen) return;
          if (event.key === 'Escape') {
            event.preventDefault();
            setMobileOpen(false);
          } else if (event.key === 'Tab') {
            const focusable = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                'a[href], button:not(:disabled)',
              ),
            ).filter((element) => element.getClientRects().length);
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <Brand />
        <button
          className="mobile-close icon-button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        >
          <X size={20} />
        </button>
        <span className="nav-section-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {nav.map(({ path: link, label, icon: Icon }) => (
            <a
              key={link}
              href={`#${link}`}
              className={
                path === link ||
                (link === '/history' && path.startsWith('/jobs/'))
                  ? 'active'
                  : ''
              }
              aria-current={path === link ? 'page' : undefined}
              onClick={() => setMobileOpen(false)}
            >
              <Icon size={19} />
              {label}
              {link === '/new' && <span className="nav-plus">+</span>}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="live-dot" />
            {demo ? 'Illustrative workspace' : 'Upload-based analysis'}
            <p>
              One video.
              <br />A new perspective.
            </p>
          </div>
          <a
            className={`demo-link ${demo ? 'active' : ''}`}
            href="#/demo"
            onClick={() => setMobileOpen(false)}
          >
            <FlaskConical size={18} /> Explore demo <ChevronRight size={14} />
          </a>
          <div className="profile">
            <span className="avatar">{username?.[0].toUpperCase() ?? 'D'}</span>
            <div>
              <strong>{username ?? 'Demo visitor'}</strong>
              <span>{demo ? 'Demo mode' : 'Administrator'}</span>
            </div>
            {username ? (
              <button
                className="icon-button"
                aria-label="Sign out"
                onClick={() => {
                  void logout();
                }}
              >
                <LogOut size={17} />
              </button>
            ) : (
              <button
                className="icon-button"
                aria-label="Go to sign in"
                onClick={() => navigate('/')}
              >
                <ArrowRight size={17} />
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="main-shell" inert={navigationOpen}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              ref={menuButton}
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              aria-controls="workspace-navigation"
              aria-expanded={navigationOpen}
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={21} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <span className={`environment ${demo ? 'is-demo' : ''}`}>
              <span className="dot" />
              {demo ? 'DEMO' : 'PRIVATE WORKSPACE'}
            </span>
            <a
              className="icon-button"
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              aria-label="Open API documentation"
            >
              <CircleHelp size={19} />
            </a>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="main-content">
          {logoutError && <ErrorNotice message={logoutError} />}{' '}
          {demo ? (
            <Overview key="demo" demo />
          ) : path === '/new' ? (
            <NewAnalysis />
          ) : path.startsWith('/jobs/') ? (
            <JobDetail key={path} id={encodeURIComponent(path.slice(6))} />
          ) : path === '/history' ? (
            <HistoryPage />
          ) : path === '/settings' ? (
            <SettingsPage
              username={username!}
              logout={() => {
                void logout();
              }}
            />
          ) : (
            <Overview key="overview" />
          )}
          <footer className="page-footer">
            <span>
              <Clapperboard size={14} /> TrafficVision AI
            </span>
            <span>Understand the movement.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
