import type { DiffFile, DiffLine as EditLine } from "@/components/agentchat/toolDiff";
import type { DiffHunk, DiffLine } from "@/components/agentic/sidePanel/explorer/explorerApi";

/** The marker a hunk shows when the file no longer holds the edited lines, so no line numbers are known. */
export const UNPLACED_HUNK_HEADER = "⋯";

function fileLines(text: string): string[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  // A file ending in a newline has no empty last line.
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** Where `needle` starts in `lines`, looking from `from` first and then from the top; -1 when absent. */
function locate(lines: string[], needle: string[], from: number): number {
  const matchesAt = (start: number) => needle.every((text, i) => lines[start + i] === text);
  for (let start = from; start + needle.length <= lines.length; start++) if (matchesAt(start)) return start;
  for (let start = 0; start < Math.min(from, lines.length - needle.length + 1); start++) if (matchesAt(start)) return start;
  return -1;
}

/**
 * One edit, drawn the way the Changes view draws a file: hunks with both line
 * numbers in the gutter.
 *
 * An edit names only the lines it touched, not where they sit. Its "after"
 * side (unchanged plus added lines) is looked up in the file as it is now; where
 * it is found, the lines get their numbers. Where the file has moved on since
 * the edit, the hunk is drawn without numbers.
 */
export function editHunks(file: DiffFile, text: string | null): DiffHunk[] {
  const segments: EditLine[][] = [[]];
  for (const line of file.lines) {
    if (line.kind === "gap") segments.push([]);
    else segments[segments.length - 1].push(line);
  }
  const lines = text === null ? null : fileLines(text);
  let from = 0;
  // How far the old numbering runs ahead of the new one, from the hunks above.
  let shift = 0;
  const hunks: DiffHunk[] = [];
  for (const segment of segments) {
    if (!segment.length) continue;
    const after = segment.filter((line) => line.kind !== "del").map((line) => line.text);
    const before = segment.length - segment.filter((line) => line.kind === "add").length;
    const at = lines && after.length ? locate(lines, after, from) : -1;
    let oldNo = at < 0 ? null : at + 1 + shift;
    let newNo = at < 0 ? null : at + 1;
    const out: DiffLine[] = segment.map((line) => {
      const kind = line.kind as DiffLine["kind"];
      const row: DiffLine = {
        kind,
        text: line.text,
        old_no: kind === "add" || oldNo === null ? null : oldNo++,
        new_no: kind === "del" || newNo === null ? null : newNo++,
      };
      return row;
    });
    hunks.push({
      header: at < 0 ? UNPLACED_HUNK_HEADER : `@@ -${at + 1 + shift},${before} +${at + 1},${after.length} @@`,
      lines: out,
    });
    if (at >= 0) from = at + after.length;
    shift += before - after.length;
  }
  return hunks;
}
