/**
 * The page's side of a spoken comment: the script a node's page runs
 * (`dodaios/nodes/bridge.py`, `BRIDGE_JS`), run here in a page of its own with
 * a stand-in for the app as its parent. Its microphone only asks the app; the
 * words come back as plain text and go after what the field holds.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  NODE_COMMENT_MESSAGE,
  NODE_DICTATE_MESSAGE,
  NODE_DICTATION_STATE_MESSAGE,
  NODE_DICTATION_TEXT_MESSAGE,
  NODE_MODE_MESSAGE,
} from "./nodeBridge";

const BRIDGE = resolve(__dirname, "../../../../../../nodes/bridge.py");
const SCRIPT = (() => {
  const found = /BRIDGE_JS: Final\[str\] = r"""([\s\S]*?)"""/.exec(readFileSync(BRIDGE, "utf8"));
  if (!found?.[1]) throw new Error("BRIDGE_JS not found in bridge.py");
  return found[1];
})();

/** A window of its own (jsdom ships no types here; this is the little the test uses). */
type PageWindow = Window & typeof globalThis & { eval(code: string): unknown };
type Jsdom = new (html: string, options?: Record<string, unknown>) => { window: PageWindow };
let JSDOM: Jsdom;
beforeAll(async () => {
  const name = "jsdom";
  ({ JSDOM } = (await import(/* @vite-ignore */ name)) as { JSDOM: Jsdom });
});

const LABELS = {
  placeholder: "Add a comment…",
  dictate: "Dictate",
  stopDictate: "Stop dictation",
  listening: "Listening… speak now",
  transcribing: "Transcribing…",
};

