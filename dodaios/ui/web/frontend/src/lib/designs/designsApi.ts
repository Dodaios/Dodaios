/** The designs routes (`dodaios/ui/web/designs_routes.py`, docs/designs.md). */

export const STANDARD_DESIGN_ID = "standard";

export type BackgroundStyle = "none" | "glow" | "waves" | "stars" | "gradient";
export type BackgroundSpeed = "slow" | "medium" | "fast";

export interface DesignPalette {
  background: string;
  foreground: string;
  accent: string;
  sidebar?: string;
  card?: string;
  popover?: string;
  surface?: string;
  border?: string;
  muted?: string;
  primary?: string;
  user_bubble?: string;
  bubble_out?: string;
  bubble_in?: string;
  success?: string;
  warning?: string;
  destructive?: string;
}

export interface DesignBackground {
  style: BackgroundStyle;
  colors: string[];
  speed: BackgroundSpeed;
  strength: number;
}

export interface Design {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  dark: DesignPalette | null;
  light: DesignPalette | null;
  background: DesignBackground;
  created_at: number;
  updated_at: number;
}

export interface DesignsState {
  active: string;
  standard_id: string;
  designs: Design[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no JSON body: the status is the message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function fetchDesigns(): Promise<DesignsState> {
  return request<DesignsState>("/api/designs");
}

export async function activateDesign(id: string): Promise<DesignsState> {
  const body = await request<{ state: DesignsState }>("/api/designs/active", {
    method: "PUT",
    body: JSON.stringify({ id }),
  });
  return body.state;
}

export async function resetDesign(): Promise<DesignsState> {
  const body = await request<{ state: DesignsState }>("/api/designs/reset", { method: "POST" });
  return body.state;
}

export async function deleteDesign(id: string): Promise<DesignsState> {
  const body = await request<{ state: DesignsState }>(`/api/designs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  return body.state;
}

export async function renameDesign(id: string, name: string): Promise<DesignsState> {
  const body = await request<{ state: DesignsState }>("/api/designs", {
    method: "POST",
    body: JSON.stringify({ id, name, apply: false }),
  });
  return body.state;
}
