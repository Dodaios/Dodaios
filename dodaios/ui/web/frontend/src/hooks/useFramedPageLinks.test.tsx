import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const openExternalUrl = vi.fn();
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: (url: string) => openExternalUrl(url) }));

import { FRAMED_LINK_MESSAGE, clickBacked, framedLinkTarget, useFramedPageLinks } from "./useFramedPageLinks";

function Framed() {
  const frame = useRef<HTMLIFrameElement>(null);
  useFramedPageLinks(frame);
  return <iframe ref={frame} title="page" data-testid="frame" />;
}

function post(source: Window | null, data: unknown) {
  window.dispatchEvent(new MessageEvent("message", { data, source }));
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  openExternalUrl.mockReset();
  vi.useRealTimers();
});

it("opens a web link the framed page asks for, once per click", () => {
  const { getByTestId } = render(<Framed />);
  const page = (getByTestId("frame") as HTMLIFrameElement).contentWindow;
  post(page, { type: FRAMED_LINK_MESSAGE, href: "https://example.test/pricing" });
  // A script that keeps asking gets one open, not a hundred tabs.
  post(page, { type: FRAMED_LINK_MESSAGE, href: "https://example.test/again" });
  expect(openExternalUrl.mock.calls).toEqual([["https://example.test/pricing"]]);
  vi.advanceTimersByTime(1000);
  post(page, { type: FRAMED_LINK_MESSAGE, href: "https://example.test/later" });
  expect(openExternalUrl).toHaveBeenCalledTimes(2);
});

it("ignores every other window and every other kind of address", () => {
  const { getByTestId } = render(<Framed />);
  const page = (getByTestId("frame") as HTMLIFrameElement).contentWindow;
  post(window, { type: FRAMED_LINK_MESSAGE, href: "https://example.test/x" });
  post(page, { type: "something-else", href: "https://example.test/x" });
  for (const href of ["javascript:alert(1)", "file:///etc/passwd", "/api/config", "https://a b", ""]) {
    post(page, { type: FRAMED_LINK_MESSAGE, href });
  }
  expect(openExternalUrl).not.toHaveBeenCalled();
  expect(framedLinkTarget({ type: FRAMED_LINK_MESSAGE, href: 7 })).toBeNull();
  expect(framedLinkTarget(null)).toBeNull();
});

function browser(userAgent: string, isActive?: boolean): Navigator {
  return {
    userAgent,
    ...(isActive === undefined ? {} : { userActivation: { isActive } }),
  } as unknown as Navigator;
}

const CHROMIUM = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0";
const WEBKIT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko)";

it("tells a click from a page that asks on its own", () => {
  expect(clickBacked(browser(CHROMIUM, true))).toBe(true);
  expect(clickBacked(browser(CHROMIUM, false))).toBe(false);
  // Engines that do not report the frame's click here keep working as before.
  expect(clickBacked(browser(WEBKIT, false))).toBe(true);
  expect(clickBacked(browser(CHROMIUM))).toBe(true);
});

it("opens nothing for a framed page that asks without a click", () => {
  const original = Object.getOwnPropertyDescriptor(window.navigator, "userActivation");
  const agent = vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(CHROMIUM);
  let active = false;
  Object.defineProperty(window.navigator, "userActivation", {
    configurable: true,
    get: () => ({ isActive: active }),
  });
  try {
    const { getByTestId } = render(<Framed />);
    const page = (getByTestId("frame") as HTMLIFrameElement).contentWindow;
    for (let i = 0; i < 5; i += 1) {
      post(page, { type: FRAMED_LINK_MESSAGE, href: `https://example.test/unasked-${i}` });
      vi.advanceTimersByTime(1000);
    }
    expect(openExternalUrl).not.toHaveBeenCalled();

    active = true;
    post(page, { type: FRAMED_LINK_MESSAGE, href: "https://example.test/clicked" });
    expect(openExternalUrl.mock.calls).toEqual([["https://example.test/clicked"]]);
  } finally {
    agent.mockRestore();
    if (original) Object.defineProperty(window.navigator, "userActivation", original);
    else delete (window.navigator as unknown as Record<string, unknown>).userActivation;
  }
});
