import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { offerUndo, resetUndoOffers, undoOfferOf, UNDO_TOAST_MS } from "@/lib/undoToast";
import { useEventStore } from "@/store/events";

function notice(payload: Record<string, unknown>, tsMs = Date.now()): AgentChatEvent {
  return { seq: 1, ts_ms: tsMs, kind: "notice", payload } as AgentChatEvent;
}

describe("the undo toast", () => {
  beforeEach(() => {
    resetUndoOffers();
    useEventStore.setState({ toasts: [] });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("reads an undo offer and ignores other notices, stale offers and expired ones", () => {
    const now = Date.now();
    expect(undoOfferOf(notice({ kind: "undo_available", undo_id: "u1", text: "Archived a mail" }), now)).toEqual({ id: "u1", label: "Archived a mail" });
    expect(undoOfferOf(notice({ kind: "approval_rule" }), now)).toBeNull();
    expect(undoOfferOf(notice({ kind: "undo_available", undo_id: "u2", expires_ms: now - 1 }), now)).toBeNull();
    expect(undoOfferOf(notice({ kind: "undo_available", undo_id: "u3" }, now - UNDO_TOAST_MS * 3), now)).toBeNull();
  });

  it("shows one six-second toast with an Undo button that runs the inverse", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ ok: true, entry: { id: "u1", state: "undone" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const event = notice({ kind: "undo_available", undo_id: "u1", text: "Archived a mail" });
    offerUndo(event);
    offerUndo(event);
    const toasts = useEventStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].message).toBe("Done: Archived a mail");
    expect(toasts[0].expiresAt - toasts[0].ts).toBe(UNDO_TOAST_MS);
    expect(toasts[0].action?.label).toBe("Undo");
    await toasts[0].action!.onAction();
    expect(fetcher).toHaveBeenCalledWith("/api/trust/undo/u1", { method: "POST" });
    expect(useEventStore.getState().toasts.some((t) => t.message === "Undone.")).toBe(true);
  });

  it("says so when the inverse could not run", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: false, entry: { id: "u1", state: "failed", error: "no runner" } }), { status: 200 })));
    offerUndo(notice({ kind: "undo_available", undo_id: "u9", text: "Created an event" }));
    await useEventStore.getState().toasts[0].action!.onAction();
    expect(useEventStore.getState().toasts.some((t) => t.kind === "warning" && t.message.includes("no runner"))).toBe(true);
  });
});
