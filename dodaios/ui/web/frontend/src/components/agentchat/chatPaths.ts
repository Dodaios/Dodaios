import { createContext } from "react";

/**
 * Opens a file or folder an answer names, beside the conversation.
 *
 * A thread provides it, so a path the agent wrote opens in the side panel.
 * Where nothing provides it (the Dodaios chat), paths stay plain text and
 * linked paths keep opening on the computer.
 */
export const ChatPathOpener = createContext<((path: string) => void) | null>(null);

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

/** `:42`, `:42:7`, `#L42`, `(42,7)`: where in the file, not part of its name. */
const LOCATION_SUFFIX = /(?:#L[1-9]\d*(?:-L?[1-9]\d*)?|:[1-9]\d*(?::[1-9]\d*)?|\([1-9]\d*(?:,[1-9]\d*)?\))$/;

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
