/**
 * The undo toast: a reversible action the assistant just took ("Archived a
 * mail") shows for six seconds with one button, Undo, which runs the inverse
 * through `POST /api/trust/undo/{id}` (dodaios/trust/undo.py).
 *
 * Fed by the chat's `notice{kind:"undo_available"}` events (store/agentChat.ts
 * `ingest`). The timeline reducer drops that notice, so the toast is its only
 * face; a replayed event log (a reload) never re-offers an old undo because
 * the offer carries its own expiry.
 */
import { fill, translate } from "@/i18n";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { runUndo } from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

/** How long the offer stays on screen. */
export const UNDO_TOAST_MS = 6000;

const seen = new Set<string>();

/** The undo offer in `event`, or null when it is not one (or is stale). */
export function undoOfferOf(event: AgentChatEvent, now = Date.now()): { id: string; label: string } | null {
  if (event.kind !== "notice") return null;
  const p = (event.payload ?? {}) as Record<string, unknown>;
  if (p.kind !== "undo_available" || typeof p.undo_id !== "string" || !p.undo_id) return null;
  const expires = typeof p.expires_ms === "number" ? p.expires_ms : 0;
  if (expires && expires < now) return null;
  // A replayed log would re-offer; the notice is new only when its time is near.
  const ts = typeof event.ts_ms === "number" ? event.ts_ms : now;
  if (now - ts > UNDO_TOAST_MS * 2) return null;
  return { id: p.undo_id, label: typeof p.text === "string" ? p.text : "" };
}

/** Show the undo toast for an `undo_available` notice; no-op for anything else. */
export function offerUndo(event: AgentChatEvent): void {
  const offer = undoOfferOf(event);
  if (!offer || seen.has(offer.id)) return;
  seen.add(offer.id);
  if (seen.size > 200) seen.delete(seen.values().next().value as string);
  const push = useEventStore.getState().pushToast;
  const message = offer.label
    ? fill(translate("trust.undo.toast"), { what: offer.label })
    : translate("trust.undo.toast_plain");
  push("success", message, {
    ttlMs: UNDO_TOAST_MS,
    action: {
      label: translate("trust.undo.button"),
      onAction: async () => {
        try {
          const entry = await runUndo(offer.id);
          const again = useEventStore.getState().pushToast;
          if (entry.state === "undone") again("success", translate("trust.undo.done"));
          else again("warning", entry.error ? `${translate("trust.undo.failed")} ${entry.error}` : translate("trust.undo.failed"));
        } catch {
          useEventStore.getState().pushToast("error", translate("trust.undo.failed"));
        }
      },
    },
  });
}

/** Tests: forget which offers were shown. */
export function resetUndoOffers(): void {
  seen.clear();
}
