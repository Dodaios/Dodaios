import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Design, DesignsState } from "@/lib/designs/designsApi";

const DESIGN: Design = {
  id: "midnight",
  name: "Midnight",
  description: "",
  builtin: false,
  dark: { background: "#0b1020", foreground: "#e8ecf8", accent: "#7c9cff" },
  light: null,
  background: { style: "glow", colors: ["#1d3b8f"], speed: "slow", strength: 0.5 },
  created_at: 1,
  updated_at: 1,
};

function state(active: string): DesignsState {
  return { active, standard_id: "standard", designs: [DESIGN] };
}

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

describe("designs store", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    document.documentElement.className = "dark";
    document.getElementById("dodaios-design")?.remove();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("paints the active design, caches it for the boot script, and takes it off on reset", async () => {
    const fetchMock = vi.fn((url: string) =>
      url.endsWith("/reset") ? respond({ state: state("standard") }) : respond(state("midnight")),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { useDesignsStore, DESIGN_CACHE_KEY } = await import("@/store/designs");

    await useDesignsStore.getState().load();
    expect(useDesignsStore.getState().current?.id).toBe("midnight");
    expect(document.documentElement.classList.contains("dodaios-design")).toBe(true);
    const style = document.getElementById("dodaios-design");
    expect(style?.textContent).toContain(":root.dodaios-design.dark");
    const cached = JSON.parse(window.localStorage.getItem(DESIGN_CACHE_KEY) ?? "null");
    expect(cached.design.id).toBe("midnight");
    expect(cached.css).toBe(style?.textContent);

    await useDesignsStore.getState().reset();
    expect(useDesignsStore.getState().current).toBeNull();
    expect(document.documentElement.classList.contains("dodaios-design")).toBe(false);
    expect(document.getElementById("dodaios-design")).toBeNull();
    expect(window.localStorage.getItem(DESIGN_CACHE_KEY)).toBeNull();
  });

  it("starts from the cached design before the backend answers", async () => {
    window.localStorage.setItem("jarvis.design", JSON.stringify({ css: "x", design: DESIGN }));
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const { useDesignsStore } = await import("@/store/designs");
    expect(useDesignsStore.getState().current?.id).toBe("midnight");
    expect(useDesignsStore.getState().active).toBe("midnight");
  });

  it("keeps the cached design when the backend cannot be reached", async () => {
    window.localStorage.setItem("jarvis.design", JSON.stringify({ css: "x", design: DESIGN }));
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    const { useDesignsStore } = await import("@/store/designs");
    await useDesignsStore.getState().load();
    expect(useDesignsStore.getState().loaded).toBe(true);
    expect(useDesignsStore.getState().current?.id).toBe("midnight");
  });
});
