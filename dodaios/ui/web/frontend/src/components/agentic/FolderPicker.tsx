/**
 * Which folder the agents work in.
 *
 * ## One field, one list
 *
 * The picker is a single field over a single list, and the field reads what
 * is typed the way a terminal would:
 *
 * * a **name** (`shop`) narrows the folder on screen and, from two letters on,
 *   also finds folders of that name elsewhere on the machine;
 * * a **path** (`Desktop\shop`, `..`, `~/code`, `C:\work`) is a place. A
 *   relative one is read against the folder on screen, exactly as `cd` reads
 *   it, and the leading `cd` itself may be typed too;
 * * **Enter** opens the highlighted folder, or the typed path when nothing is
 *   highlighted; **Tab** completes the name and leaves the next part ready to
 *   type; **Backspace** in the empty field goes up one folder; the arrow keys
 *   move through the list. Enter in the empty field confirms the choice.
 *
 * The list under the field always shows the folders the typed text could
 * mean, so a half-typed path completes on screen instead of in a dropdown.
 *
 * It replaces a layout that had grown a search field, a second path field
 * behind a pencil button, a suggestions dropdown and five icon buttons. Each
 * was added for a real report; together they made the one thing people came
 * to do (name a folder) the hardest to find.
 *
 * ## The folder on screen is the folder chosen
 *
 * Opening a folder, clicking a crumb and going up all choose what is then on
 * screen, so "what will be used" never differs from "where I am". The start
 * view is the one exception: it is a list of places, not a folder, and
 * showing it keeps the previous choice.
 *
 * ## The other ways in
 *
 * * **Recent folders** on the start view, with their previous layout.
 * * **The system folder window** (Explorer, Finder, the desktop's own dialog),
 *   offered only where the backend confirms this machine can show it. The
 *   in-page list is the floor, not the fallback: the system window opens on
 *   the machine the BACKEND runs on, so it is useless over a network.
 * * **Drag and drop** anywhere on the panel. Inside the desktop shell the host
 *   reports the real path (`waitForNativeDrop`); in a browser only the NAME is
 *   known, and the backend searches for it (see `extractDropPayload`).
 * * **A new folder**, made inside the folder on screen; a typed name that does
 *   not exist yet is offered for creation rather than only refused.
 *
 * ## Clicking fast
 *
 * Every listing carries a ticket and only the newest one is shown. Without it
 * two quick clicks could show the first folder under the second one's name,
 * because the slower answer arrived last. The address bar moves on the click
 * itself, and the list is dimmed until its folder has arrived.
 *
 * ## Escape
 *
 * Every host is a dialog that closes on Escape. The field uses Escape to clear
 * what was typed and the new-folder field to back out of itself, so both carry
 * `data-escape-local` while they have something to give up; a host checks for
 * it before closing (AgenticIdeView's key handler, `onEscapeKeyDown` on the
 * Radix dialogs).
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronRight,
  CornerLeftUp,
  Eye,
  EyeOff,
  Folder,
  FolderGit2,
  FolderOpen,
  FolderPlus,
  HardDrive,
  History,
  Home,
  Loader2,
  Monitor,
  Search,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { waitForNativeDrop } from "@/lib/nativeDrop";
import { useDragSessionEnd } from "./dragSessionEnd";
import { Button, FOCUS_RING, Field, IconButton, SectionLabel } from "./controls";
import {
  createFolder,
  fetchFolders,
  fetchNativePickerSupport,
  fetchRecents,
  forgetRecent,
  openNativePicker,
  resolveDroppedFolder,
  searchFolders,
  type FolderItem,
  type FoldersResponse,
  type NativePickerSupport,
  type RecentWorkspace,
} from "@/lib/agenticIdeApi";
import {
  extractDropPayload,
  foldCrumbs,
  isAbsolutePath,
  isFolderName,
  lastUsedLabel,
  leafName,
  looksLikePath,
  matchByName,
  normalizeTypedPath,
  parentPath,
  pathCrumbs,
  sameName,
  samePath,
  separatorOf,
  typedParts,
} from "./folderPaths";

// The pure path rules live in `folderPaths`; they are re-exported because the
// picker is where callers and tests have always found them.
export {
  extractDropPayload,
  isAbsolutePath,
  joinPath,
  lastUsedLabel,
  leafName,
  looksLikePath,
  normalizeTypedPath,
  pathCrumbs,
  resolveTypedPath,
  separatorOf,
  splitTypedPath,
} from "./folderPaths";

interface FolderPickerProps {
  selected: string | null;
  onSelect: (path: string) => void;
  /** A recent workspace was picked — its previous layout can be replayed. */
  onSelectRecent?: (recent: RecentWorkspace) => void;
  /**
   * Enter in the empty field with a folder chosen: the host's own "use this
   * folder". Without it Enter in the empty field does nothing.
   */
  onConfirm?: () => void;
  /**
   * Whether the picker states the chosen folder under its list. A host that
   * already reports the choice beside its own action turns it off so the
   * folder is not named twice.
   */
  showSelection?: boolean;
  className?: string;
}

/** A bare word shorter than this only narrows the list already on screen. */
const SEARCH_MIN = 2;
const SEARCH_DEBOUNCE_MS = 250;
/** How many folders from elsewhere on the machine are offered at once. */
const HITS_SHOWN = 12;

interface Listing {
  /** The folder these entries are in; null is the start view's places. */
  path: string | null;
  entries: FolderItem[];
  error: string | null;
  truncated: boolean;
}

