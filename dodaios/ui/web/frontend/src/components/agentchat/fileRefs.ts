/**
 * How a thread's answer labels a file or folder it names: the name, a parent
 * folder when two named files share that name, and the line.
 *
 * The label format and the parent-folder rule are adapted from
 * pingdotgg/t3code @ 2c4310eb (packages/shared/src/fileLinks.ts:
 * buildFileLinkParentSuffixByPath, fileLinkLabel), MIT License, Copyright (c)
 * 2026 T3 Tools Inc. — third_party/t3code/LICENSE. Changes: folders are
 * labelled by their own name, and the paths come from inline code spans.
 */
import { fileRefInCode, type FileRef } from "./chatPaths";

/** The comparable form of a path: forward slashes, no trailing slash. */
export function fileRefKey(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

/** `src/app.ts` → `app.ts`; a folder (`docs/`) by its own name. */
export function fileRefName(path: string): string {
  const key = fileRefKey(path);
  return key.slice(key.lastIndexOf("/") + 1) || key;
}

function parentFolders(key: string): string[] {
  return key.split("/").filter(Boolean).slice(0, -1);
}

/**
 * For each named path whose name another named path shares, the shortest
 * run of parent folders (at least two when it has them) that tells them apart.
 */
export function fileRefSuffixes(paths: Iterable<string>): Map<string, string> {
  const byName = new Map<string, Set<string>>();
  for (const path of paths) {
    const key = fileRefKey(path);
    const name = fileRefName(key);
    if (!name) continue;
    const group = byName.get(name) ?? new Set<string>();
    group.add(key);
    byName.set(name, group);
  }
  const suffixes = new Map<string, string>();
  for (const named of byName.values()) {
    // `core/config.py` and `dodaios/core/config.py` are one file named twice.
    const group = [...named].filter((key) => ![...named].some((other) => other.endsWith(`/${key}`)));
    if (group.length < 2) continue;
    const parents = new Map(group.map((key) => [key, parentFolders(key)]));
    const counts = new Map<string, number>();
    for (const segments of parents.values()) {
      for (let depth = 1; depth <= segments.length; depth += 1) {
        const suffix = segments.slice(-depth).join("/");
        counts.set(suffix, (counts.get(suffix) ?? 0) + 1);
      }
    }
    for (const [key, segments] of parents) {
      if (segments.length === 0) continue;
      let depth = segments.length;
      for (let candidate = 1; candidate <= segments.length; candidate += 1) {
        if (counts.get(segments.slice(-candidate).join("/")) === 1) { depth = candidate; break; }
      }
      suffixes.set(key, segments.slice(-Math.min(segments.length, Math.max(depth, 2))).join("/"));
    }
    // A shorter naming of one of them reads like it, when it can only be that one.
    for (const key of named) {
      if (suffixes.has(key)) continue;
      const longer = group.filter((other) => other.endsWith(`/${key}`));
      const suffix = longer.length === 1 ? suffixes.get(longer[0]) : undefined;
      if (suffix) suffixes.set(key, suffix);
    }
  }
  return suffixes;
}

/** `app.ts · src/lib · L42`, `app.ts · L42–64`, `app.ts · L42:C7`, `docs`. */
export function fileRefLabel(ref: FileRef, suffix?: string): string {
  const line = ref.line
    ? `L${ref.line}${ref.endLine ? `–${ref.endLine}` : ref.column ? `:C${ref.column}` : ""}`
    : "";
  // macOS stores many names decomposed; compose them for display only.
  return [fileRefName(ref.path), suffix, line].filter(Boolean).join(" · ").normalize("NFC");
}

/** Fenced blocks hold code, not references. */
const FENCED_BLOCK = /^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}\1[^\S\n]*$|(?![\s\S]))/gm;
const INLINE_CODE = /(`+)([^`\n]|[^`\n][^\n]*?[^`\n])\1(?!`)/g;

/** The paths a Markdown text names in inline code, for telling same-named files apart. */
export function fileRefsInMarkdown(markdown: string): string[] {
  const prose = markdown.includes("```") || markdown.includes("~~~") ? markdown.replace(FENCED_BLOCK, "") : markdown;
  const paths: string[] = [];
  for (const match of prose.matchAll(INLINE_CODE)) {
    const ref = fileRefInCode(match[2]);
    if (ref) paths.push(ref.path);
  }
  return paths;
}
