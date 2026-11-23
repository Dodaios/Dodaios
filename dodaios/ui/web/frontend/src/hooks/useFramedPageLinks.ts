import { useEffect, type RefObject } from "react";

import { openExternalUrl } from "@/lib/openExternal";

/**
 * The message a framed page sends when the reader clicks a web link in it
 * (`PAGE_JS` in dodaios/artifacts/design_guide.py; a parity test pins the name).
 */
export const FRAMED_LINK_MESSAGE = "dodaios-open-link";

/** Two opens closer together than this are one click, or not a click at all. */
const MIN_GAP_MS = 800;

/**
 * Whether a person just clicked, as far as this window can tell.
 *
 * A click inside a framed page also counts as activity of the windows around
 * it, so a real click on a link is visible here. A page's script that posts
 * the message on its own is not. Only Chromium is known to report the frame's
 * click to this window reliably; every other engine keeps opening as before.
 */
export function clickBacked(nav: Navigator = navigator): boolean {
  const activation = (nav as Navigator & { userActivation?: { isActive: boolean } }).userActivation;
  if (!activation || !/\bChrome\//.test(nav.userAgent)) return true;
  return activation.isActive;
}

/** The web address a framed page asks to open, or null for anything else. */
export function framedLinkTarget(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; href?: unknown };
  if (message.type !== FRAMED_LINK_MESSAGE || typeof message.href !== "string") return null;
  return /^https?:\/\/[^\s]+$/i.test(message.href) && message.href.length <= 2048 ? message.href : null;
}

/**
 * Open the web links of a framed page in the person's browser.
 *
 * A page is framed without popups and without navigation, so a click on one
 * of its links (a source, a product page) would do nothing. The page tells
 * this window instead, and this window opens the address the way every other
 * link in the app opens. Only `http(s)` addresses, only from this frame, only
 * after a click (`clickBacked`), and not faster than a person clicks: the
 * page's script runs in an opaque origin and gets nothing else from this.
 */
export function useFramedPageLinks(frame: RefObject<HTMLIFrameElement | null>): void {
  useEffect(() => {
    let last = 0;
    const onMessage = (event: MessageEvent) => {
      const node = frame.current;
      if (!node || event.source !== node.contentWindow) return;
      const href = framedLinkTarget(event.data);
      if (!href || !clickBacked()) return;
      const now = Date.now();
      if (now - last < MIN_GAP_MS) return;
      last = now;
      void openExternalUrl(href);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [frame]);
}
