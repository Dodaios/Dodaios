/**
 * Immutable updates written as mutations, with structural sharing.
 *
 * An editor's change reads best as "set this cell", "move that slide": code
 * that mutates. The undo history, though, needs every version of the spec to
 * stay as it was. `produce` gives the change a DRAFT, a proxy that records
 * writes on lazily made shallow copies, and then builds the next spec from
 * them: the parts nobody touched are the very same objects as before. So a
 * history of 200 versions of a large sheet costs 200 copies of the touched
 * paths, not 200 copies of the sheet.
 *
 * Only plain objects and arrays are drafted (a spec is JSON). The change may
 * also return a whole new value instead of mutating; drafts inside that value
 * are resolved too. A draft must not be used after `produce` returns.
 */

const STATE = Symbol("draft-state");

interface DraftState {
  base: Record<PropertyKey, unknown> | unknown[];
  copy: Record<PropertyKey, unknown> | unknown[] | null;
  /** Child drafts by key, made on first read. */
  children: Map<PropertyKey, unknown>;
  /** Keys written by the change: only their values can hold new objects with drafts inside. */
  assigned: Set<PropertyKey>;
  parent: DraftState | null;
  revoked: boolean;
}

function isDraftable(value: unknown): value is Record<PropertyKey, unknown> | unknown[] {
  if (value === null || typeof value !== "object") return false;
  if (Array.isArray(value)) return true;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function stateOf(value: unknown): DraftState | undefined {
  return value !== null && typeof value === "object"
    ? ((value as Record<symbol, unknown>)[STATE] as DraftState | undefined)
    : undefined;
}

export function isDraft(value: unknown): boolean {
  return stateOf(value) !== undefined;
}

function current(state: DraftState): Record<PropertyKey, unknown> | unknown[] {
  return state.copy ?? state.base;
}

function markChanged(state: DraftState): void {
  let walk: DraftState | null = state;
  while (walk && walk.copy === null) {
    walk.copy = Array.isArray(walk.base) ? walk.base.slice() : { ...walk.base };
    walk = walk.parent;
  }
}

function assertLive(state: DraftState): void {
  if (state.revoked) throw new Error("A draft was used after its change finished.");
}

function createDraft(base: Record<PropertyKey, unknown> | unknown[], parent: DraftState | null): unknown {
  const state: DraftState = { base, copy: null, children: new Map(), assigned: new Set(), parent, revoked: false };
  // The proxy target is a stand-in of the same shape, so Array.isArray and
  // the invariants of non-configurable properties (an array's length) hold.
  const target = Array.isArray(base) ? [] : {};
  return new Proxy(target, {
    get(_target, key) {
      if (key === STATE) return state;
      assertLive(state);
      const source = current(state) as Record<PropertyKey, unknown>;
      const value = source[key];
      if (!Object.prototype.hasOwnProperty.call(source, key) || !isDraftable(value)) return value;
      const known = state.children.get(key);
      if (known !== undefined && stateOf(known)?.base === value) return known;
      if (known !== undefined && known === value) return known;
      const child = createDraft(value, state);
      state.children.set(key, child);
      return child;
    },
    set(_target, key, value) {
      assertLive(state);
      const source = current(state) as Record<PropertyKey, unknown>;
      if (source[key] === value && (value !== undefined || key in source)) return true;
      markChanged(state);
      (state.copy as Record<PropertyKey, unknown>)[key] = value;
      state.children.delete(key);
      state.assigned.add(key);
      if (isDraft(value)) state.children.set(key, value);
      return true;
    },
    deleteProperty(_target, key) {
      assertLive(state);
      if (!(key in current(state))) return true;
      markChanged(state);
      delete (state.copy as Record<PropertyKey, unknown>)[key];
      state.children.delete(key);
      return true;
    },
    has(_target, key) {
      if (key === STATE) return true;
      return key in current(state);
    },
    ownKeys() {
      return Reflect.ownKeys(current(state));
    },
    getOwnPropertyDescriptor(_target, key) {
      const source = current(state);
      const descriptor = Reflect.getOwnPropertyDescriptor(source, key);
      if (!descriptor) return undefined;
      // The stand-in target's own `length` is non-configurable; keep it so.
      if (Array.isArray(source) && key === "length") return descriptor;
      return { ...descriptor, configurable: true, writable: true, value: (this.get as (t: object, k: PropertyKey) => unknown)(target, key) };
    },
    defineProperty(_target, key, descriptor) {
      assertLive(state);
      markChanged(state);
      Object.defineProperty(state.copy as object, key, descriptor);
      state.children.delete(key);
      state.assigned.add(key);
      return true;
    },
    getPrototypeOf() {
      return Object.getPrototypeOf(base);
    },
  });
}

/** The value a draft stands for once its change is over. */
function finalize(value: unknown, seen: Set<unknown>): unknown {
  const state = stateOf(value);
  if (state) {
    if (state.copy === null) {
      state.revoked = true;
      return state.base;
    }
    const copy = state.copy as Record<PropertyKey, unknown>;
    state.revoked = true;
    // Children read and then changed: the copy still holds their base.
    for (const [key, child] of state.children) {
      const inner = stateOf(child);
      if (!inner || !Object.prototype.hasOwnProperty.call(copy, key)) continue;
      if (copy[key] === inner.base || copy[key] === child) copy[key] = finalize(child, seen);
    }
    // Values the change put in place: a draft, or a new object around drafts.
    for (const key of state.assigned) {
      if (Object.prototype.hasOwnProperty.call(copy, key)) copy[key] = finalize(copy[key], seen);
    }
    return copy;
  }
  // A new object the change built may hold drafts it read along the way.
  if (isDraftable(value) && !seen.has(value) && !Object.isFrozen(value)) {
    seen.add(value);
    const holder = value as Record<PropertyKey, unknown>;
    for (const key of Object.keys(holder)) {
      const inner = holder[key];
      if (inner !== null && typeof inner === "object") {
        const done = finalize(inner, seen);
        if (done !== inner) holder[key] = done;
      }
    }
  }
  return value;
}

/** Revoke every draft made from `state` (also those never written). */
function revokeAll(state: DraftState): void {
  state.revoked = true;
  for (const child of state.children.values()) {
    const inner = stateOf(child);
    if (inner) revokeAll(inner);
  }
}

/**
 * The next version of `base` after `change`. `change` mutates its draft (and
 * returns nothing), or returns the next value. Returns `base` itself when
 * nothing changed, so a no-op edit is recognisable by identity.
 */
export function produce<S>(base: S, change: (draft: S) => S | void): S {
  if (!isDraftable(base)) {
    const next = change(base);
    return next === undefined ? base : next;
  }
  const draft = createDraft(base, null) as S;
  const rootState = stateOf(draft) as DraftState;
  let returned: S | void;
  try {
    returned = change(draft);
  } catch (error) {
    revokeAll(rootState);
    throw error;
  }
  const seen = new Set<unknown>();
  let result: S;
  if (returned !== undefined && returned !== draft) {
    result = finalize(returned, seen) as S;
  } else {
    result = finalize(draft, seen) as S;
  }
  revokeAll(rootState);
  return result;
}
