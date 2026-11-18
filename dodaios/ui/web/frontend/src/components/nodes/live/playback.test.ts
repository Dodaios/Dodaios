import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LIVE_TIMING,
  LivePlayer,
  changedElements,
  elementForPath,
  readingOrder,
  revealDelays,
  unitsFor,
  type PresenceElements,
} from "./playback";
import { defaultReveal } from "./reveal";

function html(markup: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = markup;
  document.body.appendChild(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("the cadence", () => {
  it("plays units 90 ms apart, and compresses a long batch to three seconds", () => {
    expect(revealDelays(0)).toEqual([]);
    expect(revealDelays(1)).toEqual([0]);
    expect(revealDelays(4)).toEqual([0, 90, 180, 270]);
    const long = revealDelays(200);
    expect(long[long.length - 1] + LIVE_TIMING.fadeMs).toBeLessThanOrEqual(LIVE_TIMING.maxBatchMs);
    expect(long[1]).toBeLessThan(LIVE_TIMING.staggerMs);
  });
});

describe("finding what a batch wrote", () => {
  it("orders elements as they are read, each once, outer ones only", () => {
    const root = html("<p id=a>A</p><p id=b><b id=c>C</b></p>");
    const [a, b, c] = ["a", "b", "c"].map((id) => root.querySelector(`#${id}`)!);
    expect(readingOrder([c, b, a, b])).toEqual([a, b]);
  });

  it("takes added blocks and rewritten text from the DOM changes, in reading order", async () => {
    const root = html("<p id=first>One</p>");
    const records: MutationRecord[] = [];
    const watch = new MutationObserver((r) => records.push(...r));
    watch.observe(root, { childList: true, characterData: true, subtree: true });
    const added = document.createElement("p");
    added.textContent = "Two";
    root.appendChild(added);
    root.querySelector("#first")!.firstChild!.nodeValue = "One, rewritten";
    await Promise.resolve();
    records.push(...watch.takeRecords());
    watch.disconnect();
    expect(changedElements(records, root)).toEqual([root.querySelector("#first"), added]);
  });

  it("leaves out what has nothing to see and what is pinned in place", async () => {
    const root = html("<div id=body></div>");
    const records: MutationRecord[] = [];
    const watch = new MutationObserver((r) => records.push(...r));
    watch.observe(root, { childList: true, subtree: true });
    const empty = document.createElement("div");
    const row = document.createElement("div");
    row.textContent = "Rent";
    const total = document.createElement("div");
    total.textContent = "Sum";
    total.style.position = "sticky";
    root.append(empty, row, total);
    await Promise.resolve();
    records.push(...watch.takeRecords());
    watch.disconnect();
    expect(changedElements(records, root)).toEqual([row]);
  });

  it("finds a marked element by its path, or by the nearest marked parent path", () => {
    const root = html('<table><tr data-live-path="/rows/0"><td>a</td></tr><tr data-live-path="/rows/1"><td data-live-path="/rows/1/0">b</td></tr></table>');
    expect(elementForPath(root, "/rows/1/0")?.textContent).toBe("b");
    expect(elementForPath(root, "/rows/0/3")?.getAttribute("data-live-path")).toBe("/rows/0");
    expect(elementForPath(root, "/title")).toBeNull();
  });

  it("turns steps into units: paths, selectors and what changed; a step that finds nothing is left out", () => {
    const root = html('<h1 class="t">T</h1><p data-live-path="/blocks/0">x</p>');
    const changed = [root.querySelector("p")!];
    const units = unitsFor(
      [
        { target: { selector: ".t" }, label: "Title" },
        { target: { path: "/blocks/0/text" } },
        { target: { path: "/missing" } },
        ...defaultReveal.steps({ type: "docs", previous: null, next: {}, ops: null, initial: false, root }),
      ],
      root,
      changed,
    );
    expect(units.map((u) => u.elements[0].tagName)).toEqual(["H1", "P", "P"]);
    expect(units[0].label).toBe("Title");
  });
});

describe("the player", () => {
  let host: HTMLElement;
  let view: PresenceElements;
  const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);

  beforeEach(() => {
    vi.useFakeTimers();
    host = html("");
    const make = () => host.appendChild(document.createElement("div"));
    view = { cursor: make(), frame: make(), tag: make(), pill: make() };
    animate.mockClear();
  });

  function units(n: number) {
    const root = html(Array.from({ length: n }, (_, i) => `<p>${i}</p>`).join(""));
    const elements = [...root.querySelectorAll("p")];
    for (const el of elements) (el as unknown as { animate: typeof animate }).animate = animate;
    return elements.map((el) => ({ elements: [el] }));
  }

  it("hides a batch and fades it back unit by unit, then waits for the next edit", () => {
    const player = new LivePlayer(host, view, () => false);
    player.play(units(3));
    // Three holds; nothing faded in yet but the first unit (at 0 ms).
    expect(host.dataset.phase).toBe("writing");
    vi.advanceTimersByTime(LIVE_TIMING.staggerMs * 3);
    expect(player.playing).toBe(false);
    expect(host.dataset.phase).toBe("thinking");
    // 3 holds + 3 fades.
    expect(animate).toHaveBeenCalledTimes(6);
    player.destroy();
  });

  it("finishes at once when the person acts, and stops following the writing", () => {
    const player = new LivePlayer(host, view, () => false);
    player.play(units(10));
    player.interrupt();
    expect(player.playing).toBe(false);
    expect(player.following).toBe(false);
    player.destroy();
  });

  it("plays a unit's own motion with its fade and calls its hook as it is revealed", () => {
    const player = new LivePlayer(host, view, () => false);
    const [unit] = units(1);
    const enter = vi.fn(() => [{ opacity: 0 }, { opacity: 1 }] as Keyframe[]);
    const onReveal = vi.fn();
    player.play([{ ...unit, enter, onReveal }]);
    vi.advanceTimersByTime(10);
    expect(onReveal).toHaveBeenCalledWith(unit.elements[0]);
    expect(enter).toHaveBeenCalledWith(unit.elements[0]);
    // hold + fade + the unit's own motion.
    expect(animate).toHaveBeenCalledTimes(3);
    player.destroy();
  });

  it("calls the hook but plays no motion with reduced motion", () => {
    const player = new LivePlayer(host, view, () => true);
    const [unit] = units(1);
    const enter = vi.fn(() => [{ opacity: 0 }] as Keyframe[]);
    const onReveal = vi.fn();
    player.play([{ ...unit, enter, onReveal }]);
    expect(onReveal).toHaveBeenCalledTimes(1);
    expect(enter).not.toHaveBeenCalled();
    player.destroy();
  });

  it("shows the batch at once with reduced motion", () => {
    const player = new LivePlayer(host, view, () => true);
    player.play(units(4));
    expect(player.playing).toBe(false);
    expect(animate).not.toHaveBeenCalled();
    player.destroy();
  });
  it("runs a unit's own motion on its turn, and never hides one that is already on screen", () => {
    const player = new LivePlayer(host, view, () => false);
    const [a, b] = units(2);
    const onReveal = vi.fn();
    player.play([{ ...a, onReveal }, { ...b, visible: true, onReveal }]);
    // One hold (the first unit); the visible unit is not hidden.
    expect(animate).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(LIVE_TIMING.staggerMs * 2);
    expect(onReveal).toHaveBeenCalledTimes(2);
    expect(onReveal).toHaveBeenCalledWith(a.elements[0]);
    // Hold + fade of the first unit only.
    expect(animate).toHaveBeenCalledTimes(2);
    player.destroy();
  });

  it("carries a step's own motion, visibility and solo frame into its unit", () => {
    const root = html("<p>x</p>");
    const onReveal = vi.fn();
    const [unit] = unitsFor([{ target: { selector: "p" }, onReveal, visible: true, solo: true }], root, []);
    expect(unit).toMatchObject({ visible: true, solo: true, onReveal });
  });
});
