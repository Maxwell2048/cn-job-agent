import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveEvent } from "./api";

/** Load data on mount and whenever `deps` change; `reload()` fetches again. */
export function useData<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/** Follow a run's or collection's Server-Sent Events while `enabled`.
 *  Calls `onEnd` when the server sends __end__. */
export function useEventStream(path: string | null, enabled: boolean, onEnd?: () => void) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const endRef = useRef(onEnd);
  endRef.current = onEnd;

  useEffect(() => {
    if (!path || !enabled) return;
    setEvents([]);
    const source = new EventSource(path);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as LiveEvent;
      setEvents((previous) => [...previous, event]);
      if (event.node === "__end__") {
        source.close();
        endRef.current?.();
      }
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [path, enabled]);

  return events;
}
