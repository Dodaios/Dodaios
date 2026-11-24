import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";

const fakes = vi.hoisted(() => ({
  realtimeAvailable: false,
  requiresWebRtcOffer: false,
  constructed: 0,
  start: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@/hooks/useVoiceMode", () => ({
  useVoiceMode: () => ({
    realtimeAvailable: fakes.realtimeAvailable,
    requiresWebRtcOffer: fakes.requiresWebRtcOffer,
  }),
}));

vi.mock("@/lib/realtimeTransportBroker", () => ({
  RealtimeTransportBroker: class {
    constructor() {
      fakes.constructed += 1;
    }

    start() {
      fakes.start();
    }

    stop() {
      fakes.stop();
    }
  },
}));

import { SubscriptionRealtimeTransportBroker } from "./SubscriptionRealtimeTransportBroker";

beforeEach(() => {
  fakes.realtimeAvailable = false;
  fakes.requiresWebRtcOffer = false;
  fakes.constructed = 0;
  fakes.start.mockClear();
  fakes.stop.mockClear();
  (window as unknown as { pywebview?: unknown }).pywebview = { api: {} };
  window.__JARVIS_REALTIME_BROKER_TOKEN = "desktop-capability";
});

afterEach(() => {
  cleanup();
  delete (window as unknown as { pywebview?: unknown }).pywebview;
  delete window.__JARVIS_REALTIME_BROKER_TOKEN;
});

describe("SubscriptionRealtimeTransportBroker", () => {
  it.each([
    [false, true],
    [true, false],
  ])(
    "does not start for availability %s, offer requirement %s",
    (available, requiresOffer) => {
      fakes.realtimeAvailable = available;
      fakes.requiresWebRtcOffer = requiresOffer;

      render(<SubscriptionRealtimeTransportBroker />);

      expect(fakes.constructed).toBe(0);
      expect(fakes.start).not.toHaveBeenCalled();
    },
  );

  it("runs only while subscription Realtime needs an offer", () => {
    fakes.realtimeAvailable = true;
    fakes.requiresWebRtcOffer = true;
    const view = render(<SubscriptionRealtimeTransportBroker />);

    expect(fakes.constructed).toBe(1);
    expect(fakes.start).toHaveBeenCalledOnce();

    fakes.requiresWebRtcOffer = false;
    view.rerender(<SubscriptionRealtimeTransportBroker />);
    expect(fakes.stop).toHaveBeenCalledOnce();
    expect(fakes.constructed).toBe(1);
  });

  it("does not expose the passive peer to a normal authenticated browser", () => {
    fakes.realtimeAvailable = true;
    fakes.requiresWebRtcOffer = true;
    delete (window as unknown as { pywebview?: unknown }).pywebview;

    render(<SubscriptionRealtimeTransportBroker />);

    expect(fakes.constructed).toBe(0);
  });

  it("requires the desktop-only process capability", () => {
    fakes.realtimeAvailable = true;
    fakes.requiresWebRtcOffer = true;
    delete window.__JARVIS_REALTIME_BROKER_TOKEN;

    render(<SubscriptionRealtimeTransportBroker />);

    expect(fakes.constructed).toBe(0);
  });

  it("starts when the native host injects its capability after first render", () => {
    fakes.realtimeAvailable = true;
    fakes.requiresWebRtcOffer = true;
    delete window.__JARVIS_REALTIME_BROKER_TOKEN;

    render(<SubscriptionRealtimeTransportBroker />);
    expect(fakes.constructed).toBe(0);

    act(() => {
      window.__JARVIS_REALTIME_BROKER_TOKEN = "late-desktop-capability";
      window.dispatchEvent(new Event("jarvis-token-ready"));
    });

    expect(fakes.constructed).toBe(1);
    expect(fakes.start).toHaveBeenCalledOnce();
  });
});
