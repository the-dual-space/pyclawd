// React Query hooks over the REST API, plus the SSE live-refresh subscription.
// Server state lives here; UI state lives in the store (store.tsx).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type StreamEvent } from "@/api";

/**
 * Drive an agent SSE stream: accumulate its progress events, track a running flag,
 * and expose an abort handle. Shared by the review-tray agent modal (AgentPanel) and
 * the inline comment-reply runner (ReplyRunner), which had copied this wiring.
 *
 * `start(stream, onEvent)` opens a new run: `stream(onEvent, signal)` is the actual
 * SSE call (e.g. `streamAgent`/`streamReply`). When `onEvent` is omitted each event is
 * appended to `events`; when provided, the caller decides what to do with each event
 * (append via the returned `setEvents`, capture a session id / comment frame, …). A
 * non-abort error is appended as an `error` event; `abort()` stops the current run.
 */
export function useAgentStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(
    (
      stream: (onEvent: (e: StreamEvent) => void, signal: AbortSignal) => Promise<void>,
      onEvent?: (e: StreamEvent) => void,
    ) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setRunning(true);
      stream((e) => (onEvent ? onEvent(e) : setEvents((prev) => [...prev, e])), controller.signal)
        .catch((err) => {
          if (err?.name !== "AbortError")
            setEvents((prev) => [...prev, { kind: "error", text: String(err?.message ?? err) }]);
        })
        .finally(() => setRunning(false));
    },
    [],
  );

  const abort = useCallback(() => abortRef.current?.abort(), []);

  return { events, setEvents, running, start, abort };
}

/** A piece of state backed by localStorage — for layout prefs like panel sizes. */
export function usePersisted<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw !== null ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* ignore quota/availability errors */
      }
    },
    [key],
  );
  return [value, set];
}

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: api.projects });
}

export function useRefs(project: string | null) {
  return useQuery({
    queryKey: ["refs", project],
    queryFn: () => api.refs(project!),
    enabled: !!project,
  });
}

export function useChanges(
  project: string | null,
  base: string,
  target: string,
  all: boolean,
) {
  return useQuery({
    queryKey: ["changes", project, base, target, all],
    queryFn: () => api.changes(project!, base, target, all),
    enabled: !!project,
  });
}

export function useDiff(
  project: string | null,
  base: string,
  target: string,
  path: string | null,
  mode: string,
) {
  return useQuery({
    queryKey: ["diff", project, base, target, path, mode],
    queryFn: () => api.diff(project!, base, target, path!, mode),
    enabled: !!project && !!path,
  });
}

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
}

export function useFiles(project: string | null) {
  return useQuery({
    queryKey: ["files", project],
    queryFn: () => api.files(project!),
    enabled: !!project,
  });
}

export function useAgentAvailable() {
  return useQuery({ queryKey: ["agent-available"], queryFn: api.agentAvailable });
}

export function useRunAvailable(project: string | null) {
  return useQuery({
    queryKey: ["run-available", project],
    queryFn: () => api.runAvailable(project!),
    enabled: !!project,
  });
}

/**
 * Subscribe to the server's SSE stream for the active comparison and invalidate the
 * changes/diff queries whenever the state token moves. Replaces interval polling:
 * the backend pushes only on real filesystem activity, and the content-aware token
 * fires even for repeated edits of one already-modified file.
 */
export function useLiveRefresh(
  project: string | null,
  base: string,
  target: string,
  enabled: boolean,
) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!project || !enabled) return;
    const params = new URLSearchParams({ project, base, target });
    const es = new EventSource(`/api/events?${params.toString()}`);
    let last: string | null = null;
    es.onmessage = (ev) => {
      const { token } = JSON.parse(ev.data) as { token: string };
      if (last !== null && token !== last) {
        qc.invalidateQueries({ queryKey: ["changes", project] });
        qc.invalidateQueries({ queryKey: ["diff", project] });
        qc.invalidateQueries({ queryKey: ["projects"] });
      }
      last = token;
    };
    return () => es.close();
  }, [project, base, target, enabled, qc]);
}
