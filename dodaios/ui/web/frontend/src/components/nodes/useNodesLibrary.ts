/**
 * The Nodes library's state, in one hook.
 *
 * The section view calls it once and hands the result to `NodesLibrary`, so
 * the library keeps its tab, its search and its place in the list while a
 * node is open on the stage (the stage walks `cards` for previous / next).
 *
 * Tab, sort, view and type filter are choices the reader made once and finds
 * again after a restart (`jarvis.nodes.*` in this profile's storage); the
 * search text lives only as long as the hook does.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { useArtifactFavorites } from "@/hooks/useArtifactFavorites";
import {
  LIBRARY_SORTS,
  LIBRARY_TABS,
  LIBRARY_VIEWS,
  TYPE_FILTERS,
  countByTab,
  filterByType,
  newPendingNode,
  nextPendingExpiry,
  pendingCard,
  resolvePending,
  searchCards,
  visibleCards,
  type LibrarySort,
  type LibraryTab,
  type LibraryView,
  type PendingNode,
  type TypeFilter,
} from "./libraryModel";
import type { NodeCard, NodeType, NodesResponse } from "./nodeModel";
import { useNodes } from "./useNodes";

const TAB_KEY = "jarvis.nodes.tab";
const SORT_KEY = "jarvis.nodes.sort";
const VIEW_KEY = "jarvis.nodes.view";
const TYPE_KEY = "jarvis.nodes.type";

const NO_CARDS: NodeCard[] = [];

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = window.localStorage.getItem(key);
    if (stored !== null && (allowed as readonly string[]).includes(stored)) return stored as T;
  } catch {
    // Storage can be unavailable (private window, blocked site data): the default then.
  }
  return fallback;
}

/** A choice the reader made once and expects to find again. */
function useStoredChoice<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => readStored(key, allowed, fallback));
  const choose = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // A remembered tab or order is a convenience, never a requirement.
      }
    },
    [key],
  );
  return [value, choose];
}

export interface NodesLibraryState {
  /** The `/api/nodes` query itself (loading, error, refetch). */
  nodes: UseQueryResult<NodesResponse>;
  /** Every card the server listed, untouched. */
  allCards: NodeCard[];
  /** No answer yet, and nothing to show meanwhile. */
  loading: boolean;
  /** The list could not be read, and there is no earlier answer to show. */
  failed: boolean;

  tab: LibraryTab;
  setTab: (next: LibraryTab) => void;
  search: string;
  setSearch: (next: string) => void;
  typeFilter: TypeFilter;
  setTypeFilter: (next: TypeFilter) => void;
  sort: LibrarySort;
  setSort: (next: LibrarySort) => void;
  view: LibraryView;
  setView: (next: LibraryView) => void;

  favorites: ReadonlySet<string>;
  toggleFavorite: (key: string) => void;

  /**
   * What the current tab + search + type filter + order show: real cards
   * only, in screen order. Previous / next on the stage walk this list.
   */
  cards: NodeCard[];
  /**
   * Placeholders of nodes the assistant was asked for and has not delivered
   * yet, as the current view shows them (they lead the "All" tab).
   */
  pending: NodeCard[];
  /** Cards per tab, before search and type filter. */
  counts: Record<LibraryTab, number>;

  /** Register a placeholder for a node that was just requested. */
  addPending: (type: NodeType, request: string) => void;
  /** Back to the whole library: the "All" tab, no search, no type filter. */
  showAll: () => void;
}

export function useNodesLibrary(): NodesLibraryState {
  const [waiting, setWaiting] = useState<readonly PendingNode[]>([]);
  const nodes = useNodes({ pending: waiting.length > 0 });
  const allCards = nodes.data?.nodes ?? NO_CARDS;
  const loaded = nodes.data !== undefined;

  const [tab, setTab] = useStoredChoice<LibraryTab>(TAB_KEY, LIBRARY_TABS, "all");
  const [sort, setSort] = useStoredChoice<LibrarySort>(SORT_KEY, LIBRARY_SORTS, "changed");
  const [view, setView] = useStoredChoice<LibraryView>(VIEW_KEY, LIBRARY_VIEWS, "grid");
  const [typeFilter, setTypeFilter] = useStoredChoice<TypeFilter>(TYPE_KEY, TYPE_FILTERS, "all");
  const [search, setSearch] = useState("");

  const { favorites, toggle: toggleFavorite } = useArtifactFavorites();

  const cards = useMemo(
    () => visibleCards(allCards, { tab, favorites, query: search, type: typeFilter, sort }),
    [allCards, tab, favorites, search, typeFilter, sort],
  );
  const counts = useMemo(() => countByTab(allCards, favorites), [allCards, favorites]);

  /* --- placeholders ------------------------------------------------------- */

  const cardsRef = useRef(allCards);
  cardsRef.current = allCards;
  const serial = useRef(0);

  // A fresh list may hold the node a placeholder waits for.
  useEffect(() => {
    if (!loaded) return;
    setWaiting((current) => resolvePending(current, allCards, Date.now()));
  }, [allCards, loaded]);

  // And a placeholder nobody answered steps aside by itself.
  useEffect(() => {
    const delay = nextPendingExpiry(waiting, Date.now());
    if (delay === null) return;
    const timer = window.setTimeout(() => {
      setWaiting((current) => resolvePending(current, cardsRef.current, Date.now()));
    }, delay + 50);
    return () => window.clearTimeout(timer);
  }, [waiting]);

  const addPending = useCallback((type: NodeType, request: string) => {
    serial.current += 1;
    const item = newPendingNode(type, request, cardsRef.current, Date.now(), serial.current);
    setWaiting((current) => [...current, item]);
  }, []);

  const pending = useMemo(() => {
    if (tab !== "all" || waiting.length === 0) return NO_CARDS;
    // Newest request first: it is the one the reader just made.
    const placeholders = [...waiting].sort((a, b) => b.createdAt - a.createdAt).map(pendingCard);
    return searchCards(filterByType(placeholders, typeFilter), search);
  }, [waiting, tab, typeFilter, search]);

  const showAll = useCallback(() => {
    setTab("all");
    setSearch("");
    setTypeFilter("all");
  }, [setTab, setTypeFilter]);

  return {
    nodes,
    allCards,
    loading: nodes.isLoading && !loaded,
    failed: nodes.isError && !loaded,
    tab,
    setTab,
    search,
    setSearch,
    typeFilter,
    setTypeFilter,
    sort,
    setSort,
    view,
    setView,
    favorites,
    toggleFavorite,
    cards,
    pending,
    counts,
    addPending,
    showAll,
  };
}
