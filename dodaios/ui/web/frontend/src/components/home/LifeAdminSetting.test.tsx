import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { draftLine, LifeAdminSetting, type LifeAdmin } from "./LifeAdminSetting";

const settings = { enabled: true, digest_day: "off", digest_time: "09:00", in_brief: true, categories: {}, timezone: "" };
const item = { id: "i1", kind: "bill", title: "Electricity invoice", due: "2026-11-14", status: "noticed", draft: null };
const state = (over: Partial<LifeAdmin> = {}): LifeAdmin => ({ available: true, settings, items: [item], ...over });

describe("LifeAdminSetting", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("words a draft per kind", () => {
    expect(draftLine({ kind: "mail", subject: "Hello", body: "Text" })).toBe("Hello — Text");
    expect(draftLine({ kind: "list", lines: ["milk", "eggs"] })).toBe("milk; eggs");
    expect(draftLine({ kind: "calendar_hold", hold: { title: "Pay", date: "2026-11-12" } })).toBe("Pay · 2026-11-12");
  });

  it("renders nothing while the service is unavailable", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state({ available: false })))));
    const { container } = render(<LifeAdminSetting />);
    expect(container.textContent).toBe("");
  });

  it("shows only the switch while off", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state({ settings: { ...settings, enabled: false }, items: [] })))));
    render(<LifeAdminSetting />);
    await screen.findByTestId("lead-life-admin-enabled");
    expect(screen.queryByTestId("lead-life-admin-items")).toBeNull();
    expect(screen.queryByTestId("lead-life-admin-day")).toBeNull();
  });

  it("lists items and prepares or dismisses them", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(url)}`);
      if (String(url).endsWith("/prepare")) {
        return new Response(JSON.stringify({ ...item, status: "prepared", draft: { kind: "calendar_hold", hold: { title: "Pay", date: "2026-11-12" } } }));
      }
      if (String(url).endsWith("/dismiss")) return new Response("{}");
      return new Response(JSON.stringify(state()));
    }));
    render(<LifeAdminSetting />);
    const list = await screen.findByTestId("lead-life-admin-items");
    expect(list.textContent).toContain("Electricity invoice");
    fireEvent.click(screen.getByTestId("lead-life-admin-prepare"));
    await waitFor(() => expect(screen.getByTestId("lead-life-admin-draft").textContent).toContain("Pay"));
    expect(calls).toContain("POST /api/agent-chat/lead/life-admin/items/i1/prepare");
    fireEvent.click(screen.getByTestId("lead-life-admin-dismiss"));
    await waitFor(() => expect(screen.queryByTestId("lead-life-admin-items")).toBeNull());
    expect(calls).toContain("POST /api/agent-chat/lead/life-admin/items/i1/dismiss");
  });

  it("saves the whole settings object when a kind is switched off", async () => {
    const bodies: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") bodies.push(String(init.body));
      return new Response(JSON.stringify(state()));
    }));
    render(<LifeAdminSetting />);
    fireEvent.click(await screen.findByTestId("lead-life-admin-kind-bill"));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(JSON.parse(bodies[0]).categories.bill).toBe(false);
  });
});
