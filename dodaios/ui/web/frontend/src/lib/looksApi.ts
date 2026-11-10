/**
 * Client for `/api/looks`: visuals that take the voice orb's place
 * (`docs/looks.md`). The look itself runs in a sandboxed frame; see
 * `components/looks/LookFrame.tsx`.
 */

/** The voice orb itself: the "no look" choice. */
export const ORB_LOOK_ID = "orb";

export interface Look {
  id: string;
  name: string;
  description: string;
  author: string;
  version: string;
  license: string;
  attribution: string;
  homepage: string;
  builtin: boolean;
  preview_url: string;
  frame_url: string;
}

export interface LooksState {
  /** A look id, or `ORB_LOOK_ID`. */
  active: string;
  looks: Look[];
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = (await response.json().catch(() => null)) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : "";
    throw new Error(detail || `Looks request failed (${response.status}).`);
  }
  return body as T;
}

/** Any answer becomes a usable state: an odd one means "the orb, no looks". */
function normalize(body: unknown): LooksState {
  const raw = (body && typeof body === "object" ? body : {}) as Partial<LooksState>;
  const looks = Array.isArray(raw.looks)
    ? raw.looks.filter(
        (look): look is Look =>
          !!look && typeof look.id === "string" && typeof look.frame_url === "string",
      )
    : [];
  const active = typeof raw.active === "string" ? raw.active : ORB_LOOK_ID;
  return { active, looks };
}

export async function fetchLooks(): Promise<LooksState> {
  return normalize(await request<unknown>("/api/looks"));
}

export async function selectLook(id: string): Promise<LooksState> {
  const body = await request<unknown>("/api/looks/active", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id }),
  });
  return normalize(body);
}
