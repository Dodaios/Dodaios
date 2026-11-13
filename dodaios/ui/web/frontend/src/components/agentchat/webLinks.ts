/**
 * How the chat names a web link: the website's name for the hover card, and a
 * short name for the link itself when the answer wrote the bare address.
 *
 * A link the assistant gave its own words (`[Dodaios repo](https://…)`) keeps
 * them. A bare address (`https://www.reddit.com/r/LocalLLaMA/comments/1x/local_first_tool/`)
 * is shortened to the few words that say what it is (`Local first tool`); the
 * full address stays one hover away.
 */

/** Named websites: the name a person knows them by. Keys are hosts without `www.`. */
const SITE_NAMES: Record<string, string> = {
  "x.com": "X",
  "twitter.com": "X",
  "github.com": "GitHub",
  "gist.github.com": "GitHub Gist",
  "gitlab.com": "GitLab",
  "reddit.com": "Reddit",
  "old.reddit.com": "Reddit",
  "news.ycombinator.com": "Hacker News",
  "ycombinator.com": "Y Combinator",
  "youtube.com": "YouTube",
  "youtu.be": "YouTube",
  "m.youtube.com": "YouTube",
  "linkedin.com": "LinkedIn",
  "wikipedia.org": "Wikipedia",
  "medium.com": "Medium",
  "stackoverflow.com": "Stack Overflow",
  "producthunt.com": "Product Hunt",
  "instagram.com": "Instagram",
  "facebook.com": "Facebook",
  "tiktok.com": "TikTok",
  "threads.net": "Threads",
  "bsky.app": "Bluesky",
  "discord.com": "Discord",
  "discord.gg": "Discord",
  "huggingface.co": "Hugging Face",
  "npmjs.com": "npm",
  "pypi.org": "PyPI",
  "arxiv.org": "arXiv",
  "substack.com": "Substack",
  "docs.google.com": "Google Docs",
  "drive.google.com": "Google Drive",
  "google.com": "Google",
  "maps.google.com": "Google Maps",
  "apps.apple.com": "App Store",
  "apple.com": "Apple",
  "amazon.com": "Amazon",
  "amazon.de": "Amazon",
  "notion.so": "Notion",
  "figma.com": "Figma",
  "vercel.com": "Vercel",
  "spotify.com": "Spotify",
  "open.spotify.com": "Spotify",
};

/** The longest short name drawn in the text; longer ones end in an ellipsis. */
export const MAX_LABEL_CHARS = 56;

export interface WebLinkInfo {
  /** The address to open, as written. */
  url: string;
  /** Host without `www.`, which also names the logo (`/api/link-icon?host=…`). */
  host: string;
  /** The website's name: a known name (`Reddit`) or the host. */
  site: string;
  /** What the link shows; null keeps the words the answer wrote. */
  label: string | null;
  /** Short words that depend on the language; see {@link shortLabel}. */
  kind?: { type: "x_post"; user: string } | { type: "video" } | { type: "discussion" };
}

/** The address as a URL when it is a web address (http or https), else null. */
export function webUrl(href: string): URL | null {
  if (!/^https?:\/\//i.test(href)) return null;
  try {
    const url = new URL(href);
    return url.hostname ? url : null;
  } catch {
    return null;
  }
}

export function bareHost(url: URL): string {
  return url.hostname.toLowerCase().replace(/^www\./, "").replace(/\.$/, "");
}

/** The website's name for a host: a known name, the parent's known name, or the host itself. */
export function siteName(host: string): string {
  if (SITE_NAMES[host]) return SITE_NAMES[host];
  // en.wikipedia.org, de.linkedin.com, someone.substack.com
  const parent = host.split(".").slice(1).join(".");
  if (parent.includes(".") && SITE_NAMES[parent]) return SITE_NAMES[parent];
  return host;
}

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Shortened to {@link MAX_LABEL_CHARS} on a word boundary, with an ellipsis. */
export function clip(text: string, max = MAX_LABEL_CHARS): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,.;:–-]+$/, "")}…`;
}

/** A path segment written as words (`local_first-tool.html` → `Local first tool`), or null for an id. */
export function humanize(segment: string): string | null {
  const name = decode(segment).replace(/\.(?:html?|php|aspx?|jsp|md)$/i, "");
  // Ids and dates inside a slug go (`merz-trifft-a-1234abcd`, `2026-11-13-launch`).
  const tokens = name.replace(/[-_+]+/g, " ").split(/\s+/).filter(Boolean);
  const kept = tokens.length > 1 ? tokens.filter(token => !(/\d/.test(token) && token.length >= 6) && !/^\d{2,}$/.test(token)) : tokens;
  while (kept.length > 1 && kept[kept.length - 1].length === 1) kept.pop();
  const words = kept.join(" ");
  if (!words || words.length < 3) return null;
  // An id, a hash or a number is no name: `1x9k2ab`, `a3f9c2d1e8`, `123456`.
  const letters = (words.match(/\p{L}/gu) ?? []).length;
  const digits = (words.match(/\d/g) ?? []).length;
  if (!words.includes(" ") && (digits > 0 && digits >= letters / 2)) return null;
  if (!words.includes(" ") && /^[0-9a-f]{8,}$/i.test(words)) return null;
  if (letters < 2) return null;
  return clip(words.charAt(0).toUpperCase() + words.slice(1));
}

function segments(url: URL): string[] {
  return url.pathname.split("/").filter(Boolean);
}

function githubLabel(parts: string[]): string | null {
  const [owner, repo, section, ...rest] = parts;
  if (!owner) return null;
  if (!repo) return owner;
  const name = `${owner}/${repo.replace(/\.git$/, "")}`;
  if ((section === "pull" || section === "issues" || section === "discussions") && /^\d+$/.test(rest[0] ?? "")) {
    return `${name} #${rest[0]}`;
  }
  if (section === "releases" && rest[0] === "tag" && rest[1]) return `${name} ${decode(rest[1])}`;
  if ((section === "blob" || section === "tree") && rest.length > 1) return decode(rest[rest.length - 1]);
  return name;
}

