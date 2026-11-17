import { useCallback, useEffect, useState } from "react";

/**
 * The person's standing wishes for agent briefs, from GET /api/settings/agent-briefs.
 * `wishes` is the list in their words, one per line ("" = the default, where
 * an agent checks its own work and ships it). `default` and `limits` are the
 * server's English rule text, for the assistant; the UI shows its own copy.
 */
export interface AgentBriefsConfig {
  wishes: string;
  is_custom: boolean;
  default: string;
  limits: string;
  char_count: number;
  max_chars: number;
}

const URL = "/api/settings/agent-briefs";

async function send(init: RequestInit): Promise<AgentBriefsConfig> {
  const res = await fetch(URL, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
  return body as AgentBriefsConfig;
}

/**
 * Loads the wishes and exposes saveWishes()/resetWishes(). The assistant keeps
 * the same list when the person says it in the chat (agent-briefs-set); every
 * brief reads it fresh, so nothing here needs a restart.
 */
export function useAgentBriefs() {
  const [config, setConfig] = useState<AgentBriefsConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setConfig((await res.json()) as AgentBriefsConfig);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  const saveWishes = useCallback(async (wishes: string) => {
    const result = await send({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wishes }),
    });
    setConfig(result);
    return result;
  }, []);

  const resetWishes = useCallback(async () => {
    const result = await send({ method: "DELETE" });
    setConfig(result);
    return result;
  }, []);

  return { config, loading, error, refetch, saveWishes, resetWishes };
}
