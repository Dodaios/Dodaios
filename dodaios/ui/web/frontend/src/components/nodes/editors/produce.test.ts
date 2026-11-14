import { describe, expect, it } from "vitest";

import { isDraft, produce } from "./produce";

interface Deck {
  title: string;
  slides: { id: string; title: string; bullets: string[] }[];
  theme: { accent: string; dark: boolean };
}

function deck(): Deck {
  return {
    title: "Plan",
    slides: [
      { id: "a", title: "One", bullets: ["x"] },
      { id: "b", title: "Two", bullets: [] },
      { id: "c", title: "Three", bullets: ["y", "z"] },
    ],
    theme: { accent: "#2A6FD0", dark: false },
  };
}

describe("produce", () => {
  it("writes a mutation into a new version and shares everything untouched", () => {
    const base = deck();
    const next = produce(base, (draft) => {
      draft.slides[1].title = "Second";
    });
    expect(next).not.toBe(base);
    expect(next.slides[1].title).toBe("Second");
    expect(base.slides[1].title).toBe("Two");
    expect(next.slides).not.toBe(base.slides);
    expect(next.slides[0]).toBe(base.slides[0]);
    expect(next.slides[2]).toBe(base.slides[2]);
    expect(next.theme).toBe(base.theme);
  });

  it("returns the base itself when nothing changed, even after reading deeply", () => {
    const base = deck();
    expect(produce(base, (draft) => void draft.slides[2].bullets.length)).toBe(base);
    expect(
      produce(base, (draft) => {
        draft.title = "Plan";
      }),
    ).toBe(base);
  });

  it("supports array methods: push, splice, reorder, filter results", () => {
    const base = deck();
    const pushed = produce(base, (draft) => {
      draft.slides[0].bullets.push("new");
    });
    expect(pushed.slides[0].bullets).toEqual(["x", "new"]);
    expect(base.slides[0].bullets).toEqual(["x"]);

    const moved = produce(base, (draft) => {
      const [first] = draft.slides.splice(0, 1);
      draft.slides.push(first);
    });
    expect(moved.slides.map((slide) => slide.id)).toEqual(["b", "c", "a"]);
    expect(moved.slides[2]).toBe(base.slides[0]);
    expect(isDraft(moved.slides[2])).toBe(false);

    const edited = produce(base, (draft) => {
      const [first] = draft.slides.splice(0, 1);
      first.title = "Moved and renamed";
      draft.slides.push(first);
    });
    expect(edited.slides[2].title).toBe("Moved and renamed");
    expect(base.slides[0].title).toBe("One");

    const removed = produce(base, (draft) => {
      draft.slides = draft.slides.filter((slide) => slide.id !== "b");
    });
    expect(removed.slides.map((slide) => slide.id)).toEqual(["a", "c"]);
    expect(isDraft(removed.slides[0])).toBe(false);
    expect(Array.isArray(removed.slides)).toBe(true);
  });

  it("takes a returned value, resolving the drafts inside it", () => {
    const base = deck();
    const next = produce(base, (draft) => ({ ...draft, title: "New", slides: [draft.slides[2]] }));
    expect(next.title).toBe("New");
    expect(next.slides[0]).toBe(base.slides[2]);
    expect(isDraft(next.slides[0])).toBe(false);
    expect(isDraft(next.theme)).toBe(false);
  });

  it("deletes keys and adds new ones", () => {
    const base = { a: 1, b: { c: 2 } } as { a?: number; b: { c: number; d?: number } };
    const next = produce(base, (draft) => {
      delete draft.a;
      draft.b.d = 3;
    });
    expect(next).toEqual({ b: { c: 2, d: 3 } });
    expect("a" in next).toBe(false);
    expect(base).toEqual({ a: 1, b: { c: 2 } });
  });

  it("lets JSON and spread read a draft as the plain value", () => {
    const base = deck();
    produce(base, (draft) => {
      expect(JSON.parse(JSON.stringify(draft))).toEqual(base);
      expect({ ...draft.theme }).toEqual(base.theme);
      expect(Object.keys(draft)).toEqual(["title", "slides", "theme"]);
    });
  });

  it("refuses a draft used after the change ended, and keeps the base on a throw", () => {
    const base = deck();
    let leaked: Deck | null = null;
    produce(base, (draft) => {
      leaked = draft;
    });
    expect(() => (leaked as unknown as Deck).title).toThrow(/after its change/);
    expect(() =>
      produce(base, (draft) => {
        draft.title = "half";
        throw new Error("boom");
      }),
    ).toThrow("boom");
    expect(base.title).toBe("Plan");
  });

  it("passes primitives through", () => {
    expect(produce(3, (n) => n + 1)).toBe(4);
    expect(produce("a", () => undefined)).toBe("a");
  });
});
