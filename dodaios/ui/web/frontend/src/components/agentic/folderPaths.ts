/**
 * Reading paths the way a person types them — the pure half of the folder
 * picker, kept apart from the component so each rule can be tested by itself.
 *
 * Nothing here touches the disk or knows which operating system the BACKEND
 * runs on. The UI may be open on a different machine than the one whose
 * folders it lists, so every rule reads its answer off a real path the backend
 * handed out (see `separatorOf`) instead of asking the browser.
 */
import { fill, translate, useI18nStore } from "@/i18n";
import { localeForUiLanguage } from "@/components/runs/format";

/**
 * Pull whatever identifies the dropped folder out of a DataTransfer.
 *
 * This MUST run synchronously inside the drop handler: a DataTransfer is
 * emptied as soon as the event returns, so reading it after an `await` yields
 * nothing. Three sources, in order of how much they tell us:
 *
 * 1. `text/uri-list` / `text/plain` — Explorer and Finder usually put the real
 *    path here, which resolves exactly.
 * 2. `webkitGetAsEntry()` — gives the folder's NAME (never its path; that is a
 *    deliberate browser restriction), which the backend can search for.
 * 3. `webkitRelativePath` of a dropped file — its first segment is the folder
 *    name, which covers dropping a file from inside the project.
 */
export function extractDropPayload(dt: DataTransfer | null): {
  path?: string;
  name?: string;
} {
  if (!dt) return {};
  const out: { path?: string; name?: string } = {};

  const uri = dt.getData("text/uri-list") || dt.getData("text/plain");
  if (uri) {
    const first = uri.split(/[\r\n]+/).find((line) => line.trim().length > 0);
    if (first) out.path = first.trim();
  }

  const items = dt.items ? Array.from(dt.items) : [];
  for (const item of items) {
    const getAsEntry = (
      item as DataTransferItem & {
        webkitGetAsEntry?: () => { isDirectory?: boolean; name?: string } | null;
      }
    ).webkitGetAsEntry;
    const entry =
      typeof getAsEntry === "function" ? getAsEntry.call(item) : null;
    if (entry?.isDirectory && entry.name) {
      out.name = entry.name;
      break;
    }
  }

  if (!out.name && dt.files && dt.files.length > 0) {
    const rel = (dt.files[0] as File & { webkitRelativePath?: string })
      .webkitRelativePath;
    if (rel && rel.includes("/")) out.name = rel.split("/")[0];
  }

  return out;
}

/** Where the typed text stops being a folder and starts being what to match. */
export function splitTypedPath(value: string): { dir: string; leaf: string } {
  const cut = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
  if (cut < 0) return { dir: "", leaf: value };
  return { dir: value.slice(0, cut + 1), leaf: value.slice(cut + 1) };
}

/**
 * The folder part and the name part of what is being typed, for the list
 * under the field.
 *
 * `dir` is the folder whose contents the list shows and `leaf` narrows them.
 * A bare word has no folder part: it narrows the folder already on screen.
 * The words that ARE a folder by themselves (`..`, `~`, a bare drive) have no
 * name part, so the list shows what is inside them.
 */
export function typedParts(typed: string): { dir: string; leaf: string } {
  if (typed === "." || typed === ".." || typed === "~" || /^[a-zA-Z]:$/.test(typed)) {
    return { dir: typed, leaf: "" };
  }
  return splitTypedPath(typed);
}

/**
 * The separator this machine uses, read off a real path instead of guessed.
 *
 * A web page cannot know whether the backend is Windows or not, and guessing
 * from `navigator` would describe the wrong computer entirely when the UI is
 * open on a different one. Every path the backend hands out already contains
 * the answer.
 */
export function separatorOf(fullPath: string): string {
  return fullPath.includes("\\") ? "\\" : "/";
}

export function joinPath(base: string, name: string): string {
  const sep = separatorOf(base);
  return base.endsWith(sep) ? `${base}${name}` : `${base}${sep}${name}`;
}

/** The last segment of a path — what a person calls the folder. */
export function leafName(fullPath: string): string {
  const trimmed = fullPath.replace(/[\\/]+$/, "");
  return trimmed.split(/[\\/]/).pop() || fullPath;
}

/**
 * A path as the crumbs of an address bar, each one a place to go.
 *
 * The root keeps its own shape — `C:` on Windows, `/` elsewhere, the whole
 * `\\server\share` of a network path, since a server alone is not a folder
 * anyone can open.
 */
export function pathCrumbs(fullPath: string): { label: string; path: string }[] {
  const sep = separatorOf(fullPath);
  let root = "";
  let rest = fullPath;
  const unc = fullPath.match(/^([\\/]{2}[^\\/]+[\\/]+[^\\/]+)[\\/]*(.*)$/);
  const drive = fullPath.match(/^([a-zA-Z]:)[\\/]*(.*)$/);
  if (unc) {
    root = unc[1];
    rest = unc[2];
  } else if (drive) {
    root = `${drive[1]}${sep}`;
    rest = drive[2];
  } else if (/^[\\/]/.test(fullPath)) {
    root = sep;
    rest = fullPath.replace(/^[\\/]+/, "");
  }
  const crumbs: { label: string; path: string }[] = [];
  if (root) {
    crumbs.push({ label: root === sep ? sep : root.replace(/[\\/]+$/, ""), path: root });
  }
  let acc = root;
  for (const part of rest.split(/[\\/]+/).filter(Boolean)) {
    acc = acc ? joinPath(acc, part) : part;
    crumbs.push({ label: part, path: acc });
  }
  return crumbs;
}

