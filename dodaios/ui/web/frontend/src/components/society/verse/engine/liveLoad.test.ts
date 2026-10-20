import { describe, expect, it, vi } from "vitest";
import { isAbortError, liveLoad } from "./liveLoad";

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("live loads", () => {
  it("reports a result while wanted, and an error that is not an abort", async () => {
    const done = vi.fn();
    const failed = vi.fn();
    liveLoad(Promise.resolve(7), done, failed);
    liveLoad(Promise.reject(new Error("HTTP 404")), done, failed);
    await tick();
    expect(done).toHaveBeenCalledWith(7);
    expect(failed).toHaveBeenCalledWith(expect.objectContaining({ message: "HTTP 404" }));
  });

  it("never turns an abort into a deck failure (regression: stuck on 'deck missing')", async () => {
    const failed = vi.fn();
    liveLoad(Promise.reject(new DOMException("The user aborted a request.", "AbortError")), vi.fn(), failed);
    await tick();
    expect(failed).not.toHaveBeenCalled();
    expect(isAbortError(new DOMException("x", "AbortError"))).toBe(true);
    expect(isAbortError(new Error("x"))).toBe(false);
  });

  it("ignores results and errors that arrive after the owner let go", async () => {
    const done = vi.fn();
    const failed = vi.fn();
    let resolve!: (v: number) => void;
    let reject!: (e: Error) => void;
    const stopA = liveLoad(new Promise<number>((r) => { resolve = r; }), done, failed);
    const stopB = liveLoad(new Promise<number>((_, r) => { reject = r; }), done, failed);
    stopA();
    stopB();
    resolve(1);
    reject(new Error("late"));
    await tick();
    expect(done).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
  });
});
