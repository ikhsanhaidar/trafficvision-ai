import { useCallback, useEffect, useState } from 'react';
import { api } from './api';

export function useResource<T>(path: string | null, pollMilliseconds = 0) {
  const [resource, setResource] = useState<{
    path: string | null;
    data: T | null;
  }>({ path: null, data: null });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!path) {
      setResource({ path: null, data: null });
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let mounted = true;
    setLoading(true);
    setError('');
    async function refresh() {
      try {
        const result = await api<T>(path!, { signal: controller.signal });
        if (mounted) {
          setResource({ path, data: result });
          setError('');
        }
      } catch (error) {
        if (
          mounted &&
          !(error instanceof DOMException && error.name === 'AbortError')
        )
          setError(
            error instanceof Error ? error.message : 'Something went wrong.',
          );
      } finally {
        if (mounted) {
          setLoading(false);
          if (pollMilliseconds) timer = setTimeout(refresh, pollMilliseconds);
        }
      }
    }
    void refresh();
    return () => {
      mounted = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, pollMilliseconds, revision]);
  return {
    data: resource.path === path ? resource.data : null,
    error,
    loading: loading || Boolean(path && resource.path !== path && !error),
    reload,
  };
}
