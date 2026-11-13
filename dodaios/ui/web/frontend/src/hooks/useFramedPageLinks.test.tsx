import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const openExternalUrl = vi.fn();
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: (url: string) => openExternalUrl(url) }));

import { FRAMED_LINK_MESSAGE, framedLinkTarget, useFramedPageLinks } from "./useFramedPageLinks";

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
