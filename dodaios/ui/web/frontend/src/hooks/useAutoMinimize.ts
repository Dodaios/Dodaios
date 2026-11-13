import { useCallback, useEffect, useState } from "react";

export interface AutoMinimizeResult {
  ok: boolean;
  enabled: boolean;
  supported: boolean;
  persisted: boolean;
  applied_live: boolean;
  restart_required: boolean;
}

/** Minimize the main desktop window when another app takes focus (Windows). */
export function useAutoMinimize() {
  const [enabled, setEnabledState] = useState<boolean | null>(null);
  const [supported, setSupported] = useState(false);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      const res = await fetch("/api/settings/auto-minimize-on-focus-loss");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEnabledState(Boolean(data.enabled));
      setSupported(Boolean(data.supported));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetch().catch(() => setSupported(false));
  }, [refetch]);

  const setEnabled = useCallback(async (next: boolean): Promise<AutoMinimizeResult> => {
    const res = await fetch("/api/settings/auto-minimize-on-focus-loss", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
    setEnabledState(Boolean(body.enabled));
    setSupported(Boolean(body.supported));
    return body as AutoMinimizeResult;
  }, []);

  return { enabled, supported, loading, refetch, setEnabled };
}