/** A node's page in comment mode, its parent a stand-in that records what it hears. */
function page() {
  const app = new JSDOM("").window;
  const posted = vi.fn();
  (app as unknown as { postMessage: typeof posted }).postMessage = posted;
  const dom = new JSDOM("<!doctype html><body><h2>Costs</h2><p>Flights are 640 euros.</p></body>", {
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const win = dom.window;
  Object.defineProperty(win, "parent", { value: app, configurable: true });
  win.eval(SCRIPT);
  const say = (data: Record<string, unknown>) =>
    win.dispatchEvent(new win.MessageEvent("message", { data, source: app as unknown as Window }));
  say({ type: NODE_MODE_MESSAGE, mode: "comment", labels: LABELS });
  const doc = win.document;
  const sent = (type: string) => posted.mock.calls.map(([message]) => message).filter((m) => m.type === type);
  return {
    win,
    say,
    sent,
    posted,
    /** Click the paragraph: the comment field opens there. */
    pin() {
      doc.querySelector("p")!.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
      return {
        field: doc.querySelector(".nc textarea") as HTMLTextAreaElement,
        mic: () => doc.querySelector(".nc .nc-mic") as HTMLButtonElement | null,
        add: () => doc.querySelector(".nc .nc-send") as HTMLButtonElement,
      };
    },
    type(field: HTMLTextAreaElement, text: string) {
      field.value = text;
      field.dispatchEvent(new win.Event("input", { bubbles: true }));
    },
    key(field: HTMLTextAreaElement, key: string) {
      field.dispatchEvent(new win.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    },
  };
}

describe("a comment spoken into a node's page", () => {
  it("has a microphone that asks the app to dictate, and shows where the dictation stands", () => {
    const p = page();
    const { field, mic } = p.pin();
    expect(mic()?.getAttribute("aria-label")).toBe("Dictate");

    mic()!.click();
    expect(p.sent(NODE_DICTATE_MESSAGE)).toEqual([{ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" }]);
    // The page shows nothing until the app says it records.
    expect(mic()!.className).toBe("nc-mic");

    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    expect(mic()!.className).toContain("is-rec");
    expect(mic()!.getAttribute("aria-label")).toBe("Stop dictation");
    expect(field.placeholder).toBe("Listening… speak now");

    mic()!.click();
    expect(p.sent(NODE_DICTATE_MESSAGE).at(-1)).toEqual({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "stop" });

    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "transcribing" });
    expect(mic()!.className).toContain("is-wait");
    expect(mic()!.disabled).toBe(true);
    expect(mic()!.getAttribute("aria-label")).toBe("Transcribing…");
  });

  it("puts the words after what was typed", () => {
    const p = page();
    const { field, mic, add } = p.pin();
    p.type(field, "Shorter:");
    mic()!.click();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "transcribing" });
    p.say({ type: NODE_DICTATION_TEXT_MESSAGE, n: 1, outcome: "text", text: " only the price, please " });
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "idle" });
    expect(field.value).toBe("Shorter: only the price, please");
    expect(add().disabled).toBe(false);
    expect(mic()!.className).toBe("nc-mic");
    expect(mic()!.disabled).toBe(false);
    expect(field.placeholder).toBe("Add a comment…");
    // Nothing is added before the reader adds it.
    expect(p.sent(NODE_COMMENT_MESSAGE)).toEqual([]);
  });

  it("adds a comment the reader added while speaking once the words are in", () => {
    const p = page();
    const { field, mic } = p.pin();
    mic()!.click();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    p.key(field, "Enter");
    // Add stops the recording and waits.
    expect(p.sent(NODE_DICTATE_MESSAGE).at(-1)).toEqual({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "stop" });
    expect(p.sent(NODE_COMMENT_MESSAGE)).toEqual([]);

    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "transcribing" });
    p.say({ type: NODE_DICTATION_TEXT_MESSAGE, n: 1, outcome: "text", text: "Use the cheaper flight" });
    expect(p.sent(NODE_COMMENT_MESSAGE)).toEqual([
      expect.objectContaining({ n: 1, text: "Use the cheaper flight", quote: "Flights are 640 euros." }),
    ]);
  });

  it("keeps the comment when the dictation failed", () => {
    const p = page();
    const { field, mic } = p.pin();
    p.type(field, "Typed half");
    mic()!.click();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    p.key(field, "Enter");
    p.say({ type: NODE_DICTATION_TEXT_MESSAGE, n: 1, outcome: "failed", text: "" });
    expect(p.sent(NODE_COMMENT_MESSAGE)).toEqual([]);
    expect(field.value).toBe("Typed half");
    expect(mic()!.disabled).toBe(false);
  });

  it("rests while another dictation of the app has the microphone", () => {
    const p = page();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "held" });
    const { mic } = p.pin();
    expect(mic()!.disabled).toBe(true);
    mic()!.click();
    expect(p.sent(NODE_DICTATE_MESSAGE)).toEqual([]);
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "idle" });
    expect(mic()!.disabled).toBe(false);
  });

  it("stops the recording when the field is closed, and ignores words for another comment", () => {
    const p = page();
    const { field, mic } = p.pin();
    mic()!.click();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    p.say({ type: NODE_DICTATION_TEXT_MESSAGE, n: 7, outcome: "text", text: "not for this one" });
    expect(field.value).toBe("");
    p.key(field, "Escape");
    expect(p.sent(NODE_DICTATE_MESSAGE).at(-1)).toEqual({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "stop" });
    expect(p.win.document.querySelector(".nc")).toBeNull();
  });

  it("keeps a running dictation when the field moves to another place", () => {
    const p = page();
    const first = p.pin();
    first.mic()!.click();
    p.say({ type: NODE_DICTATION_STATE_MESSAGE, n: 1, state: "recording" });
    const stops = p.sent(NODE_DICTATE_MESSAGE).length;
    p.win.document.querySelector("h2")!.dispatchEvent(new p.win.MouseEvent("click", { bubbles: true }));
    const moved = p.win.document.querySelector(".nc .nc-mic") as HTMLButtonElement;
    expect(moved.className).toContain("is-rec");
    expect(p.sent(NODE_DICTATE_MESSAGE)).toHaveLength(stops);
  });

  it("writes the words as text, never as markup", () => {
    const p = page();
    const { field, mic } = p.pin();
    mic()!.click();
    p.say({ type: NODE_DICTATION_TEXT_MESSAGE, n: 1, outcome: "text", text: "<img src=x onerror=alert(1)>" });
    expect(field.value).toBe("<img src=x onerror=alert(1)>");
    expect(p.win.document.querySelector(".nc img")).toBeNull();
  });
});