function redditLabel(parts: string[]): string | null {
  const [kind, name, section, , slug] = parts;
  if ((kind === "r" || kind === "u" || kind === "user") && name) {
    if (section === "comments" && slug) return humanize(slug) ?? `${kind === "r" ? "r" : "u"}/${name}`;
    return `${kind === "r" ? "r" : "u"}/${name}`;
  }
  return null;
}

/**
 * The link's name and short label.
 *
 * `written` is the text the answer gave the link, null when it is more than
 * text (bold words, code). When it is the address itself (an autolinked bare
 * URL, or a label that is just a URL or a domain path), the label is built
 * from the address; otherwise it is kept.
 */
export function webLinkInfo(href: string, written: string | null): WebLinkInfo | null {
  const url = webUrl(href);
  if (!url) return null;
  const host = bareHost(url);
  const site = siteName(host);
  const info: WebLinkInfo = { url: href, host, site, label: null };
  if (written === null || !looksLikeAddress(written)) return info;
  const parts = segments(url);

  if (host === "x.com" || host === "twitter.com") {
    const [user, section] = parts;
    if (user && section === "status") return { ...info, label: null, kind: { type: "x_post", user } };
    if (user && !["home", "search", "explore", "i", "intent", "hashtag"].includes(user)) return { ...info, label: `@${user}` };
    return { ...info, label: site };
  }
  if (host === "github.com") return { ...info, label: githubLabel(parts) ?? site };
  if (host === "reddit.com" || host === "old.reddit.com") return { ...info, label: redditLabel(parts) ?? site };
  if (host === "news.ycombinator.com") {
    return url.pathname === "/item" ? { ...info, kind: { type: "discussion" } } : { ...info, label: site };
  }
  if (host === "youtube.com" || host === "m.youtube.com" || host === "youtu.be") {
    if (parts[0]?.startsWith("@")) return { ...info, label: decode(parts[0]) };
    if (host === "youtu.be" || url.pathname === "/watch" || parts[0] === "shorts") return { ...info, kind: { type: "video" } };
    return { ...info, label: site };
  }
  if (site === "Wikipedia" && parts[0] === "wiki" && parts[1]) {
    return { ...info, label: clip(decode(parts[1]).replace(/_/g, " ")) };
  }
  if (host === "linkedin.com" && (parts[0] === "in" || parts[0] === "company") && parts[1]) {
    return { ...info, label: humanize(parts[1]) ?? site };
  }
  // Any other site: the last part of the path that reads as words, else the site.
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const words = humanize(parts[index]);
    if (words) return { ...info, label: words };
  }
  return { ...info, label: site };
}

/**
 * Whether the words a link shows are its address rather than a name: a URL,
 * `www.…`, or a domain with a path (`github.com/org/repo`).
 */
export function looksLikeAddress(written: string): boolean {
  const text = written.trim();
  if (!text) return true;
  if (/\s/.test(text)) return false;
  if (/^(?:https?:\/\/|www\.)/i.test(text)) return true;
  return /^[a-z0-9-]+(?:\.[a-z0-9-]+)+\/\S*$/i.test(text);
}

/** Where the chat loads a website's logo from (the backend keeps a copy per site). */
export function linkIconUrl(host: string): string {
  return `/api/link-icon?host=${encodeURIComponent(host)}`;
}

/** The address as shown on the hover card: without `https://` and a trailing slash. */
export function displayAddress(href: string): string {
  return href.replace(/^https?:\/\//i, "").replace(/\/$/, "");
}
