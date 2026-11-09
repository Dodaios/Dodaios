/**
 * Keep the app alive when something else rewrote the page under React.
 *
 * A page translator (Chrome's built-in one, a translation extension) replaces
 * text nodes with its own elements. React still holds the old nodes, so its
 * next update calls `insertBefore` or `removeChild` with a node that is no
 * longer where React left it, and the browser throws: "Failed to execute
 * 'insertBefore' on 'Node'". The whole view unmounts on that one error. A
 * person whose voice call failed and who then opened the app in a browser saw
 * exactly this instead of the reason for the failure (issue #828).
 *
 * index.html asks translators to leave the page alone, since the app carries
 * its own languages. This guard is the second line: a browser or extension
 * that translates anyway costs one stale label, not the whole page.
 */

let installed = false;

export function installDomMutationGuard(): void {
  if (installed || typeof Node !== "function" || !Node.prototype) return;
  installed = true;

  const originalRemoveChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function removeChild<T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) {
      // Already moved or replaced by someone else: there is nothing of ours
      // left to remove here.
      console.warn("A page node was moved outside the app; skipped its removal.");
      return child;
    }
    return originalRemoveChild.call(this, child) as T;
  };

  const originalInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function insertBefore<T extends Node>(
    this: Node,
    node: T,
    reference: Node | null,
  ): T {
    if (reference && reference.parentNode !== this) {
      // The node React wanted to insert before is gone from this parent.
      // Appending keeps the new content on the page.
      console.warn("A page node was moved outside the app; appended new content instead.");
      return originalInsertBefore.call(this, node, null) as T;
    }
    return originalInsertBefore.call(this, node, reference) as T;
  };
}
