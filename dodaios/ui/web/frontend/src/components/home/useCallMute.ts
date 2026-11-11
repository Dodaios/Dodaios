import { useCallback, useEffect } from "react";
import { create } from "zustand";

import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";

/**
 * Whether the running call's microphone is off, shared by every control
 * that shows it (the composer's switch, the call window's status line).
 * `flipped` marks a flip made during this call: its answer wins over a read
 * that started earlier and lands later.
 */
const useMuteStore = create<{ muted: boolean; flipped: boolean }>(() => ({ muted: false, flipped: false }));

/**
 * The running call's microphone switch (GET/POST /api/voice/mic-mute).
 * Read when a call starts, flipped by the person. Off a call nothing shows
 * it, and the next call reads it again.
 */
export function useCallMute(live: boolean): { muted: boolean; toggleMute: () => void } {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const muted = useMuteStore((s) => s.muted);

  useEffect(() => {
    if (!live) return;
    // A call (or a control showing up during one) starts from the host's word.
    useMuteStore.setState({ flipped: false });
    let alive = true;
    void fetch("/api/voice/mic-mute")
      .then((r) => (r.ok ? r.json() : null))
      .then(
        (body: { muted?: boolean } | null) => {
          if (alive && !useMuteStore.getState().flipped && typeof body?.muted === "boolean") {
            useMuteStore.setState({ muted: body.muted });
          }
        },
        () => undefined,
      );
    return () => {
      alive = false;
    };
  }, [live]);

  const toggleMute = useCallback(() => {
    useMuteStore.setState({ flipped: true });
    void fetch("/api/voice/mic-mute", { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const body = (await r.json()) as { muted?: boolean };
        useMuteStore.setState({ muted: Boolean(body.muted) });
      })
      .catch(() => pushToast("error", t("home.call.mute_failed")));
  }, [pushToast, t]);

  return { muted, toggleMute };
}
