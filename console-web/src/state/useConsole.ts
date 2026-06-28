import { useCallback, useEffect, useState } from "react";
import { api, ConsoleSnapshot } from "../api/client";

export function useConsoleSnapshot() {
  const [snapshot, setSnapshot] = useState<ConsoleSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await api.snapshot());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const source = new EventSource("/api/stream");
    source.onmessage = () => void refresh();
    source.addEventListener("task.created", () => void refresh());
    source.addEventListener("task.updated", () => void refresh());
    source.addEventListener("alert.opened", () => void refresh());
    source.onerror = () => source.close();
    return () => {
      window.clearInterval(timer);
      source.close();
    };
  }, [refresh]);

  return { snapshot, error, refresh };
}

