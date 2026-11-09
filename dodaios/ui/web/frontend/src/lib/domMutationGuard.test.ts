import { describe, expect, it, vi } from "vitest";

import { installDomMutationGuard } from "./domMutationGuard";

describe("installDomMutationGuard", () => {
  installDomMutationGuard();

  it("appends when the reference node was moved out by a page translator", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const parent = document.createElement("div");
    const reference = document.createElement("span");
    parent.append(reference);
    // The translator wraps the node it translated in its own element.
    const wrapper = document.createElement("font");
    parent.replaceChild(wrapper, reference);
    wrapper.append(reference);

    const fresh = document.createElement("p");
    expect(() => parent.insertBefore(fresh, reference)).not.toThrow();
    expect(fresh.parentNode).toBe(parent);
    warn.mockRestore();
  });

  it("skips removing a node that is no longer a child", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const parent = document.createElement("div");
    const elsewhere = document.createElement("div");
    const child = document.createElement("span");
    elsewhere.append(child);

    expect(() => parent.removeChild(child)).not.toThrow();
    expect(child.parentNode).toBe(elsewhere);
    warn.mockRestore();
  });

  it("leaves ordinary inserts and removals unchanged", () => {
    const parent = document.createElement("div");
    const first = document.createElement("i");
    const second = document.createElement("b");
    parent.append(second);
    parent.insertBefore(first, second);
    expect(Array.from(parent.children)).toEqual([first, second]);
    parent.removeChild(first);
    expect(Array.from(parent.children)).toEqual([second]);
  });
});
