/** One file's receipt in a transcript — enough to say what was sent, no more. */
export interface UserAttachment {
  name: string;
  kind: string;
  /** `vision` / `extraction` / `none` — whether the model could read it. */
  describedBy: string;
  /**
   * Where the file itself can be fetched from, same-origin. The timeline draws
   * the picture when it has this and a chip when it does not.
   */
  url?: string;
  sizeBytes?: number;
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/** The attachment receipts off one message, tolerant of any shape. */
export function userAttachments(raw: unknown): UserAttachment[] {
  if (!Array.isArray(raw)) return [];
  const out: UserAttachment[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const row = entry as Record<string, unknown>;
    const name = str(row.name);
    if (!name) continue;
    const url = str(row.url);
    out.push({
      name,
      kind: str(row.kind),
      describedBy: str(row.described_by),
      ...(typeof row.size_bytes === "number" && Number.isFinite(row.size_bytes) && row.size_bytes >= 0
        ? { sizeBytes: row.size_bytes } : {}),
      ...(url ? { url } : {}),
    });
  }
  return out;
}
