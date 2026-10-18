import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getJSON } from "./api";

export interface Loadable<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

const cache = new Map<string, { at: number; data: unknown }>();
const TTL_MS = 60_000;

/** Fetch a GET endpoint with loading/error state and a short in-memory cache. */
export function useApi<T>(path: string | null, apiKey?: string): Loadable<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>(() => {
    const hit = path && !apiKey ? cache.get(path) : undefined;
    return { data: (hit?.data as T) ?? null, error: null, loading: !!path && !hit };
  });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => {
    if (path) cache.delete(path);
    setNonce((n) => n + 1);
  }, [path]);

  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const hit = !apiKey ? cache.get(path) : undefined;
    if (hit && Date.now() - hit.at < TTL_MS && nonce === 0) {
      setState({ data: hit.data as T, error: null, loading: false });
      return;
    }
    const ctrl = new AbortController();
    setState((s) => ({ data: s.data, error: null, loading: true }));
    getJSON<T>(path, apiKey, ctrl.signal)
      .then((data) => {
        if (!apiKey) cache.set(path, { at: Date.now(), data });
        setState({ data, error: null, loading: false });
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        const msg = e instanceof ApiError ? e.message : "Could not reach the Ebola Watch API.";
        setState({ data: null, error: msg, loading: false });
      });
    return () => ctrl.abort();
  }, [path, apiKey, nonce]);

  return { ...state, reload };
}

/** Track an element's width for responsive SVG charts. */
export function useWidth<T extends HTMLElement>(initial = 640): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Ebola Watch` : "Ebola Watch";
  }, [title]);
}
