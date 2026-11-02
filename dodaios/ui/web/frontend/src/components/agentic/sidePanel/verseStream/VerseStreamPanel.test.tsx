import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VerseStreamPanel } from "./VerseStreamPanel";
import { readUnrealPreview } from "./useUnrealPreviewFlag";
import { VERSE_STREAM_LOCALES, verseStreamText } from "./strings";
import { fakeWorld, flush, FakeChannel } from "./testFakes";

type ObserverCallback = (entries: Partial<IntersectionObserverEntry>[]) => void;
let observers: ObserverCallback[] = [];

class IntersectionObserverStub {
  constructor(callback: ObserverCallback) {
    observers.push(callback);
  }
  observe() {}
  disconnect() {}
  unobserve() {}
  takeRecords() {
    return [];
  }
}

function intersect(visible: boolean) {
  act(() => {
    for (const callback of observers) callback([{ isIntersecting: visible, intersectionRatio: visible ? 1 : 0 }]);
  });
}

function setPageHidden(hidden: boolean) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  observers = [];
  vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width: 480,
    height: 320,
    top: 0,
    left: 0,
    right: 480,
    bottom: 320,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  setPageHidden(false);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function streamingPanel() {
  const world = fakeWorld();
  render(<VerseStreamPanel deps={world.deps} />);
  intersect(true);
  await act(flush);
  const socket = world.sockets[0];
  act(() => {
    socket.open();
    socket.receive({ type: "config", peerConnectionOptions: { iceServers: [] } });
    socket.receive({ type: "streamerList", ids: ["Verse"] });
    socket.receive({ type: "offer", sdp: "v=0\r\n" });
  });
  await act(flush);
  const channel = new FakeChannel();
  act(() => {
    world.peers[0].connect(channel);
  });
  return { world, socket, channel };
}

describe("VerseStreamPanel", () => {
  it("does nothing until the panel is on screen", async () => {
    const world = fakeWorld();
    render(<VerseStreamPanel deps={world.deps} />);
    await act(flush);
    expect(world.ticketCalls).toBe(0);
    intersect(true);
    await act(flush);
    expect(world.ticketCalls).toBe(1);
    expect(world.sockets).toHaveLength(1);
  });

  it("streams, and closes the session in the same task when scrolled away (A20.1)", async () => {
    const { socket } = await streamingPanel();
    expect(screen.getByTestId("verse-stream-panel").dataset.phase).toBe("streaming");
    expect(socket.sent[0]).toMatchObject({ type: "hello", w: 480, h: 320 });
    intersect(false);
    expect(socket.closedWith).toBe(1000);
  });

  it("closes when the app is minimised (page hidden)", async () => {
    const { socket } = await streamingPanel();
    setPageHidden(true);
    expect(socket.closedWith).toBe(1000);
  });

  it("forwards walking keys and drops duel keys", async () => {
    const { channel } = await streamingPanel();
    const panel = screen.getByTestId("verse-stream-panel");
    fireEvent.keyDown(panel, { code: "KeyW", key: "w" });
    fireEvent.keyDown(panel, { code: "Space", key: " " });
    fireEvent.keyDown(panel, { code: "KeyR", key: "r" });
    fireEvent.keyUp(panel, { code: "KeyW", key: "w" });
    expect(channel.sent.map((m) => Array.from(m))).toEqual([
      [60, 87, 0],
      [61, 87],
    ]);
  });

  it("shows the last frame with 'Verse is open' when the full view wins", async () => {
    const { socket, world } = await streamingPanel();
    act(() => {
      socket.receive({ type: "verse.streamState", state: "stopped", error: "full_view_open" });
    });
    expect(screen.getByTestId("verse-stream-open").textContent).toContain(verseStreamText("en").verseOpen);
    expect(world.peers[0].closed).toBe(true);
    expect(socket.closedWith).toBeNull(); // the panel stays visible to the Verse
  });

  it("shows the plain card without a Verse host and retries", async () => {
    const world = fakeWorld(null);
    render(<VerseStreamPanel deps={world.deps} />);
    intersect(true);
    await act(flush);
    expect(screen.getByTestId("verse-stream-fallback").textContent).toContain(verseStreamText("en").unavailable);
    fireEvent.click(screen.getByRole("button"));
    await act(flush);
    expect(world.ticketCalls).toBe(2);
  });

  it("shows the plain card when the stream fails", async () => {
    const { socket } = await streamingPanel();
    act(() => {
      socket.receive({ type: "verse.streamState", state: "failed", error: "encoder_unavailable" });
    });
    expect(screen.getByTestId("verse-stream-fallback").textContent).toContain(verseStreamText("en").failed);
  });
});

describe("verse stream strings and flag", () => {
  it("has every string in every UI locale", () => {
    const keys = Object.keys(verseStreamText("en")).sort();
    expect(VERSE_STREAM_LOCALES.sort()).toEqual(["de", "en", "es", "pt", "zh"]);
    for (const lang of VERSE_STREAM_LOCALES) {
      const text = verseStreamText(lang) as Record<string, string>;
      expect(Object.keys(text).sort()).toEqual(keys);
      for (const key of keys) expect(text[key].length).toBeGreaterThan(0);
    }
    expect(verseStreamText("xx")).toBe(verseStreamText("en"));
  });

  it("reads verse.unreal_preview strictly", () => {
    expect(readUnrealPreview({ verse: { unreal_preview: true } })).toBe(true);
    expect(readUnrealPreview({ verse: { unreal_preview: "true" } })).toBe(false);
    expect(readUnrealPreview({ verse: {} })).toBe(false);
    expect(readUnrealPreview({})).toBe(false);
    expect(readUnrealPreview(null)).toBe(false);
  });
});
