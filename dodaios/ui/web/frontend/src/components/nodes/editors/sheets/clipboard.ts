/**
 * Cells on the clipboard as tab-separated text, the format every spreadsheet
 * app reads and writes: one line per row, a tab between cells, and a cell
 * that holds a tab, a line break or a quote wrapped in double quotes (a quote
 * inside doubled). Reading accepts what those apps write: \r\n or \n line
 * ends, a trailing line end, quoted cells over several lines.
 */
import { isNumber, rawNumber, textOf, type CellValue } from "./model";

/** The rows and cells of a tab-separated text. */
export function parseTsv(text: string): string[][] {
  const source = text.replace(/\r\n?/g, "\n");
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let at = 0;
  let quoted = false;
  let started = true; // at the start of a cell: a quote there opens a quoted cell
  while (at < source.length) {
    const char = source[at];
    if (quoted) {
      if (char === '"') {
        if (source[at + 1] === '"') {
          cell += '"';
          at += 2;
          continue;
        }
        quoted = false;
        at += 1;
        continue;
      }
      cell += char;
      at += 1;
      continue;
    }
    if (char === '"' && started) {
      quoted = true;
      started = false;
      at += 1;
      continue;
    }
    started = false;
    if (char === "\t") {
      row.push(cell);
      cell = "";
      started = true;
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      started = true;
    } else {
      cell += char;
    }
    at += 1;
  }
  if (cell !== "" || row.length || quoted) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function quote(text: string): string {
  return /[\t\n\r"]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Rows of texts as tab-separated text, one line per row. */
export function toTsv(rows: readonly (readonly string[])[]): string {
  return rows.map((row) => row.map(quote).join("\t")).join("\n");
}

/**
 * A cell as clipboard text another app reads as the same value: a number
 * plain (no grouping, no currency sign, the locale's decimal mark) so it
 * arrives as a number, a check as TRUE/FALSE, a link as its address.
 */
export function clipboardText(value: CellValue | undefined, locale?: string): string {
  if (value === undefined || value === null) return "";
  if (isNumber(value)) return rawNumber(value, locale);
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "object" && value.href) return value.text && value.text !== value.href ? value.text : value.href;
  return textOf(value);
}
