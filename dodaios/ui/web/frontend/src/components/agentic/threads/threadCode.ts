import { fill, translate } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import { useEventStore } from "@/store/events";

/**
 * A thread's code as the person reads and gives it to Dodaios: `#3f9a2c`.
 * The server derives it from the session id; "" while a row carries none.
 */
export function shownThreadCode(session: { code?: string } | null | undefined): string {
  return session?.code ? `#${session.code}` : "";
}

/** Copy a thread's code and say what it is for. */
export async function copyThreadCode(code: string): Promise<boolean> {
  if (!code) return false;
  const copied = await robustCopy(code);
  useEventStore.getState().pushToast(
    copied ? "success" : "error",
    fill(translate(copied ? "ide_threads.code.copied" : "ide_threads.code.copy_failed"), { code }),
  );
  return copied;
}
