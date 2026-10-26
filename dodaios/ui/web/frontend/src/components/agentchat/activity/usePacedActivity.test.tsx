import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Activity } from "./activityModel";
import { HOLD_MS, usePacedActivity } from "./usePacedActivity";

const step = (family: Activity["family"], target = "", episode = `${family}:${target}`): Activity =>
  ({ family, phrase: family, target, episode, brand: "", peer: "" });

/** Records every value the hook hands to the line, one entry per commit. */
function Probe({ next, seen, times }: { next: Activity | null; seen: (Activity | null)[]; times?: number[] }) {
  const shown = usePacedActivity(next);
  seen.push(shown);
  times?.push(Date.now());
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(10_000);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function changes(seen: (Activity | null)[]): (Activity | null)[] {
  return seen.filter((value, i) => i === 0 || value !== seen[i - 1]);
}

describe("usePacedActivity", () => {
  it("holds a step for 800 ms and keeps only the newest waiting one", () => {
    const seen: (Activity | null)[] = [];
    const { rerender } = render(<Probe next={step("reading", "a.ts")} seen={seen} />);
    act(() => { vi.advanceTimersByTime(100); });
    rerender(<Probe next={step("searching", "x")} seen={seen} />);
    act(() => { vi.advanceTimersByTime(100); });
    rerender(<Probe next={step("running", "npm")} seen={seen} />);
    // Nothing changed yet: the first step still has its 800 ms.
    expect(seen.at(-1)?.family).toBe("reading");
    act(() => { vi.advanceTimersByTime(HOLD_MS); });
    // The queue keeps one slot: "searching" was replaced before it showed.
    expect(changes(seen).map((value) => value?.family)).toEqual(["reading", "running"]);
  });

  it("does not re-show the same step under a new episode", () => {
    const seen: (Activity | null)[] = [];
    const first = step("thinking", "", "r1");
    const { rerender } = render(<Probe next={first} seen={seen} />);
    act(() => { vi.advanceTimersByTime(2_000); });
    rerender(<Probe next={step("thinking", "", "r2")} seen={seen} />);
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(seen.at(-1)).toBe(first);
  });

  it("a step after a long one shows at once", () => {
    const seen: (Activity | null)[] = [];
    const { rerender } = render(<Probe next={step("reading", "a.ts")} seen={seen} />);
    act(() => { vi.advanceTimersByTime(5_000); });
    rerender(<Probe next={step("writing", "a.ts")} seen={seen} />);
    expect(seen.at(-1)?.family).toBe("writing");
  });

  it("a storm of steps changes the line at most once per 800 ms", () => {
    const seen: (Activity | null)[] = [];
    const times: number[] = [];
    const { rerender } = render(<Probe next={step("thinking")} seen={seen} times={times} />);
    for (let i = 0; i < 120; i++) {
      act(() => { vi.advanceTimersByTime(50); });
      rerender(<Probe next={step(i % 2 ? "reading" : "running", String(i))} seen={seen} times={times} />);
    }
    // When the shown value changed, as the line committed it.
    const stamps = seen.flatMap((value, i) => (i === 0 || value !== seen[i - 1] ? [times[i]] : []));
    expect(stamps.length).toBeGreaterThan(2);
    expect(stamps.length).toBeLessThanOrEqual(Math.ceil(6_000 / HOLD_MS) + 1);
    for (let i = 1; i < stamps.length; i++) expect(stamps[i] - stamps[i - 1]).toBeGreaterThanOrEqual(HOLD_MS);
  });
});
