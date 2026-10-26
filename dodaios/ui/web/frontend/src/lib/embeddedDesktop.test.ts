import { afterEach, describe, expect, it } from "vitest";

import { voiceModeEndpoint } from "./embeddedDesktop";

type DesktopWindow = Window & {
  __JARVIS_EMBEDDED_DESKTOP?: boolean;
  pywebview?: { api?: unknown };
};

const host = window as DesktopWindow;

describe("voiceModeEndpoint", () => {
  afterEach(() => {
    delete host.__JARVIS_EMBEDDED_DESKTOP;
    delete host.pywebview;
  });

  it("identifies an embedded desktop request", () => {
    host.__JARVIS_EMBEDDED_DESKTOP = true;

    expect(voiceModeEndpoint()).toBe("/api/settings/voice-mode?surface=desktop");
  });

  it("leaves an ordinary browser on the shared endpoint", () => {
    expect(voiceModeEndpoint()).toBe("/api/settings/voice-mode");
  });
});