/**
 * The folder above `fullPath`, or null at a root.
 *
 * Worked out from the path itself, not taken from the last listing: the
 * address bar moves the moment a folder is clicked, before its listing has
 * arrived, and "up" has to mean up from where the bar says we are.
 */
export function parentPath(fullPath: string): string | null {
  const crumbs = pathCrumbs(fullPath);
  return crumbs.length > 1 ? crumbs[crumbs.length - 2].path : null;
}

/** More crumbs than this and the middle ones fold into "…". */
const CRUMBS_MAX = 4;

/**
 * A long path keeps its root and the two folders nearest the end; the middle
 * folds into one "…" crumb that leads to the last folder it hides.
 */
export function foldCrumbs(
  crumbs: { label: string; path: string }[],
): { label: string; path: string; folded?: boolean }[] {
  if (crumbs.length <= CRUMBS_MAX) return crumbs;
  const hidden = crumbs.slice(1, -2);
  return [
    crumbs[0],
    { label: "…", path: hidden[hidden.length - 1].path, folded: true },
    ...crumbs.slice(-2),
  ];
}

/** Two folder names that the file system would treat as the same one. */
export function sameName(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/** Two paths that name the same folder, whatever separator ends them. */
export function samePath(a: string | null, b: string | null): boolean {
  if (a === null || b === null) return a === b;
  const tidy = (value: string) => value.replace(/[\\/]+$/, "").toLowerCase();
  return tidy(a) === tidy(b);
}

/**
 * The folders that match a typed word: names that START with it first, names
 * that merely contain it after, each group in the order it came in.
 */
export function matchByName<T extends { name: string }>(entries: T[], word: string): T[] {
  const needle = word.toLowerCase();
  if (!needle) return entries;
  const starts: T[] = [];
  const contains: T[] = [];
  for (const entry of entries) {
    const name = entry.name.toLowerCase();
    if (name.startsWith(needle)) starts.push(entry);
    else if (name.includes(needle)) contains.push(entry);
  }
  return [...starts, ...contains];
}

/** A name that can be given to one new folder: one segment, no wildcards. */
export function isFolderName(value: string): boolean {
  const name = value.trim();
  return Boolean(name) && name !== "." && name !== ".." && !/[\\/:*?"<>|]/.test(name);
}

/**
 * When a recent folder was last opened, the way people say it.
 *
 * Counted in calendar days on this clock, so something opened late last night
 * is "Yesterday" this morning, not "Today". Accepts seconds (what the backend
 * stores) or milliseconds.
 */
export function lastUsedLabel(lastUsed: number, now: number = Date.now()): string {
  if (!lastUsed || !Number.isFinite(lastUsed)) return "";
  const ms = lastUsed > 1e12 ? lastUsed : lastUsed * 1000;
  const dayStart = (t: number) => {
    const d = new Date(t);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  };
  const days = Math.round((dayStart(now) - dayStart(ms)) / 86_400_000);
  if (days <= 0) return translate("ide_folder_picker.today");
  if (days === 1) return translate("ide_folder_picker.yesterday");
  if (days < 7) return fill(translate("ide_folder_picker.days_ago"), { count: days });
  if (days < 30) {
    const weeks = Math.floor(days / 7);
    return weeks === 1
      ? translate("ide_folder_picker.last_week")
      : fill(translate("ide_folder_picker.weeks_ago"), { count: weeks });
  }
  return new Date(ms).toLocaleDateString(localeForUiLanguage(useI18nStore.getState().ui), {
    day: "numeric",
    month: "short",
    year: days > 300 ? "numeric" : undefined,
  });
}

/**
 * What was typed, read the way a shell would read it.
 *
 * People type `cd projects` — the command word is not part of the path and is
 * dropped (with cmd's `/d`), and so are quotes around a path pasted from a
 * terminal.
 */
export function normalizeTypedPath(raw: string): string {
  let value = raw.trim();
  value = value.replace(/^cd(?:\s+\/d)?(?:\s+|$)/i, "").trim();
  // A prompt copied whole — `PS C:\Users\me>` — is the path with a shell's
  // decoration on both ends; the decoration is not part of the folder.
  value = value.replace(/^PS\s+/, "").replace(/\s*>$/, "").trim();
  const quoted = value.match(/^(["'])(.*)\1$/);
  if (quoted) value = quoted[2].trim();
  return value;
}

/** A path that names its own root: `/…`, `~…`, `C:\…`, or a UNC `\\server`. */
export function isAbsolutePath(value: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|[\\/]|~)/.test(value);
}

/**
 * Text that names a PLACE rather than a folder to look for.
 *
 * A root or a separator anywhere is the tell: nobody searches for a folder
 * called `Desktop\shop`, they mean the one at that path. A bare name stays a
 * search, which is what a search field is for.
 */
export function looksLikePath(value: string): boolean {
  return isAbsolutePath(value) || /[\\/]/.test(value);
}

/**
 * The folder a typed path means, given the folder on screen.
 *
 * Anything that does not name its own root is relative to what the list shows
 * — `haral\.personal-jarvis` typed while looking at `C:\Users` is
 * `C:\Users\haral\.personal-jarvis`, exactly as `cd` would read it.
 * Without a folder on screen (the start view) the text is passed on as typed.
 *
 * The backend does this again, and with the last word (it knows `..`, `~` and
 * the environment); this one is for showing the person where a path leads
 * before anything is asked.
 */
export function resolveTypedPath(raw: string, base: string | null): string {
  const typed = normalizeTypedPath(raw);
  if (!typed) return "";
  if (isAbsolutePath(typed) || !base) return typed;
  return joinPath(base, typed);
}
