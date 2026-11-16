import { afterEach, describe, expect, it } from "vitest";

import { moveKeepingPlace } from "./moveKeepingPlace";

/** A conversation element with one scroll area in it, sized by hand (jsdom lays nothing out). */
function conversation(scroll: { height: number; client: number; top: number }) {
  const element = document.createElement("div");
  const viewport = document.createElement("div");
  viewport.setAttribute("data-radix-scroll-area-viewport", "");
  Object.defineProperty(viewport, "scrollHeight", { configurable: true, get: () => scroll.height });
  Object.defineProperty(viewport, "clientHeight", { configurable: true, get: () => scroll.client });
  viewport.scrollTop = scroll.top;
  element.appendChild(viewport);
  return { element, viewport };
}

const place = () => document.body.appendChild(document.createElement("div"));

afterEach(() => {
  document.body.innerHTML = "";
});

describe("moving a drawn conversation", () => {
  it("moves the very element, and leaves it alone where it already stands", () => {
    const home = place();
    const window_ = place();
    const { element } = conversation({ height: 1000, client: 200, top: 0 });
    moveKeepingPlace(element, home);
    expect(home.lastElementChild).toBe(element);
    moveKeepingPlace(element, window_);
    expect(window_.lastElementChild).toBe(element);
    expect(home.childElementCount).toBe(0);
    // Asked again for the same place: nothing is taken off the page.
    const marker = document.createElement("span");
    window_.appendChild(marker);
    moveKeepingPlace(element, window_);
    expect(window_.lastElementChild).toBe(marker);
  });

  it("keeps a reader at the end of the conversation at its end", () => {
    const home = place();
    const narrow = place();
    const { element, viewport } = conversation({ height: 1000, client: 200, top: 800 });
    moveKeepingPlace(element, home);
    // Beside a node the same conversation is narrower, so it is longer: the
    // height changes with the move itself, as it does in a browser.
    Object.defineProperty(viewport, "scrollHeight", {
      configurable: true,
      get: () => (element.parentElement === narrow ? 1600 : 1000),
    });
    moveKeepingPlace(element, narrow);
    expect(viewport.scrollTop).toBe(1600);
  });

  it("keeps the message that led the view at the same height for a reader further up", () => {
    const home = place();
    const narrow = place();
    const { element, viewport } = conversation({ height: 3000, client: 200, top: 400 });
    const message = document.createElement("div");
    message.setAttribute("data-message-id", "m-1");
    viewport.appendChild(message);
    viewport.getBoundingClientRect = () => ({ top: 100, bottom: 300 }) as DOMRect;
    // Before the move the message starts 40px under the viewport's top edge;
    // after it (narrower, so everything above grew) 190px under it.
    message.getBoundingClientRect = () => {
      const top = element.parentElement === narrow ? 290 : 140;
      return { top, bottom: top + 80 } as DOMRect;
    };
    moveKeepingPlace(element, home);
    moveKeepingPlace(element, narrow);
    // Scrolled on by the 150px the message moved down.
    expect(viewport.scrollTop).toBe(550);
  });
});
