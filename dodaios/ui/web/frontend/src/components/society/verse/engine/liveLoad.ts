/**
 * A load whose outcome only counts while its owner still wants it. A deck
 * that was switched away from (or a renderer rebuilt after a lost context)
 * aborts its loads; that abort, or a result arriving after the switch, must
 * never be reported as the new deck failing or being ready.
 */

export function isAbortError(error: unknown): boolean {
  return (error instanceof DOMException || error instanceof Error) && error.name === "AbortError";
}

/** Follow `promise`; returns the function that stops caring about it. */
export function liveLoad<T>(promise: Promise<T>, onDone: (value: T) => void, onError: (error: Error) => void): () => void {
  let live = true;
  promise.then(
    (value) => { if (live) onDone(value); },
    (error: unknown) => {
      if (!live || isAbortError(error)) return;
      onError(error instanceof Error ? error : new Error(String(error)));
    },
  );
  return () => { live = false; };
}
