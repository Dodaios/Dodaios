/**
 * What Dodaios says when it cannot hear the microphone although access to it
 * is granted: one toast that names the input and offers the one thing that
 * helps.
 *
 * The backend publishes `MicrophoneTrouble` once per episode, with the input's
 * name as the computer lists it and one of two reasons:
 *   - `not_answering`: the computer's audio system stopped answering for that
 *     input. Only a restart of the app frees it. The app restarts by itself as
 *     soon as nothing is running; the button does it now.
 *   - `silent`: the input is open and delivers no sound at all (muted, a jack
 *     without a microphone, a virtual device whose app is closed). The button
 *     opens the microphone picker in Settings.
 * `MicrophoneRecovered` takes the toast down again.
 *
 * Shown only in the main window of the embedded desktop app. Every window has
 * its own socket, so without an owner N windows would say it N times, and a
 * remote browser must not offer to restart somebody else's computer.
 */
import { fill, translate } from "@/i18n";
import { hasEmbeddedDesktopBridge } from "@/lib/embeddedDesktop";
import { useEventStore, type Toast, type ToastAction } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";

/** Mirror of `dodaios.core.events.MICROPHONE_TROUBLE_REASONS`. */
export const MICROPHONE_TROUBLE_REASONS = ["not_answering", "silent"] as const;
export type MicrophoneTroubleReason = (typeof MICROPHONE_TROUBLE_REASONS)[number];

/** A stuck microphone stays stuck: the sentence stays until it is over or dismissed. */
export const MICROPHONE_NOT_ANSWERING_TTL_MS = 10 * 60_000;
/** Long enough to read one sentence and aim at its button. */
export const MICROPHONE_SILENT_TTL_MS = 20_000;

/** The piece that needs React state (the restart hook), handed in by `useMicrophoneToast`. */
export interface MicrophoneToastDeps {
  /** Quit and reopen (`useRestartApp`). */
  restart: () => Promise<void>;
}

export interface MicrophoneToastPlan {
  reason: MicrophoneTroubleReason;
  device: string;
  kind: Toast["kind"];
  messageKey: string;
  action: "restart" | "choose";
  ttlMs: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The sentence and the button for one `MicrophoneTrouble` payload, or `null`. */
export function planMicrophoneToast(payload: unknown): MicrophoneToastPlan | null {
  if (!isRecord(payload)) return null;
  const reason = payload.reason;
  if (reason !== "not_answering" && reason !== "silent") return null;
  const device = typeof payload.device === "string" ? payload.device.trim() : "";
  const suffix = device === "" ? "_unnamed" : "";
  if (reason === "not_answering") {
    return {
      reason,
      device,
      kind: "error",
      messageKey: `microphone_notice.not_answering${suffix}`,
      action: "restart",
      ttlMs: MICROPHONE_NOT_ANSWERING_TTL_MS,
    };
  }
  return {
    reason,
    device,
    kind: "warning",
    messageKey: `microphone_notice.silent${suffix}`,
    action: "choose",
    ttlMs: MICROPHONE_SILENT_TTL_MS,
  };
}

/** Whether THIS window says it: the main window of the embedded desktop app. */
export function isMicrophoneToastWindow(): boolean {
  return !useEventStore.getState().solo && hasEmbeddedDesktopBridge();
}

/** Input name -> the sentences on screen about it, so a recovery can take them down. */
const told = new Map<string, Set<string>>();

/** Tests only: forget what this window already said. */
export function resetMicrophoneToastState(): void {
  told.clear();
}

/** Open Settings on the microphone and speaker picker. */
export function openMicrophonePicker(): void {
  useSettingsJump.getState().request("audio-devices");
  useEventStore.getState().setActiveSection("settings");
}

function actionFor(plan: MicrophoneToastPlan, deps: MicrophoneToastDeps): ToastAction {
  if (plan.action === "restart") {
    return {
      label: translate("microphone_notice.action.restart"),
      onAction: () => deps.restart(),
      // A restart can answer "missions are running, press again".
      keepOpen: true,
    };
  }
  return {
    label: translate("microphone_notice.action.choose"),
    onAction: openMicrophonePicker,
  };
}

/**
 * Feed one bus event in. Cheap for every event but the two it reads, so the
 * WebSocket hook can call it for each envelope.
 */
export function handleMicrophoneToastEvent(
  eventName: string,
  payload: unknown,
  deps: MicrophoneToastDeps,
): void {
  if (eventName === "MicrophoneRecovered") {
    const device = isRecord(payload) && typeof payload.device === "string" ? payload.device.trim() : "";
    const messages = told.get(device);
    if (!messages) return;
    told.delete(device);
    const store = useEventStore.getState();
    for (const toast of store.toasts) {
      if (messages.has(toast.message)) store.dismissToast(toast.id);
    }
    return;
  }
  if (eventName !== "MicrophoneTrouble") return;
  if (!isMicrophoneToastWindow()) return;
  const plan = planMicrophoneToast(payload);
  if (!plan) return;
  const message = fill(translate(plan.messageKey), { device: plan.device });
  const messages = told.get(plan.device) ?? new Set<string>();
  messages.add(message);
  told.set(plan.device, messages);
  useEventStore.getState().pushToast(plan.kind, message, {
    action: actionFor(plan, deps),
    ttlMs: plan.ttlMs,
  });
}
