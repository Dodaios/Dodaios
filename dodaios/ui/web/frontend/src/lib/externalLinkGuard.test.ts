import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const openExternalUrl = vi.fn(async (_url: string) => true);
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: (url: string) => openExternalUrl(url) }));

import { installExternalLinkGuard, safeWebUrl, unhandledLinkAction } from "./externalLinkGuard";

const HERE = { href: "http://127.0.0.1:47821/threads/abc", origin: "http://127.0.0.1:47821" };

function anchor(href: string | null, attrs: Record<string, string> = {}): HTMLAnchorElement {
  const a = document.createElement("a");
  if (href !== null) a.setAttribute("href", href);
  for (const [name, value] of Object.entries(attrs)) a.setAttribute(name, value);
  a.textContent = "link";
  document.body.appendChild(a);
  return a;
}

/** Click and report whether the browser would still navigate. */
function click(node: HTMLElement): boolean {
  let navigates = false;
  // Last in line: note what the page decided, then keep jsdom from navigating.
  const last = (event: Event) => {
    navigates = !event.defaultPrevented;
    event.preventDefault();
  };
  window.addEventListener("click", last);
  node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, composed: true }));
  window.removeEventListener("click", last);
  return navigates;
}

let uninstall: () => void = () => {};

beforeEach(() => {
  uninstall = installExternalLinkGuard();
});
afterEach(() => {
  uninstall();
  document.body.innerHTML = "";
  openExternalUrl.mockClear();
});

describe("unhandledLinkAction", () => {
  it("opens web addresses of other sites outside the app", () => {
    for (const href of ["https://example.test/a", "http://example.test", "//example.test/x"]) {
      expect(unhandledLinkAction(anchor(href), HERE)).toBe("external");
    }
    // Another server on this machine is another site too.
    expect(unhandledLinkAction(anchor("http://127.0.0.1:3000/"), HERE)).toBe("external");
    expect(unhandledLinkAction(anchor("http://localhost:47821/"), HERE)).toBe("external");
  });

  it("leaves the app's own addresses, downloads and mail links alone", () => {
    for (const href of ["/settings", "#section", "?tab=2", "notes.md", "/api/outputs/1/download"]) {
      expect(unhandledLinkAction(anchor(href), HERE)).toBe("leave");
    }
    expect(unhandledLinkAction(anchor("mailto:someone@example.test"), HERE)).toBe("leave");
    expect(unhandledLinkAction(anchor("data:text/plain,hi", { download: "a.txt" }), HERE)).toBe("leave");
    expect(unhandledLinkAction(anchor(null), HERE)).toBe("leave");
    expect(unhandledLinkAction(anchor(""), HERE)).toBe("leave");
  });

  it("blocks every other scheme that would replace the window", () => {
    for (const href of ["file:///C:/Windows/win.ini", "data:text/html,<p>x</p>", "ms-settings:privacy", "ftp://example.test/x"]) {
      expect(unhandledLinkAction(anchor(href), HERE)).toBe("block");
    }
  });
});

describe("installExternalLinkGuard", () => {
  it("keeps a plain Markdown link from loading another site in the app window", () => {
    const link = anchor("https://example.test/landing");

    const navigates = click(link);

    expect(navigates).toBe(false);
    expect(openExternalUrl.mock.calls).toEqual([["https://example.test/landing"]]);
  });

  it("finds the link when the click lands on something inside it", () => {
    const link = anchor("https://example.test/with-code");
    const inner = document.createElement("code");
    link.appendChild(inner);

    expect(click(inner)).toBe(false);
    expect(openExternalUrl).toHaveBeenCalledTimes(1);
  });

  it("stops other schemes without opening anything", () => {
    expect(click(anchor("file:///C:/Windows/win.ini"))).toBe(false);
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("does not touch links of the app or links a component already handled", () => {
    expect(click(anchor("/settings"))).toBe(true);

    const handled = anchor("https://example.test/handled");
    handled.addEventListener("click", (event) => event.preventDefault());
    click(handled);

    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("stops guarding once removed", () => {
    uninstall();

    expect(click(anchor("https://example.test/later"))).toBe(true);
    expect(openExternalUrl).not.toHaveBeenCalled();
  });
});

describe("safeWebUrl", () => {
  it("passes an http(s) address and nothing else", () => {
    expect(safeWebUrl("https://a.example/x")).toBe("https://a.example/x");
    expect(safeWebUrl("  HTTP://a.example ")).toBe("http://a.example/");
    expect(safeWebUrl("javascript:alert(1)")).toBeNull();
    expect(safeWebUrl("file:///x")).toBeNull();
    expect(safeWebUrl("ms-settings:")).toBeNull();
    expect(safeWebUrl("search-ms:query=x")).toBeNull();
    expect(safeWebUrl("//evil.example/")).toBeNull();
    expect(safeWebUrl("")).toBeNull();
    expect(safeWebUrl(undefined)).toBeNull();
  });
});
