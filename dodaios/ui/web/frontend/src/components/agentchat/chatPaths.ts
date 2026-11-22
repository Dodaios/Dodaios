import { createContext, type ComponentType } from "react";

/**
 * Opens a file or folder an answer names, beside the conversation, at `line`
 * when the answer named one (`src/app.ts:42`).
 *
 * A thread provides it, so a path the agent wrote opens in the side panel.
 * Where nothing provides it (the Dodaios chat), paths stay plain text and
 * linked paths keep opening on the computer.
 */
export const ChatPathOpener = createContext<((path: string, line?: number) => void) | null>(null);

/**
 * The coloured file-type glyph a thread draws in front of a file an answer
 * names. The thread hands it in, so the glyph sheet loads with the IDE and not
 * with every chat that shows Markdown; without it a plain file mark stands in.
 */
export const ChatFileIcon = createContext<ComponentType<{ path: string; className?: string }> | null>(null);

/** Where in a file a reference points: a line, a column, the last line of a range. */
export interface FileLocation {
  line?: number;
  column?: number;
  endLine?: number;
}

/** A file or folder an answer names, and where in it. */
export interface FileRef extends FileLocation {
  path: string;
}

/** Extensions a bare name (`todo.md`) must end in to read as a file, not as code (`item.text`). */
const FILE_EXTENSIONS = new Set([
  // text and data
  "md", "markdown", "mdx", "txt", "log", "csv", "tsv", "json", "jsonc", "jsonl", "ndjson", "yaml", "yml",
  "toml", "ini", "cfg", "conf", "env", "xml", "html", "htm", "css", "scss", "sass", "less", "svg",
  "lock", "rst", "tex", "sql", "db", "sqlite", "proto", "graphql", "gql", "srt", "vtt",
  // code
  "py", "pyi", "ipynb", "ts", "tsx", "mts", "cts", "js", "jsx", "mjs", "cjs", "vue", "svelte", "astro",
  "rs", "go", "java", "kt", "kts", "swift", "c", "h", "cpp", "cc", "cxx", "hpp", "cs", "rb", "php",
  "lua", "dart", "scala", "r", "pl", "ex", "exs", "erl", "hs", "zig", "nim", "sh", "bash", "zsh",
  "fish", "ps1", "psm1", "psd1", "bat", "cmd", "gradle", "spec", "patch", "diff",
  // media and documents
  "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif", "heic", "tif", "tiff", "pdf",
  "mp3", "wav", "ogg", "oga", "m4a", "aac", "flac", "opus", "mp4", "m4v", "webm", "mov", "mkv", "avi",
  "docx", "doc", "odt", "rtf", "xlsx", "xls", "ods", "pptx", "ppt", "odp", "epub",
  // archives and programs
  "zip", "gz", "tgz", "tar", "7z", "rar", "exe", "msi", "dmg", "pkg", "deb", "rpm", "whl", "apk",
]);

/** Dot files a bare name may be: `.env`, `.gitignore`. */
const DOT_FILES = /^\.(?:env(?:\.[\w-]+)?|gitignore|gitattributes|gitmodules|editorconfig|npmrc|nvmrc|prettierrc|eslintrc(?:\.\w+)?|dockerignore|bashrc|zshrc|profile)$/i;

/** First folders of an absolute Unix path that are real places, not routes (`/api/x`). */
const UNIX_ROOTS = new Set([
  "home", "users", "tmp", "var", "etc", "opt", "usr", "mnt", "media", "srv", "root", "private",
  "volumes", "library", "applications", "workspace", "workspaces", "data", "app", "code", "src",
]);

/**
 * `:42`, `:42:7`, `:42-64`, `#L42`, `#L42C7`, `#L42-L64`, `(42,7)`: where in
 * the file, not part of its name. Groups: line, column, last line, for each form.
 */
const LOCATION_SUFFIX = /(?:#L([1-9]\d*)(?:C([1-9]\d*)|-L?([1-9]\d*))?|:([1-9]\d*)(?::([1-9]\d*)|-([1-9]\d*))?|\(([1-9]\d*)(?:,([1-9]\d*))?\))$/;

/** A path and the place in it its end names (`src/app.ts:42` → `src/app.ts`, line 42). */
export function splitLocation(raw: string): FileRef {
  const text = raw.trim();
  const match = LOCATION_SUFFIX.exec(text);
  if (!match) return { path: text };
  const line = Number(match[1] ?? match[4] ?? match[7]);
  const column = Number(match[2] ?? match[5] ?? match[8] ?? 0);
  const endLine = Number(match[3] ?? match[6] ?? 0);
  return {
    path: text.slice(0, match.index),
    line,
    ...(column ? { column } : {}),
    ...(endLine > line ? { endLine } : {}),
  };
}

/** The file or folder an inline code span names, with the line it points at; null for code. */
export function fileRefInCode(raw: string): FileRef | null {
  const path = pathInCode(raw);
  if (!path) return null;
  const { path: _written, ...location } = splitLocation(raw);
  return { path, ...location };
}

const NAME_PART = /^[\w.@+~-]+$/;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/**
 * The file or folder an inline code span names (`todo.md`, `src/app.ts:12`,
 * `C:\Users\me\Downloads\clip.mp4`, `docs/`), without its line, or null when
 * the span is code, a command or a branch name.
 */
export function pathInCode(raw: string): string | null {
  const text = raw.trim();
  if (!text || text.length > 400 || /[\u0000-\u001f<>"|*?]/.test(text)) return null;
  const path = text.replace(LOCATION_SUFFIX, "");
  if (!path) return null;
  // Windows, absolute: always a place on this computer, spaces and all.
  if (/^[A-Za-z]:[\\/]./.test(path)) return path;
  if (/\s/.test(path) || /^[a-z][a-z0-9+.-]*:/i.test(path)) return null;
  const parts = path.replace(/\\/g, "/").split("/");
  const name = parts[parts.length - 1];
  const folder = name === "";
  const named = parts.filter((part, index) => part !== "" || index === parts.length - 1);
  if (named.slice(0, folder ? -1 : undefined).some((part) => part !== "." && part !== ".." && part !== "~" && !NAME_PART.test(part))) return null;
  const extension = extensionOf(name);
  // The home folder: `~/Downloads/notes.md`, `~/projects/`.
  if (path.startsWith("~/") || path.startsWith("~\\")) return parts.length > 1 && (parts[1] ?? "") !== "" ? path : null;
  if (path.startsWith("/")) {
    if (path.startsWith("//")) return null;
    const first = (parts[1] ?? "").toLowerCase();
    // `/api/settings` is a route and `/compact` a command; a real place starts at a real root.
    return parts.length > 2 && (UNIX_ROOTS.has(first) || FILE_EXTENSIONS.has(extension)) ? path : null;
  }
  if (path.startsWith("@")) return null; // an import alias (`@/lib/utils`) or a package
  if (parts.length > 1) {
    // `src/components/` is a folder; `src/app.ts` a file; `fix/bar-edges` a branch.
    if (folder) return parts.slice(0, -1).every((part) => part !== "") ? path : null;
    return /[a-z]/i.test(extension) && extension.length <= 10 ? path : null;
  }
  return FILE_EXTENSIONS.has(extension) || DOT_FILES.test(name) ? path : null;
}
