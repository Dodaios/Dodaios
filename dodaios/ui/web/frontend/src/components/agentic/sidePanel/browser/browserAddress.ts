const LOCAL_HOST = /^(localhost|127(?:\.\d{1,3}){3}|\[::1\]|0\.0\.0\.0)(?::\d+)?(?:[/?#]|$)/i;
const BARE_PORT = /^:?\d{2,5}(?:[/?#]|$)/;
const SCHEME = /^[a-z][a-z\d+.-]*:\/\//i;
// One word and nothing else: no dot, port, path or scheme ("github", "wetter").
const ONE_WORD = /^[^\s./:?#]+$/;

/** Where a search from the address bar goes. Shown in the person's own browser. */
export function searchAddress(query: string): string {
  return `https://www.google.com/search?q=${encodeURIComponent(query.trim())}`;
}

export type BrowserInput =
  | { kind: "address"; url: string }
  | { kind: "search"; query: string; url: string };

/**
 * What the reader typed into the address bar: an address to load, or a search.
 *
 * A single word without a dot ("github") and anything with spaces is a
 * search, as in every browser's address bar; `localhost` stays an address.
 * Without this, "github" became `https://github/`, a host that does not
 * exist, and text with spaces did nothing at all.
 */
export function readBrowserInput(raw: string): BrowserInput | null {
  const text = raw.trim();
  if (!text) return null;
  if (/\s/.test(text) || (ONE_WORD.test(text) && !LOCAL_HOST.test(text) && !BARE_PORT.test(text))) {
    return { kind: "search", query: text, url: searchAddress(text) };
  }
  const url = normalizeBrowserAddress(text);
  return url ? { kind: "address", url } : null;
}

/**
 * Turn what the reader typed into an address the browser surface can load.
 *
 * A bare port (`5173`, `:5173`) and a local host go over plain http, the way
 * dev servers listen; anything else without a scheme gets https. Only web
 * schemes pass: `javascript:`, `file:` and friends return null.
 */
export function normalizeBrowserAddress(raw: string): string | null {
  const text = raw.trim();
  if (!text || /\s/.test(text)) return null;
  let candidate: string;
  if (BARE_PORT.test(text)) candidate = `http://localhost:${text.replace(/^:/, "")}`;
  else if (SCHEME.test(text)) candidate = text;
  else if (LOCAL_HOST.test(text)) candidate = `http://${text}`;
  else candidate = `https://${text}`;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    if (!parsed.hostname) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

/**
 * The word a stored address was made from, when the old address bar turned a
 * search word into a host (`https://github/`): one label, https, no port, no
 * path. Such a host never answers, so the panel offers the word again instead.
 */
export function wordFromBrokenAddress(url: string): string | null {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname;
    if (parsed.protocol !== "https:" || parsed.port || host.includes(".") || host.includes(":")) return null;
    if (isLocalBrowserAddress(url) || (parsed.pathname !== "/" && parsed.pathname !== "")) return null;
    if (parsed.search || parsed.hash) return null;
    return host;
  } catch {
    return null;
  }
}

/** A local address (a dev server on this machine): no site policy to ask about. */
export function isLocalBrowserAddress(url: string): boolean {
  try {
    const { hostname } = new URL(url);
    return /^(localhost|127(?:\.\d{1,3}){3}|\[::1\]|0\.0\.0\.0)$/i.test(hostname);
  } catch {
    return false;
  }
}
