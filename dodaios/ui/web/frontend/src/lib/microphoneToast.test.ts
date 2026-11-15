import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { translate, useI18nStore, type UiLanguage } from "@/i18n";
import {
  MICROPHONE_NOT_ANSWERING_TTL_MS,
  MICROPHONE_SILENT_TTL_MS,
  MICROPHONE_TROUBLE_REASONS,
  handleMicrophoneToastEvent,
  planMicrophoneToast,
  resetMicrophoneToastState,
} from "@/lib/microphoneToast";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";

const BUILT_IN = "MacBook Air-Mikrofon";

function trouble(over: Record<string, unknown> = {}) {
  return {
    reason: "not_answering",
    device: BUILT_IN,
    feature: "wake_word",
    automatic: true,
    ...over,
  };
}

type Host = { __JARVIS_EMBEDDED_DESKTOP?: boolean };

describe("planMicrophoneToast", () => {
  it("offers a restart for a microphone the audio system stopped answering for", () => {
    expect(planMicrophoneToast(trouble())).toMatchObject({
      reason: "not_answering",
      device: BUILT_IN,
      kind: "error",
      messageKey: "microphone_notice.not_answering",
      action: "restart",
      ttlMs: MICROPHONE_NOT_ANSWERING_TTL_MS,
    });
  });

  it("offers the microphone picker for an input that delivers no sound", () => {
    expect(planMicrophoneToast(trouble({ reason: "silent" }))).toMatchObject({
      reason: "silent",
      kind: "warning",
      messageKey: "microphone_notice.silent",
      action: "choose",
      ttlMs: MICROPHONE_SILENT_TTL_MS,
    });
  });

  it("has a sentence for an input without a name", () => {
    expect(planMicrophoneToast(trouble({ device: "" }))?.messageKey).toBe(
      "microphone_notice.not_answering_unnamed",
    );
    expect(planMicrophoneToast(trouble({ reason: "silent", device: "  " }))?.messageKey).toBe(
      "microphone_notice.silent_unnamed",
    );
  });

  it.each([null, "x", {}, { reason: "muted" }, { reason: 7 }])("says nothing for %j", (payload) => {
    expect(planMicrophoneToast(payload)).toBeNull();
  });

  it("knows every reason the backend can send", () => {
    for (const reason of MICROPHONE_TROUBLE_REASONS) {
      expect(planMicrophoneToast(trouble({ reason }))).not.toBeNull();
    }
  });
});

describe("microphone notice texts", () => {
  const languages: UiLanguage[] = ["en", "de", "es", "pt", "zh"];
  const keys = [
    "microphone_notice.not_answering",
    "microphone_notice.not_answering_unnamed",
    "microphone_notice.silent",
    "microphone_notice.silent_unnamed",
    "microphone_notice.action.restart",
    "microphone_notice.action.choose",
  ];
  const before = useI18nStore.getState().ui;

  afterEach(() => {
    useI18nStore.setState({ ui: before });
  });

  it.each(languages)("has every sentence in %s, and the named ones name the input", (ui) => {
    useI18nStore.setState({ ui });
    for (const key of keys) {
      const text = translate(key);
      expect(text, `${ui}: ${key}`).not.toBe(key);
      expect(text.trim().length, `${ui}: ${key}`).toBeGreaterThan(0);
    }
    expect(translate("microphone_notice.not_answering")).toContain("{device}");
    expect(translate("microphone_notice.silent")).toContain("{device}");
    expect(translate("microphone_notice.not_answering_unnamed")).not.toContain("{device}");
    expect(translate("microphone_notice.silent_unnamed")).not.toContain("{device}");
  });
});

describe("handleMicrophoneToastEvent", () => {
  const host = window as unknown as Host;
  const restart = vi.fn(async () => {});

  beforeEach(() => {
    host.__JARVIS_EMBEDDED_DESKTOP = true;
    resetMicrophoneToastState();
    restart.mockClear();
    useI18nStore.setState({ ui: "en" });
    useEventStore.setState({ toasts: [], solo: false, activeSection: "chats" });
  });

  afterEach(() => {
    delete host.__JARVIS_EMBEDDED_DESKTOP;
    useEventStore.setState({ toasts: [] });
  });

  it("names the stuck microphone and restarts on the button", async () => {
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble(), { restart });

    const [toast] = useEventStore.getState().toasts;
    expect(toast.kind).toBe("error");
    expect(toast.message).toContain(`"${BUILT_IN}"`);
    expect(toast.message).not.toContain("{device}");
    expect(toast.action?.label).toBe(translate("microphone_notice.action.restart"));
    // A restart can answer "missions are running, press again".
    expect(toast.action?.keepOpen).toBe(true);

    await toast.action?.onAction();
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it("names the silent microphone and opens the microphone picker on the button", async () => {
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble({ reason: "silent" }), { restart });

    const [toast] = useEventStore.getState().toasts;
    expect(toast.kind).toBe("warning");
    expect(toast.message).toContain(`"${BUILT_IN}"`);
    expect(toast.action?.label).toBe(translate("microphone_notice.action.choose"));

    await toast.action?.onAction();
    expect(useEventStore.getState().activeSection).toBe("settings");
    expect(useSettingsJump.getState().take()).toBe("audio-devices");
    expect(restart).not.toHaveBeenCalled();
  });

  it("takes the notice down when the microphone is heard again", () => {
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble(), { restart });
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble({ device: "AirPods Pro", reason: "silent" }), {
      restart,
    });
    expect(useEventStore.getState().toasts).toHaveLength(2);

    handleMicrophoneToastEvent("MicrophoneRecovered", { device: BUILT_IN }, { restart });

    const left = useEventStore.getState().toasts;
    expect(left).toHaveLength(1);
    expect(left[0].message).toContain("AirPods Pro");
  });

  it("says nothing in a remote browser or a detached window", () => {
    delete host.__JARVIS_EMBEDDED_DESKTOP;
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble(), { restart });
    expect(useEventStore.getState().toasts).toHaveLength(0);

    host.__JARVIS_EMBEDDED_DESKTOP = true;
    useEventStore.setState({ solo: true });
    handleMicrophoneToastEvent("MicrophoneTrouble", trouble(), { restart });
    expect(useEventStore.getState().toasts).toHaveLength(0);
  });

  it("ignores every other event", () => {
    handleMicrophoneToastEvent("PermissionNeeded", trouble(), { restart });
    handleMicrophoneToastEvent("DictationCompleted", {}, { restart });
    expect(useEventStore.getState().toasts).toHaveLength(0);
  });
});
