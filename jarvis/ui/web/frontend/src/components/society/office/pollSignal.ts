/**
 * One abort signal per scheduled read of the office's pollers (desk chats,
 * team rounds). A read ends when its answer comes, when the poller is cleaned
 * up (`parent` aborts), or after `ms`: a request hanging on a half-open
 * socket must never hold the next tick back.
 */

/** How long one read may take before it is given up. */
export const READ_TIMEOUT_MS = 8000;

export interface ReadSignal {
  signal: AbortSignal;
  /** Call when the read has settled: drops the timer and the link to the parent. */
  done: () => void;
}

export function readSignal(parent: AbortSignal, ms = READ_TIMEOUT_MS): ReadSignal {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (parent.aborted) abort();
  else parent.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, ms);
  return {
    signal: controller.signal,
    done: () => { clearTimeout(timer); parent.removeEventListener("abort", abort); },
  };
}

/**
 * Run `read` under a signal of its own. Resolves to its value, or rejects
 * when it fails, is aborted or takes longer than `ms`; the timeout rejects
 * even when the underlying request ignores the signal.
 */
export async function withReadSignal<T>(parent: AbortSignal, read: (signal: AbortSignal) => Promise<T>, ms = READ_TIMEOUT_MS): Promise<T> {
  const { signal, done } = readSignal(parent, ms);
  try {
    return await Promise.race([
      read(signal),
      new Promise<never>((_, reject) => {
        const fail = () => reject(new Error(parent.aborted ? "read cancelled" : "read timed out"));
        if (signal.aborted) fail();
        else signal.addEventListener("abort", fail, { once: true });
      }),
    ]);
  } finally {
    done();
  }
}
