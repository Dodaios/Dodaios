/**
 * What the first conversation reads and writes, kept apart from its look.
 *
 * Answers land where the rest of the app already reads them:
 * - the name in the Profile (`PATCH /api/profile/field`, the greeting and
 *   the sidebar use it) AND as a pinned profile memory in the personal
 *   memory vault, so the assistant knows it in every conversation;
 * - what the person wants help with as one pinned preference memory;
 * - accounts through the Plugins sign-in (see `accounts.ts`).
 *
 * Every write is best-effort: a backend that is still booting must never
 * trap the person in the introduction. Memory texts are English on purpose
 * — they are read by the model, not shown as interface text.
 */

const STATE_URL = "/api/onboarding/state";

let dueCache: Promise<boolean> | null = null;

/** Whether the introduction should show. Read once per page load. */
export function firstConversationDue(): Promise<boolean> {
  dueCache ??= (async () => {
    try {
      const res = await fetch(STATE_URL, { cache: "no-store" });
      if (!res.ok) return false;
      const body = (await res.json()) as { completed?: boolean; first_conversation_due?: boolean };
      return body.completed === true && body.first_conversation_due === true;
    } catch {
      // Fail closed: an unreadable state never shows an introduction twice.
      return false;
    }
  })();
  return dueCache;
}

/** Ends the introduction for this page load as well as on disk. */
function markFinishedLocally(): void {
  dueCache = Promise.resolve(false);
}

/** Test seam: forget the cached answer. */
export function _resetFirstConversationCache(): void {
  dueCache = null;
}

async function send(url: string, method: string, body: unknown): Promise<boolean> {
  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function remember(text: string, kind: string): Promise<boolean> {
  return send("/api/memory/vault/items", "POST", { text, kind, pinned: true });
}

/** Cleans what was typed into a name: one line, no surrounding quotes, at most 60 characters. */
export function cleanName(raw: string): string {
  return raw
    .replace(/[\r\n\t]+/g, " ")
    .replace(/^["'\s]+|["'\s.!]+$/g, "")
    .replace(/\s{2,}/g, " ")
    .slice(0, 60)
    .trim();
}

/** Saves the person's name to the Profile and the memory. True if either took. */
export async function saveUserName(raw: string): Promise<boolean> {
  const name = cleanName(raw);
  if (!name) return false;
  const [profile, memory] = await Promise.all([
    send("/api/profile/field", "PATCH", { cluster: "identity", field: "name", operation: "set", value: name }),
    remember(`The user's name is ${name}.`, "profile"),
  ]);
  return profile || memory;
}

/** Saves what the person wants help with as one preference memory. */
export async function saveHelpTopics(topics: readonly string[], note: string): Promise<boolean> {
  const parts = [...topics];
  const extra = note.replace(/\s+/g, " ").trim().slice(0, 300);
  if (extra) parts.push(extra);
  if (parts.length === 0) return false;
  return remember(`The user wants help with: ${parts.join(", ")}.`, "preference");
}

/** Records the introduction as answered or skipped. */
export async function finishFirstConversation(outcome: "done" | "skipped"): Promise<void> {
  markFinishedLocally();
  await send("/api/onboarding/first-conversation", "POST", { outcome });
}