/** The folder part of the typed text, listed so the name part can narrow it. */
interface Preview {
  key: string;
  path: string | null;
  entries: FolderItem[];
  error: string | null;
}

type Row =
  | { kind: "recent"; key: string; path: string; name: string; recent: RecentWorkspace }
  | { kind: "folder"; key: string; path: string; name: string; item: FolderItem; detail?: string }
  | { kind: "create"; key: string; parent: string | null; name: string };

interface Section {
  label: string | null;
  rows: Row[];
}

const EMPTY_LISTING: Listing = { path: null, entries: [], error: null, truncated: false };
const NO_ROWS: Row[] = [];

export function FolderPicker({
  selected,
  onSelect,
  onSelectRecent,
  onConfirm,
  showSelection = true,
  className,
}: FolderPickerProps) {
  const t = useT();
  // The folder the address bar shows. It moves on the click; `listing` follows
  // when the answer arrives.
  const [here, setHere] = useState<string | null>(null);
  const [listing, setListing] = useState<Listing>(EMPTY_LISTING);
  const [loading, setLoading] = useState(true);
  const [deviceName, setDeviceName] = useState("");
  const [home, setHome] = useState<string | null>(null);
  const [recents, setRecents] = useState<RecentWorkspace[]>([]);

  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [hits, setHits] = useState<{ word: string; entries: FolderItem[] } | null>(null);
  const [searching, setSearching] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // The keyboard highlight, remembered for one typed text only: a new letter
  // changes the list, and the old position would point at a different folder.
  const [cursor, setCursor] = useState<{ text: string; index: number } | null>(null);

  // Dot-folders and the folders the system hides are noise in a project list
  // and the one thing someone opening `.claude` needs — so they are a switch,
  // off by default, and a typed name that starts with a dot turns them on for
  // that lookup by itself.
  const [showHidden, setShowHidden] = useState(false);

  const [naming, setNaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createNote, setCreateNote] = useState<string | null>(null);

  const [dragOver, setDragOver] = useState(false);
  const [dropNote, setDropNote] = useState<string | null>(null);
  const [dropChoices, setDropChoices] = useState<FolderItem[]>([]);
  const dragDepth = useRef(0);

  const [nativePicker, setNativePicker] = useState<NativePickerSupport | null>(null);
  const [nativeOpen, setNativeOpen] = useState(false);
  const [nativeNote, setNativeNote] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Read through refs by the asynchronous paths: a host may hand in a fresh
  // callback every render, and an answer that arrives later must see the
  // folder that is on screen THEN, not the one from when it was asked.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const hereRef = useRef(here);
  hereRef.current = here;
  const homeRef = useRef(home);
  homeRef.current = home;
  const showHiddenRef = useRef(showHidden);
  showHiddenRef.current = showHidden;
  const previousRef = useRef<string | null>(null);
  /** Only the newest listing is shown — see "Clicking fast" above. */
  const ticketRef = useRef(0);

  const absorb = useCallback((res: FoldersResponse) => {
    if (res.device_name) setDeviceName(res.device_name);
    const homePath = res.home ?? (res.path === null ? res.entries.find((e) => e.name === "Home")?.path : null);
    if (homePath) setHome(homePath);
  }, []);

  /** Fetch a folder's listing and show it, unless a newer one was asked for. */
  const load = useCallback(
    async (target: string | null, hidden: boolean = showHiddenRef.current) => {
      const ticket = ++ticketRef.current;
      setLoading(true);
      try {
        const res = await fetchFolders(target, hidden);
        if (ticket !== ticketRef.current) return;
        absorb(res);
        setListing({
          path: res.path,
          entries: res.error ? [] : res.entries,
          error: res.error ?? null,
          truncated: Boolean(res.truncated),
        });
      } catch (e) {
        if (ticket !== ticketRef.current) return;
        setListing({ path: target, entries: [], error: (e as Error).message, truncated: false });
      } finally {
        if (ticket === ticketRef.current) setLoading(false);
      }
    },
    [absorb],
  );

  useEffect(() => {
    void load(null);
    void fetchRecents()
      .then((res) => {
        setRecents(res.recents);
        if (res.device_name) setDeviceName(res.device_name);
      })
      .catch(() => {
        /* no recents yet — the group just stays hidden */
      });
    void fetchNativePickerSupport()
      .then(setNativePicker)
      .catch(() => {
        // An older backend has no such route. Treat that as "not available"
        // rather than showing a button that would 404 on click.
        setNativePicker({ available: false });
      });
  }, [load]);

  /**
   * Go to a folder that is known to exist, and — because the folder on screen
   * is the folder chosen — choose it. `null` is the start view, which is a
   * list of places rather than a folder, so it leaves the choice as it was.
   */
  const go = useCallback(
    (target: string | null) => {
      if (target) onSelectRef.current(target);
      previousRef.current = hereRef.current;
      hereRef.current = target;
      setHere(target);
      setText("");
      setCursor(null);
      setNotice(null);
      void load(target);
      // The field keeps the keyboard, so the next name can be typed at once,
      // the way a terminal is ready for the next `cd`.
      inputRef.current?.focus();
    },
    [load],
  );

  /**
   * Open what was typed.
   *
   * A typed path is checked before it is chosen: the folder is listed first,
   * and only when it really is one does it become the selection. Otherwise
   * the message stays next to the field, the text stays for correcting, and
   * the previous choice stands.
   *
   * A bare name that is not a folder here is looked up by name on the whole
   * machine. One folder of exactly that name is opened straight away, so a
   * project can be reached from anywhere by typing what it is called.
   */
  const submitTyped = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (/^cd\s+-$/i.test(trimmed)) {
        go(previousRef.current);
        return;
      }
      // A bare `cd` goes home, as it does in a shell.
      const typed = normalizeTypedPath(trimmed) || "~";
      const base = hereRef.current ?? homeRef.current;
      const ticket = ++ticketRef.current;
      setLoading(true);
      setNotice(null);
      try {
        const res =
          isAbsolutePath(typed) || !base
            ? await fetchFolders(typed, showHiddenRef.current)
            : await fetchFolders(typed, showHiddenRef.current, base);
        if (ticket !== ticketRef.current) return;
        absorb(res);
        if (!res.error && res.path) {
          previousRef.current = hereRef.current;
          hereRef.current = res.path;
          setHere(res.path);
          setListing({
            path: res.path,
            entries: res.entries,
            error: null,
            truncated: Boolean(res.truncated),
          });
          setText("");
          setCursor(null);
          onSelectRef.current(res.path);
          return;
        }
        if (!looksLikePath(typed) && typed.length >= SEARCH_MIN) {
          const found = await searchFolders(typed);
          if (ticket !== ticketRef.current) return;
          const exact = found.entries.filter((entry) => sameName(entry.name, typed));
          if (exact.length === 1) {
            go(exact[0].path);
            return;
          }
          setHits({ word: typed, entries: found.entries });
          if (found.entries.length > 0) return;
        }
        setNotice(res.error || t("ide_folder_picker.not_a_folder"));
      } catch (e) {
        if (ticket === ticketRef.current) setNotice((e as Error).message);
      } finally {
        if (ticket === ticketRef.current) setLoading(false);
      }
    },
    [absorb, go, t],
  );

  // ------------------------------------------------------------ what is typed
  const typed = normalizeTypedPath(text);
  const parts = useMemo(() => typedParts(typed), [typed]);
  const pathMode = parts.dir !== "";
  const word = pathMode ? "" : parts.leaf;

  // The folder whose contents the typed text is matched against: its own
  // folder part, or — for a bare word on the start view — the home folder,
  // because that is where `cd Desktop` starts from in a terminal.
  const lookup = pathMode ? parts.dir : typed && here === null ? (home ?? "~") : "";
  const lookupHidden = showHidden || parts.leaf.startsWith(".");
  const lookupBase = lookup && !isAbsolutePath(lookup) ? (here ?? home) : null;
  const previewKey = lookup ? `${lookup}\n${lookupHidden}\n${lookupBase ?? ""}` : "";

  useEffect(() => {
    if (!previewKey) {
      setPreview(null);
      return;
    }
    // Asked at once, with no pause: the key changes only when the FOLDER part
    // of the text does (at a separator), never on the letters of a name, so
    // there is no burst of requests to hold back.
    let cancelled = false;
    const request = lookupBase
      ? fetchFolders(lookup, lookupHidden, lookupBase)
      : fetchFolders(lookup, lookupHidden);
    request
      .then((res) => {
        if (cancelled) return;
        setPreview({
          key: previewKey,
          path: res.path,
          entries: res.error ? [] : res.entries,
          error: res.error ?? null,
        });
      })
      .catch((e) => {
        if (!cancelled) {
          setPreview({ key: previewKey, path: null, entries: [], error: (e as Error).message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [previewKey, lookup, lookupHidden, lookupBase]);

  const livePreview = preview && preview.key === previewKey ? preview : null;

  // A bare word is also looked up by name on the whole machine once it is long
  // enough; a path is a place and never reaches the name search.
  useEffect(() => {
    if (word.length < SEARCH_MIN) {
      setHits(null);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const handle = window.setTimeout(() => {
      searchFolders(word)
        .then((res) => {
          if (!cancelled) setHits({ word, entries: res.entries });
        })
        .catch(() => {
          if (!cancelled) setHits({ word, entries: [] });
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [word]);

  // A full path that names an existing folder is chosen as it is typed, with
  // no Enter needed: someone who types `C:\work\shop` and then clicks the
  // host's button must get that folder, not the one chosen before.
  useEffect(() => {
    if (!livePreview || livePreview.error || !isAbsolutePath(typed)) return;
    const target = parts.leaf
      ? livePreview.entries.find((entry) => sameName(entry.name, parts.leaf))?.path
      : livePreview.path;
    if (!target || samePath(target, hereRef.current)) return;
    previousRef.current = hereRef.current;
    hereRef.current = target;
    setHere(target);
    onSelectRef.current(target);
    void load(target);
  }, [livePreview, parts.leaf, typed, load]);

  // ------------------------------------------------------------------- rows
  const listingIsHere = samePath(listing.path, here);
  const machine = deviceName || t("ide_folder_picker.this_machine");

  const { sections, listed, context } = useMemo(() => {
    const out: Section[] = [];
    const seen = new Set<string>();
    const add = (label: string | null, candidates: Row[]) => {
      const fresh = candidates.filter((row) => {
        if (row.kind === "create") return true;
        const id = row.path.replace(/[\\/]+$/, "").toLowerCase();
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      });
      if (fresh.length > 0) out.push({ label, rows: fresh });
    };
    const folderRows = (items: FolderItem[], withPath = false): Row[] =>
      items.map((item) => ({
        kind: "folder",
        key: `folder:${item.path}`,
        path: item.path,
        name: item.name,
        item,
        detail: withPath ? item.path : undefined,
      }));
    const recentRows = (items: RecentWorkspace[]): Row[] =>
      items.map((recent) => ({
        kind: "recent",
        key: `recent:${recent.path}`,
        path: recent.path,
        name: recent.name,
        recent,
      }));

    // The folder a new one would be made in, and what it already holds.
    let contextDir: { path: string | null; entries: FolderItem[] } | null = null;

    if (!typed) {
      // Laid out by what the LISTING is, not by where the address bar already
      // points: while a folder is on its way, the one before it stays on
      // screen (dimmed, see `stale`) instead of the list going blank.
      if (listing.path === null) {
        add(t("ide_folder_picker.recent_folders"), recentRows(recents));
        add(t("ide_folder_picker.places"), folderRows(listing.entries, true));
      } else {
        add(null, folderRows(listing.entries));
      }
    } else if (pathMode) {
      if (livePreview && !livePreview.error) {
        contextDir = { path: livePreview.path, entries: livePreview.entries };
        add(
          fill(t("ide_folder_picker.folders_in"), { folder: livePreview.path ?? parts.dir }),
          folderRows(matchByName(livePreview.entries, parts.leaf)),
        );
      }
    } else {
      if (here === null && listingIsHere) {
        // By NAME only. Matching the path as well put every recent folder that
        // lives on the Desktop above the Desktop itself, and "cd Desktop"
        // followed by Enter opened one of them.
        add(t("ide_folder_picker.recent_folders"), recentRows(matchByName(recents, word)));
        add(t("ide_folder_picker.places"), folderRows(matchByName(listing.entries, word), true));
        if (livePreview && !livePreview.error) {
          contextDir = { path: livePreview.path, entries: livePreview.entries };
          add(t("ide_folder_picker.in_home"), folderRows(matchByName(livePreview.entries, word)));
        }
      } else if (here !== null && listingIsHere) {
        contextDir = { path: here, entries: listing.entries };
        add(
          fill(t("ide_folder_picker.folders_in"), { folder: leafName(here) }),
          folderRows(matchByName(listing.entries, word)),
        );
      }
      if (hits && hits.word === word) {
        add(
          fill(t("ide_folder_picker.elsewhere"), { machine }),
          folderRows(hits.entries.slice(0, HITS_SHOWN), true),
        );
      }
    }

    // Nothing there is called anything like the typed name: the one thing
    // left to do with it is make it. Offered as a row of its own and never
    // highlighted by itself, so a typo followed by Enter cannot leave a folder
    // behind on the disk. While folders still match, the name is being
    // completed, not invented, and the offer would only be in the way.
    const foundElsewhere =
      hits !== null &&
      hits.word === word &&
      hits.entries.some((entry) => sameName(entry.name, parts.leaf));
    if (
      contextDir &&
      isFolderName(parts.leaf) &&
      !foundElsewhere &&
      matchByName(contextDir.entries, parts.leaf).length === 0
    ) {
      out.push({
        label: null,
        rows: [
          {
            kind: "create",
            key: `create:${contextDir.path}:${parts.leaf}`,
            parent: contextDir.path,
            name: parts.leaf.trim(),
          },
        ],
      });
    }

    return { sections: out, listed: out.flatMap((section) => section.rows), context: contextDir };
  }, [typed, here, recents, listing, listingIsHere, pathMode, livePreview, parts, word, hits, machine, t]);

  // The list still shows the folder before this one: the address bar moved on
  // the click, the listing has not arrived. Those rows are dimmed and cannot
  // be opened, by pointer or by key, because they are not in the folder the
  // bar names.
  const stale = !typed && !listingIsHere;
  const rows = stale ? NO_ROWS : listed;

  // The first match is highlighted while a name is being typed, so Enter opens
  // it. With no name there is nothing to prefer, and Enter means the typed
  // path itself (or, in the empty field, "use this folder").
  const defaultIndex = parts.leaf && rows.length > 0 && rows[0].kind !== "create" ? 0 : -1;
  const activeIndex =
    cursor && cursor.text === text && cursor.index < rows.length ? cursor.index : defaultIndex;

  useEffect(() => {
    if (activeIndex < 0) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-row="${activeIndex}"]`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex]);

  // -------------------------------------------------------------- actions
  /** Make the folder, then treat it like any other folder that was opened. */
  const makeFolder = (parent: string | null, name: string) => {
    if (creating) return;
    setCreating(true);
    setCreateNote(null);
    createFolder({ parent, name })
      .then((res) => {
        if (res.error || !res.folder) {
          setCreateNote(res.error || t("ide_folder_picker.create_failed"));
          return;
        }
        setNaming(false);
        setNewName("");
        go(res.folder.path);
      })
      .catch((e) => setCreateNote((e as Error).message))
      .finally(() => setCreating(false));
  };

  const activate = (row: Row) => {
    if (row.kind === "create") {
      makeFolder(row.parent, row.name);
      return;
    }
    go(row.path);
    if (row.kind === "recent") onSelectRecent?.(row.recent);
  };

  /**
   * Tab: put the highlighted folder into the field with a separator after it,
   * so the next part of the path can be typed straight on. A folder inside the
   * one being typed keeps the text relative, the way a shell completes it; a
   * folder from anywhere else is written out in full.
   */
  const complete = (row: Row) => {
    if (row.kind === "create") return;
    const sep = separatorOf(row.path);
    // The folder the typed text is read against. For a bare word that is known
    // without waiting for any listing: the folder on screen, or home.
    const base = pathMode ? (context?.path ?? null) : (here ?? home);
    const inside = base ? samePath(parentPath(row.path), base) : false;
    setText(inside ? `${parts.dir}${row.name}${sep}` : `${row.path.replace(/[\\/]+$/, "")}${sep}`);
    setCursor(null);
    setNotice(null);
  };

  const goUp = () => {
    if (here !== null) go(parentPath(here));
  };

  const onFieldKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (event.altKey && event.key === "ArrowUp") {
        event.preventDefault();
        goUp();
        return;
      }
      if (rows.length === 0) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next =
        activeIndex < 0
          ? step > 0
            ? 0
            : rows.length - 1
          : (activeIndex + step + rows.length) % rows.length;
      setCursor({ text, index: next });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (activeIndex >= 0) activate(rows[activeIndex]);
      else if (text.trim()) void submitTyped(text);
      else if (selected) onConfirm?.();
      return;
    }
    if (event.key === "Tab" && !event.shiftKey && text) {
      const row = rows[activeIndex >= 0 ? activeIndex : 0];
      if (row && row.kind !== "create") {
        event.preventDefault();
        complete(row);
      }
      return;
    }
    if (event.key === "Escape" && text) {
      // The host is told through `data-escape-local` that this one is ours.
      event.preventDefault();
      setText("");
      setCursor(null);
      setNotice(null);
      return;
    }
    // Not on a held key: clearing a long text by holding Backspace would
    // otherwise run on up the folder tree once the field is empty.
    if (event.key === "Backspace" && !text && !event.repeat && here !== null) {
      event.preventDefault();
      goUp();
    }
  };

  /**
   * A pasted path is a destination: it is opened at once instead of waiting in
   * the field for an Enter nobody knows is needed. A pasted name stays a
   * search, and a paste into text that is being edited is left alone.
   */
  const onFieldPaste = (event: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text").trim();
    const input = event.currentTarget;
    const replacesAll =
      !input.value || (input.selectionStart === 0 && input.selectionEnd === input.value.length);
    if (!pasted || /[\r\n]/.test(pasted) || !replacesAll) return;
    if (!looksLikePath(normalizeTypedPath(pasted))) return;
    event.preventDefault();
    setText(pasted);
    void submitTyped(pasted);
  };

  const toggleHidden = () => {
    const next = !showHidden;
    setShowHidden(next);
    showHiddenRef.current = next;
    void load(here, next);
  };

  /**
   * Hand over to the operating system's own folder window.
   *
   * The request stays open for as long as the window does — a person deciding
   * where their project lives is not a slow response — so the button reports
   * that a window is waiting for them.
   */
  const browseNatively = () => {
    if (nativeOpen) return;
    setNativeOpen(true);
    setNativeNote(null);
    void openNativePicker(selected ?? here)
      .then((res) => {
        if (res.path) go(res.path);
        else if (res.error) setNativeNote(res.error);
        // A cancelled dialog says nothing: the user closed it on purpose and
        // whatever was selected before is still selected.
      })
      .catch((e) => setNativeNote((e as Error).message))
      .finally(() => setNativeOpen(false));
  };

  // ------------------------------------------------------------ drag & drop
  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    setDropChoices([]);
    // Read the DataTransfer BEFORE awaiting anything (see extractDropPayload).
    const payload = extractDropPayload(event.dataTransfer);
    if (!payload.path && !payload.name) {
      setDropNote(t("ide_folder_picker.drop_not_folder"));
      return;
    }
    setDropNote(t("ide_folder_picker.drop_finding"));
    // The desktop shell knows the real path of what was dropped and says so a
    // moment after the drop; with only a name, that beats searching for it.
    // The wait itself is armed here, synchronously, so no announcement is
    // missed — outside the shell it answers null at once.
    const nativePaths = payload.path
      ? Promise.resolve(null)
      : waitForNativeDrop({ name: payload.name });
    void nativePaths
      .then((native) =>
        resolveDroppedFolder(native?.paths[0] ? { path: native.paths[0] } : payload),
      )
      .then((res) => {
        if (res.resolved) {
          setDropNote(res.detail || null);
          go(res.resolved);
        } else {
          setDropChoices(res.candidates);
          setDropNote(res.detail || t("ide_folder_picker.drop_not_found"));
        }
      })
      .catch((e) => setDropNote((e as Error).message));
  };

  // The same backstop every other drop target in the app needs: a drag that
  // ends outside the window sends no `dragleave`, `drop` or `dragend`, and the
  // highlight would otherwise sit over the folder list for good (BUG-167).
  const clearDragOver = useCallback(() => {
    dragDepth.current = 0;
    setDragOver(false);
  }, []);
  useDragSessionEnd(dragOver, clearDragOver);

  // ------------------------------------------------------------------ render
  const crumbs = here ? foldCrumbs(pathCrumbs(here)) : [];
  const busy = loading || searching || (previewKey !== "" && !livePreview);
  const newFolderHome = here ?? t("ide_folder_picker.your_home_folder");

  let empty: string | null = null;
  if (listed.length === 0 && !busy) {
    if (typed) {
      empty = livePreview?.error ?? fill(t("ide_folder_picker.no_match"), { query: typed });
    } else if (listing.error && listingIsHere) {
      empty = listing.error;
    } else if (here !== null) {
      empty = t("ide_folder_picker.empty_folder");
    } else {
      empty = t("ide_folder_picker.empty_start");
    }
  }

  let rowIndex = -1;

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        dragDepth.current += 1;
        setDragOver(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragOver(false);
      }}
      onDrop={onDrop}
      data-testid="folder-drop-zone"
      className={cn("relative flex min-h-0 min-w-0 flex-1 flex-col p-3", className)}
    >
      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-40 flex flex-col items-center justify-center gap-2 rounded-surface border-2 border-dashed border-primary/60 bg-background/95">
          <FolderOpen className="h-8 w-8 text-primary" />
          <span className="text-sm font-medium text-foreground">
            {t("ide_folder_picker.drop_overlay")}
          </span>
        </div>
      )}

      {/* -------------------------------------------------------------- field */}
      <div className="relative shrink-0" data-escape-local={text ? "" : undefined}>
        {busy ? (
          <Loader2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : (
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        )}
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setNotice(null);
          }}
          onKeyDown={onFieldKeyDown}
          onPaste={onFieldPaste}
          placeholder={t("ide_folder_picker.search_placeholder")}
          aria-label={t("ide_folder_picker.search_aria")}
          aria-controls="folder-picker-list"
          aria-invalid={notice ? true : undefined}
          data-testid="folder-search"
          data-autofocus
          className={cn(
            "h-11 w-full rounded-surface border border-border bg-background pl-10 pr-10 text-sm",
            "text-foreground placeholder:text-muted-foreground outline-none transition-colors",
            "focus:border-foreground/40",
            notice && "border-destructive/60 focus:border-destructive/60",
          )}
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
        />
        {text && (
          <IconButton
            size="sm"
            label={t("ide_folder_picker.clear_search")}
            onClick={() => {
              setText("");
              setNotice(null);
              inputRef.current?.focus();
            }}
            className="absolute right-2.5 top-1/2 -translate-y-1/2"
          >
            <X className="h-3.5 w-3.5" />
          </IconButton>
        )}
      </div>

      {notice && (
        <p className="mt-1.5 shrink-0 px-1 text-xs text-destructive" role="alert">
          {notice}
        </p>
      )}

      {/* -------------------------------------------------------- address bar */}
      <div className="mt-2 flex h-9 shrink-0 items-center gap-1">
        <IconButton
          label={t("ide_folder_picker.go_up")}
          onClick={goUp}
          disabled={here === null}
        >
          <CornerLeftUp className="h-4 w-4" />
        </IconButton>
        <nav
          aria-label={t("ide_folder_picker.folder_path")}
          className="flex h-full min-w-0 flex-1 items-center"
        >
          <button
            type="button"
            onClick={() => go(null)}
            title={fill(t("ide_folder_picker.start_title"), { machine })}
            aria-current={here === null ? "location" : undefined}
            className={cn(
              CRUMB,
              here === null ? "max-w-full shrink font-medium text-foreground" : "shrink-0",
            )}
          >
            <Monitor className="h-3.5 w-3.5 shrink-0" />
            {/* The name leaves once a path is shown: it is on the button's
                title still, and the path needs the room more. */}
            <span className={cn("truncate", here !== null && "sr-only")}>{machine}</span>
          </button>
          {crumbs.map((crumb, index) => {
            const last = index === crumbs.length - 1;
            return (
              <Fragment key={`${crumb.path}:${crumb.folded ? "fold" : "crumb"}`}>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
                <button
                  type="button"
                  onClick={() => go(crumb.path)}
                  title={crumb.path}
                  aria-label={crumb.folded ? t("ide_folder_picker.show_whole_path") : undefined}
                  aria-current={last ? "location" : undefined}
                  className={cn(
                    CRUMB,
                    // The root ("C:", "/") is short and says which disk: it
                    // keeps its width, the folders after it give way first.
                    crumb.folded || index === 0 ? "shrink-0" : "min-w-[1.5rem] shrink",
                    last && "font-medium text-foreground",
                  )}
                >
                  <span className="truncate">{crumb.label}</span>
                </button>
              </Fragment>
            );
          })}
        </nav>

        <Button
          variant="subtle"
          onClick={() => {
            setNaming(true);
            setNewName("");
            setCreateNote(null);
          }}
          disabled={naming}
          data-testid="new-folder"
          title={fill(t("ide_folder_picker.new_folder_title"), { path: newFolderHome })}
          className="px-2"
        >
          <FolderPlus className="h-4 w-4" />
          <span className="hidden sm:inline">{t("ide_folder_picker.new_folder")}</span>
        </Button>
        {nativePicker?.available && (
          <Button
            variant="subtle"
            onClick={browseNatively}
            disabled={nativeOpen}
            data-testid="native-browse"
            title={t("ide_folder_picker.browse_title")}
            className="px-2"
          >
            {nativeOpen ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FolderOpen className="h-4 w-4" />
            )}
            <span className="hidden sm:inline">
              {nativeOpen ? t("ide_folder_picker.window_open") : t("ide_folder_picker.browse")}
            </span>
          </Button>
        )}
        <IconButton
          label={showHidden ? t("ide_folder_picker.hide_hidden") : t("ide_folder_picker.show_hidden")}
          title={
            showHidden
              ? t("ide_folder_picker.hidden_shown_title")
              : t("ide_folder_picker.hidden_list_title")
          }
          aria-pressed={showHidden}
          onClick={toggleHidden}
          data-testid="toggle-hidden"
          className={cn(showHidden && "text-foreground")}
        >
          {showHidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        </IconButton>
      </div>

      {/* The window can still end up behind the app — a user who does not know
          it is there just sees a button that hung. Saying so costs one line. */}
      {nativeOpen && (
        <p className="mt-1 shrink-0 px-1 text-xs text-muted-foreground" role="status">
          {t("ide_folder_picker.native_open_note")}
        </p>
      )}

      {/* --------------------------------------------------------- new folder */}
      {naming && (
        <form
          data-testid="new-folder-form"
          data-escape-local
          className="mt-1 shrink-0 rounded-surface border border-border bg-secondary/40 p-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) makeFolder(here, newName);
          }}
        >
          <div className="flex items-center gap-2">
            <FolderPlus className="ml-1 h-4 w-4 shrink-0 text-muted-foreground" />
            <Field
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setNaming(false);
                  setCreateNote(null);
                  inputRef.current?.focus();
                }
              }}
              placeholder={t("ide_folder_picker.new_folder_name")}
              aria-label={t("ide_folder_picker.new_folder_name")}
              data-testid="new-folder-name"
              className="min-w-0 flex-1"
              spellCheck={false}
              autoComplete="off"
            />
            <Button
              type="submit"
              variant="primary"
              disabled={creating || !newName.trim()}
              data-testid="new-folder-create"
            >
              {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {t("ide_folder_picker.create")}
            </Button>
            <IconButton
              label={t("ide_folder_picker.cancel_new_folder")}
              onClick={() => {
                setNaming(false);
                setCreateNote(null);
              }}
            >
              <X className="h-4 w-4" />
            </IconButton>
          </div>
          <p className="mt-1.5 truncate pl-7 text-xs text-muted-foreground">
            {t("ide_folder_picker.created_in")}{" "}
            <span className="font-mono">{newFolderHome}</span>
          </p>
        </form>
      )}
      {createNote && (
        <p className="mt-1 shrink-0 px-1 text-xs text-destructive" role="alert">
          {createNote}
        </p>
      )}

      {/* --------------------------------------------------------------- list */}
      <div
        ref={listRef}
        id="folder-picker-list"
        role="listbox"
        aria-label={t("ide_folder_picker.folder_list")}
        aria-busy={busy}
        className={cn(
          "mt-1 min-h-[14rem] flex-1 overflow-y-auto scrollbar-jarvis border-t border-border pt-1",
          "transition-opacity duration-150",
          stale && "pointer-events-none opacity-40 delay-100",
        )}
      >
        {sections.map((section, sectionIndex) => (
          <section key={`${section.label ?? "rows"}:${sectionIndex}`} aria-label={section.label ?? undefined}>
            {section.label && (
              <div className="truncate px-2.5 pb-1 pt-3" title={section.label}>
                <SectionLabel>{section.label}</SectionLabel>
              </div>
            )}
            <ul>
              {section.rows.map((row) => {
                rowIndex += 1;
                return (
                  <PickerRow
                    key={row.key}
                    row={row}
                    index={rowIndex}
                    active={rowIndex === activeIndex}
                    chosen={row.kind !== "create" && samePath(row.path, selected)}
                    home={home}
                    creating={creating}
                    showTerminals={Boolean(onSelectRecent)}
                    onActivate={activate}
                    onForget={(recent) => {
                      setRecents((prev) => prev.filter((r) => r.path !== recent.path));
                      void forgetRecent(recent.path).catch(() => {
                        /* list refreshes on next visit */
                      });
                    }}
                  />
                );
              })}
            </ul>
          </section>
        ))}

        {empty && (
          <p className="px-6 py-10 text-center text-sm text-muted-foreground">{empty}</p>
        )}
        {listed.length === 0 && busy && (
          <p className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("ide_folder_picker.loading")}
          </p>
        )}
        {!typed && listingIsHere && listing.truncated && (
          <p className="px-2.5 py-3 text-xs text-muted-foreground">
            {fill(t("ide_folder_picker.truncated"), { count: listing.entries.length })}
          </p>
        )}
      </div>

      {/* ------------------------------------------------------------ choice */}
      {showSelection && <SelectedFolder selected={selected} />}

      {/* ---------------------------------------------------------- reporting */}
      {(nativeNote && !nativeOpen) || dropNote ? (
        <div className="mt-2 shrink-0 space-y-1.5 px-1">
          {nativeNote && !nativeOpen && (
            <p className="text-xs text-muted-foreground" role="alert">
              {nativeNote}
            </p>
          )}
          {dropNote && (
            <>
              <p className="text-xs text-muted-foreground">{dropNote}</p>
              {dropChoices.length > 0 && (
                <ul>
                  {dropChoices.map((choice) => (
                    <li key={choice.path}>
                      <button
                        type="button"
                        onClick={() => {
                          setDropNote(null);
                          setDropChoices([]);
                          go(choice.path);
                        }}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-control px-1.5 py-1 text-left text-xs hover:bg-secondary",
                          FOCUS_RING,
                        )}
                      >
                        <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <code className="min-w-0 truncate font-mono">{choice.path}</code>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

const CRUMB =
  "inline-flex h-7 min-w-0 items-center gap-1.5 rounded-control px-1.5 text-xs " +
  "text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground " +
  FOCUS_RING;

const ROW =
  "flex h-9 w-full items-center gap-2.5 rounded-control px-2.5 text-left text-sm " +
  "transition-colors " +
  FOCUS_RING;

const KEY =
  "rounded border border-border bg-background px-1 font-mono text-micro leading-4 text-muted-foreground";

/** A drive or the file system's root: a place, drawn as a disk and not a folder. */
function isRootPath(fullPath: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]?|[\\/])$/.test(fullPath);
}

/**
 * One line of the list: a folder to open, or the offer to make one.
 *
 * One line each, on purpose. The old rows were two lines tall (name over path)
 * and every third one carried a badge, so a list of twenty folders read as
 * forty lines of mixed weight. The path sits behind the name, in the quiet
 * colour, only where the name alone does not say which folder is meant.
 */
function PickerRow({
  row,
  index,
  active,
  chosen,
  home,
  creating,
  showTerminals,
  onActivate,
  onForget,
}: {
  row: Row;
  index: number;
  active: boolean;
  chosen: boolean;
  home: string | null;
  creating: boolean;
  showTerminals: boolean;
  onActivate: (row: Row) => void;
  onForget: (recent: RecentWorkspace) => void;
}) {
  const t = useT();
  const surface = active ? "bg-secondary" : "hover:bg-secondary/60";

  if (row.kind === "create") {
    return (
      <li>
        <button
          type="button"
          role="option"
          aria-selected={active}
          data-row={index}
          data-testid="create-offer"
          onClick={() => onActivate(row)}
          disabled={creating}
          className={cn(ROW, surface, "text-foreground disabled:opacity-50")}
        >
          {creating ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <FolderPlus className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="shrink-0 truncate">
            {fill(t("ide_folder_picker.create_folder_named"), { folder: row.name })}
          </span>
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
            {fill(t("ide_folder_picker.in_parent"), {
              path: row.parent ?? t("ide_folder_picker.your_home_folder"),
            })}
          </span>
          {active && <kbd className={KEY}>↵</kbd>}
        </button>
      </li>
    );
  }

  const recent = row.kind === "recent" ? row.recent : null;
  const item = row.kind === "folder" ? row.item : null;
  const Icon = recent
    ? History
    : home && samePath(row.path, home)
      ? Home
      : isRootPath(row.path)
        ? HardDrive
        : item?.is_repo
          ? FolderGit2
          : Folder;
  // A root is named by its own path, so the path behind it would say it twice.
  const detail = recent
    ? recent.path
    : row.kind === "folder" && row.detail && !sameName(row.detail, row.name)
      ? row.detail
      : null;

  return (
    <li className="group/row relative">
      <button
        type="button"
        role="option"
        aria-selected={active}
        data-row={index}
        onClick={() => onActivate(row)}
        title={row.path}
        className={cn(ROW, surface, recent && "pr-9")}
      >
        <Icon
          data-testid={recent ? "recent-folder-icon" : undefined}
          className={cn("h-4 w-4 shrink-0", chosen ? "text-primary" : "text-muted-foreground")}
        />
        <span className={cn("truncate", detail ? "max-w-[55%] shrink-0" : "min-w-0 flex-1", chosen && "font-medium")}>
          {row.name}
        </span>
        {detail && (
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
            {detail}
          </span>
        )}
        {chosen && <Check className="h-3.5 w-3.5 shrink-0 text-primary" strokeWidth={3} />}
        {recent && (
          <span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {/* The terminal count only means something where the layout is
                replayed — the launcher. */}
            {showTerminals &&
              `${fill(
                t(
                  recent.terminals === 1
                    ? "ide_folder_picker.terminals_one"
                    : "ide_folder_picker.terminals_other",
                ),
                { count: recent.terminals },
              )} · `}
            {lastUsedLabel(recent.last_used)}
          </span>
        )}
        {active ? (
          <span className="flex shrink-0 items-center gap-1">
            <kbd className={KEY}>Tab</kbd>
            <kbd className={KEY}>↵</kbd>
          </span>
        ) : (
          !recent && (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100" />
          )
        )}
      </button>
      {recent && (
        <IconButton
          size="sm"
          label={fill(t("ide_folder_picker.forget"), { folder: recent.name })}
          title={t("ide_folder_picker.forget_title")}
          onClick={(e) => {
            e.stopPropagation();
            onForget(recent);
          }}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 bg-secondary opacity-0 focus-visible:opacity-100 group-hover/row:opacity-100"
        >
          <X className="h-3.5 w-3.5" />
        </IconButton>
      )}
    </li>
  );
}

/**
 * The folder that will be used, said once, right above whatever acts on it.
 *
 * The list alone never answers this: a folder that is opened is chosen AND
 * replaced on screen by its contents, so the one row that could have shown
 * the choice is gone the moment it is made.
 */
function SelectedFolder({ selected }: { selected: string | null }) {
  const t = useT();
  return (
    <div
      data-testid="folder-selection"
      role="status"
      aria-live="polite"
      className="mt-2 flex h-10 shrink-0 items-center gap-2.5 border-t border-border px-2.5 pt-2 text-sm"
    >
      {selected ? (
        <>
          <Check className="h-4 w-4 shrink-0 text-primary" strokeWidth={3} />
          <span className="max-w-[45%] shrink-0 truncate font-medium">
            <span className="sr-only">{t("ide_folder_picker.chosen_folder")} </span>
            {leafName(selected)}
          </span>
          <span
            className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground"
            title={selected}
          >
            {selected}
          </span>
        </>
      ) : (
        <>
          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="text-muted-foreground">{t("ide_folder_picker.no_folder_chosen")}</span>
        </>
      )}
    </div>
  );
}
