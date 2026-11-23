import { openExternalUrl } from "@/lib/openExternal";

/**
 * What a click on a link does when no component handled it.
 *
 * `leave`    the browser's own behaviour is right (an address of this app, a
 *            download, a mail link);
 * `external` a web address elsewhere: it opens in the person's browser;
 * `block`    anything else that would replace this window.
 */
export type UnhandledLinkAction = "leave" | "external" | "block";

export function unhandledLinkAction(
  anchor: HTMLAnchorElement,
  here: { href: string; origin: string } = window.location,
): UnhandledLinkAction {
  const raw = anchor.getAttribute("href");
  if (raw === null || raw.trim() === "" || anchor.hasAttribute("download")) return "leave";
  let url: URL;
  try {
    url = new URL(raw, here.href);
  } catch {
    return "block";
  }
  if (url.origin === here.origin) return "leave";
  if (url.protocol === "http:" || url.protocol === "https:") return "external";
  if (url.protocol === "mailto:" || url.protocol === "tel:") return "leave";
  return "block";
}

function clickedAnchor(event: MouseEvent): HTMLAnchorElement | null {
  for (const node of event.composedPath()) {
    if (node instanceof HTMLAnchorElement) return node;
  }
  return null;
}

/**
 * Keep a link from replacing the app window with another site.
 *
 * Text the app shows is often written elsewhere: a model's reasoning, a
 * message between agents, a README of a cloned project, a skill's
 * description. Several views render it as plain Markdown, where a link is an
 * ordinary link, and one click loaded that site in place of the app. The
 * desktop window has no address bar, so the page shown there could pass for
 * the app. Chat links already opened in the person's browser; this makes
 * every link that no component handles behave the same.
 *
 * Runs after the components' own click handlers (they sit below `document`),
 * and leaves alone whatever they already handled.
 */
export function installExternalLinkGuard(target: Document = document): () => void {
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented) return;
    const anchor = clickedAnchor(event);
    if (!anchor) return;
    const action = unhandledLinkAction(anchor);
    if (action === "leave") return;
    event.preventDefault();
    if (action === "external") void openExternalUrl(anchor.href);
  };
  target.addEventListener("click", onClick);
  return () => target.removeEventListener("click", onClick);
}
