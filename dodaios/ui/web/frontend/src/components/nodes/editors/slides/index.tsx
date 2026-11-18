/**
 * The deck editor: the person's own way to make and change a deck, with the
 * tools of a presentation program.
 *
 * Layout: the slide strip on the left (thumbnails; add, duplicate, delete,
 * hide, drag to reorder), the selected slide in the middle with the format
 * bar above it and its speaker notes under it, and the inspector on the right
 * (the slide's layout, texts, background and transition; or, with elements
 * selected, their format). The toolbar adds slides, inserts text boxes,
 * shapes, lines and arrows, pictures, tables and charts, sets the deck's
 * design (ready-made looks, theme, type, accent, transitions, footers),
 * shows the grid and snapping, and presents the deck.
 *
 * Every slide has a layout (its texts, laid out by the deck's renderer) and
 * may carry free elements on top (`elementModel.ts`): they are selected,
 * moved, resized, rotated, aligned, ordered, copied and pasted on the canvas
 * (`CanvasEditor.tsx`) and formatted in the inspector.
 *
 * How a slide is drawn: by `SlideView`, in React, with the deck page's own
 * stylesheet (taken from the server's preview of the page, `deckPage.ts`).
 * That is the page's exact look at the speed of local rendering. Only the
 * charts' figures come from the server (its renderer is the page's), and only
 * when a chart changes.
 *
 * Every change goes through `useNodeSpecEditor`: each action is one labelled
 * undo step, typing in one field is one step per run, a drag is one step,
 * and the deck is saved shortly after each change.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent, type ReactNode } from "react";
import {
  ArrowRight,
  BarChart3,
  BringToFront,
  ChevronDown,
  ClipboardPaste,
  Copy,
  Grid3x3,
  ImagePlus,
  Keyboard,
  Loader2,
  Lock,
  Magnet,
  Maximize,
  Minus,
  MonitorPlay,
  NotebookPen,
  Palette,
  Play,
  Plus,
  Scissors,
  Search,
  SendToBack,
  Shapes,
  SlidersHorizontal,
  Table2,
  Trash2,
  Type,
  Unlock,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import { useElementSize } from "@/hooks/useElementSize";
import { fill, useT } from "@/i18n";
import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { authorName, useNodeLive } from "../../live/liveStore";
import { ChartEditor } from "../charts/ChartEditor";
import { validateChart, type ChartJson } from "../charts/chartModel";
import { ColorPicker, MenuDivider, MenuItem, Popover, ToolbarButton, ToolbarSeparator } from "../controls";
import { EditorShell } from "../EditorShell";
import { produce } from "../produce";
import type { NodeEditorProps } from "../types";
import { useNodeSpecEditor } from "../useNodeSpecEditor";
import { CanvasEditor, type ElementsChange } from "./CanvasEditor";
import { ContextMenu, MenuSeparator } from "./ContextMenu";
import {
  ACCENT_SWATCHES,
  accentColor,
  blankSlide,
  canAddSlide,
  copySlide,
  indexAfterMove,
  LIMITS,
  moveSlide,
  readDeck,
  switchLayout,
  type Deck,
  type DeckChart,
  type Layout,
  type Slide,
  type Translate,
} from "./deckModel";
import { diffDecks, firstWritten, indexAfterRevision } from "./deckDiff";
import { loadDeckCss } from "./deckPage";
import { ElementInspector, ShapeGlyph } from "./ElementInspector";
import {
  boundsOf,
  cloneElement,
  elementKey,
  hasText,
  MAX_ELEMENTS,
  newId,
  readElement,
  SHAPES,
  SLIDE_H,
  SLIDE_W,
  translate,
  type Background,
  type DeckExtras,
  type SlideElement,
} from "./elementModel";
import { ElementEditingProvider, ElementFiguresProvider, type ElementEditing } from "./elements";
import { findInDeck, replaceAll } from "./findReplace";
import { FormatBar } from "./FormatBar";
import { MOD } from "./keys";
import { firstImage, imageForSlide, ImageTooLargeError, ImageTypeError } from "./images";
import { clean } from "./inline";
import { LayoutPicker } from "./LayoutPicker";
import { PresentView } from "./PresentView";
import { SlideCanvas } from "./SlideCanvas";
import { DeckDesign, SlideDesign } from "./SlideDesign";
import { SlideInspector } from "./SlideInspector";
import { SlideStrip } from "./SlideStrip";
import { DeckLookProvider, pathKey, SlideEditingProvider, SlideView, type FieldPath, type SlideEditing } from "./SlideView";
import { useChartFigures, useElementFigures } from "./useChartFigures";

/** Optional one-line texts a slide drops when they are emptied (see `pruneEmpty`). */
const OPTIONAL_TEXTS = ["kicker", "title", "subtitle", "text", "quote", "by", "caption", "notes"] as const;

/** The value at `path` of a slide is now `value` (on a draft). */
export function setSlideText(slide: Slide, path: FieldPath, value: string): void {
  let holder: unknown = slide;
  for (const part of path.slice(0, -1)) {
    if (holder === null || typeof holder !== "object") return;
    holder = (holder as Record<string | number, unknown>)[part];
  }
  const last = path[path.length - 1];
  if (holder !== null && typeof holder === "object") (holder as Record<string | number, unknown>)[last] = value;
}

/**
 * Remove the texts the person emptied: on the page an empty text is no text,
 * and the field the person left must not linger as an empty box. List items
 * stay (an emptied point is removed with Backspace or the inspector).
 */
export function pruneEmpty(slide: Slide): void {
  for (const key of OPTIONAL_TEXTS) if (slide[key] === "") delete slide[key];
  for (const column of slide.columns ?? []) {
    if (column.title === "") delete column.title;
    if (column.text === "") delete column.text;
  }
  for (const stat of slide.stats ?? []) {
    if (stat.label === "") delete stat.label;
    if (stat.detail === "") delete stat.detail;
  }
  for (const step of slide.steps ?? []) {
    if (step.title === "") delete step.title;
    if (step.text === "") delete step.text;
  }
}

/** Every element of the deck gets an id, so a selection survives a reorder (on a fresh deck). */
function withIds(deck: Deck): Deck {
  let changed = false;
  const slides = deck.slides.map((slide) => {
    if (!slide.elements?.some((element) => !element.id)) return slide;
    changed = true;
    return { ...slide, elements: slide.elements.map((element) => (element.id ? element : { ...element, id: newId() })) };
  });
  return changed ? { ...deck, slides } : deck;
}

/** The field a new slide's writing starts in. */
function firstField(slide: Slide): string | null {
  if (slide.layout === "quote") return "quote";
  if (slide.layout === "blank") return null;
  if (slide.layout === "image" && !slide.title) return null;
  return "title";
}

/** Chapter numbers of the section slides (0 for the others), in one pass. */
function sectionNumbers(slides: readonly Slide[]): number[] {
  let count = 0;
  return slides.map((slide) => (slide.layout === "section" ? ++count : count));
}

type ImageTarget =
  | { kind: "replace"; index: number }
  | { kind: "add"; at: number }
  | { kind: "layout"; index: number }
  | { kind: "element-add"; at?: { x: number; y: number } }
  | { kind: "element-replace"; index: number }
  | { kind: "background" }
  | { kind: "deck-background" };

type ChartTarget = { kind: "slide" } | { kind: "element"; index: number } | { kind: "new" };

/** The slide a click into the deck's page was on (`/slides/2/title` → 2), else the first. */
function slideOf(path: string | undefined): number {
  const found = /^\/slides\/(\d+)(?:\/|$)/.exec(path ?? "");
  return found ? Number(found[1]) : 0;
}

/** What the editor copies: elements, kept for pasting into any slide or deck. */
const CLIPBOARD_MARK = "dodaios-slide-elements";
let clipboard: SlideElement[] = [];
/** Whether the system clipboard holds the editor's last copy (writing it may be refused). */
let clipboardSynced = false;

function elementsFromText(text: string): SlideElement[] | null {
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    if (!parsed || !Array.isArray(parsed[CLIPBOARD_MARK])) return null;
    return (parsed[CLIPBOARD_MARK] as unknown[]).map(readElement).filter((e): e is SlideElement => e !== null);
  } catch {
    return null;
  }
}

/** Natural size of a picture (a data URI), for placing it at its proportions. */
function pictureSize(src: string): Promise<{ w: number; h: number }> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ w: image.naturalWidth || 4, h: image.naturalHeight || 3 });
    image.onerror = () => resolve({ w: 4, h: 3 });
    image.src = src;
  });
}

export default function SlidesEditor({ node, initial, startAt, onDone }: NodeEditorProps) {
  const t = useT();
  const tr: Translate = useCallback((key, vars) => (vars ? fill(t(key), vars) : t(key)), [t]);
  const L = useCallback((key: string) => t(`nodes.editor.slides.${key}`), [t]);
  const nodeId = node.id ?? "";

  // The hook keeps whatever the stage handed over; the editor reads it as a deck once.
  const [start] = useState(() => ({ ...initial, spec: withIds(readDeck(initial.spec)) }));
  const editor = useNodeSpecEditor<Deck>(nodeId, start, { adopt: (spec) => withIds(readDeck(spec)) });
  const deck = editor.spec;
  const slides = useMemo(() => deck.slides ?? [], [deck.slides]);
  const count = slides.length;

  // Opened by a click into the deck's page: on the slide that was clicked.
  const [selected, setSelected] = useState(() => slideOf(startAt?.path));
  const current = Math.max(0, Math.min(selected, count - 1));
  const slide = slides[current];
  const elements = useMemo(() => slide?.elements ?? [], [slide]);

  // --- the selected elements on the slide -------------------------------------------------------
  const [selection, setSelection] = useState<string[]>([]);
  const [writing, setWriting] = useState(-1);
  const selectedIdx = useMemo(
    () => elements.map((element, index) => (selection.includes(elementKey(element, index)) ? index : -1)).filter((i) => i >= 0),
    [elements, selection],
  );
  useEffect(() => {
    setSelection([]);
    setWriting(-1);
  }, [current]);

  // --- the page's stylesheet -------------------------------------------------
  const [css, setCss] = useState<string | null>(null);
  const [cssFailed, setCssFailed] = useState(false);
  const [cssAttempt, setCssAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setCssFailed(false);
    loadDeckCss(nodeId).then(
      (text) => live && setCss(text),
      () => live && setCssFailed(true),
    );
    return () => {
      live = false;
    };
  }, [nodeId, cssAttempt]);

  const appTheme = useThemeValue();
  const theme: "light" | "dark" = deck.theme === "light" || deck.theme === "dark" ? deck.theme : appTheme;
  const accent = accentColor(deck.accent);
  const deckTitle = clean(node.title, 80);
  const sections = useMemo(() => sectionNumbers(slides), [slides]);
  const figureOf = useChartFigures(nodeId, slides);
  const elementFigure = useElementFigures(nodeId, slides);
  const figures = useMemo(() => ({ chartFigure: elementFigure }), [elementFigure]);
  const look: DeckExtras = useMemo(
    () => ({ font: deck.font, background: deck.background, transition: deck.transition, footer: deck.footer }),
    [deck.font, deck.background, deck.transition, deck.footer],
  );

  // --- following undo, redo and the assistant's revisions --------------------------------
  const ownFrom = useRef<readonly Slide[] | null>(null);
  const previous = useRef(slides);
  useEffect(() => {
    const before = previous.current;
    previous.current = slides;
    if (before === slides) return;
    if (ownFrom.current === before) {
      ownFrom.current = null;
      return;
    }
    // An agent's revision places the stage itself, while it renders (see "following the agent").
    if (editor.remote && editor.remote.next.slides === slides) return;
    let first = 0;
    while (first < Math.min(before.length, slides.length) && before[first] === slides[first]) first++;
    if (first < slides.length || slides.length !== before.length) setSelected(Math.min(first, slides.length - 1));
  }, [slides]);
  useEffect(() => {
    ownFrom.current = null;
  });

  /** One labelled step on the deck, made by the editor itself. */
  const act = useCallback(
    (label: string, change: (draft: Deck) => void, coalesce?: string) => {
      if (produce(deck, change) === deck) return;
      ownFrom.current = slides;
      editor.apply(change, { label, coalesce });
    },
    [deck, editor, slides],
  );

  // --- focus requests (a new slide's title, a new point) ------------------------------------
  const [focusRequest, setFocusRequest] = useState<SlideEditing["focusRequest"]>(null);
  const clearFocusRequest = useCallback(() => setFocusRequest(null), []);
  const [activeField, setActiveField] = useState<string | null>(null);
  const lastTextKey = useRef<string | undefined>(undefined);

  // --- slide actions ------------------------------------------------------------------------
  const select = useCallback((index: number) => setSelected(index), []);

  const insertSlide = useCallback(
    (made: Slide, at: number, label: string) => {
      if (!canAddSlide(deck)) return;
      act(label, (draft) => {
        draft.slides.splice(at, 0, made);
      });
      setSelected(at);
      const field = firstField(made);
      if (field) setFocusRequest({ key: field, select: "all" });
    },
    [act, deck],
  );

  const changeSlide = useCallback(
    (label: string, change: (s: Slide) => void, coalesce?: string) => {
      act(
        label,
        (draft) => {
          const s = draft.slides[current];
          if (s) change(s);
        },
        coalesce,
      );
    },
    [act, current],
  );

  /** A change to the current slide's elements; the list goes when it is emptied. */
  const changeElements: ElementsChange = useCallback(
    (label, change, coalesce) => {
      act(
        label,
        (draft) => {
          const s = draft.slides[current];
          if (!s) return;
          if (!s.elements) s.elements = [];
          change(s.elements);
          if (!s.elements.length) delete s.elements;
        },
        coalesce,
      );
    },
    [act, current],
  );

  /** Put new elements on the current slide and select them. */
  const addElements = useCallback(
    (made: SlideElement[], label: string, write = false) => {
      if (!slide || !made.length) return;
      const room = MAX_ELEMENTS - elements.length;
      const kept = made.slice(0, Math.max(0, room)).map((element) => (element.id ? element : { ...element, id: newId() }));
      if (!kept.length) return;
      changeElements(label, (list) => {
        list.push(...kept);
      });
      setSelection(kept.map((element, i) => elementKey(element, elements.length + i)));
      setWriting(write && kept.length === 1 ? elements.length : -1);
    },
    [changeElements, elements.length, slide],
  );

  /** A free place for a new element: the middle, moved on while another sits exactly there. */
  const freeSpot = useCallback(
    (w: number, h: number) => {
      let x = Math.round((SLIDE_W - w) / 2);
      let y = Math.round((SLIDE_H - h) / 2);
      for (let i = 0; i < 12 && elements.some((element) => element.type !== "line" && element.x === x && element.y === y); i++) {
        x += 24;
        y += 24;
      }
      return { x, y };
    },
    [elements],
  );

  const fileInput = useRef<HTMLInputElement>(null);
  const imageTarget = useRef<ImageTarget | null>(null);
  const [imageError, setImageError] = useState("");
  const [imageBusy, setImageBusy] = useState(false);

  const pickImage = useCallback((target: ImageTarget) => {
    imageTarget.current = target;
    setImageError("");
    fileInput.current?.click();
  }, []);

  const placeImage = useCallback(
    async (file: File, target: ImageTarget) => {
      setImageError("");
      setImageBusy(true);
      try {
        const image = await imageForSlide(file);
        if (target.kind === "replace") {
          act(L("step.replace_image"), (draft) => {
            const s = draft.slides[target.index];
            if (s) s.image = image;
          });
        } else if (target.kind === "layout") {
          act(L("step.layout"), (draft) => {
            const s = draft.slides[target.index];
            if (s) draft.slides[target.index] = { ...switchLayout(s, "image", tr), image };
          });
        } else if (target.kind === "add") {
          insertSlide({ ...blankSlide("image", tr), image }, target.at, L("step.add_image_slide"));
        } else if (target.kind === "element-add") {
          const size = await pictureSize(image);
          const scale = Math.min(640 / size.w, 400 / size.h, 1.5);
          const w = Math.round(size.w * scale);
          const h = Math.round(size.h * scale);
          const spot = target.at ? { x: Math.round(target.at.x - w / 2), y: Math.round(target.at.y - h / 2) } : freeSpot(w, h);
          addElements([{ type: "image", image, ...spot, w, h }], L("step.add_image"));
        } else if (target.kind === "element-replace") {
          changeElements(L("step.replace_image"), (list) => {
            const element = list[target.index];
            if (element?.type === "image") element.image = image;
          });
        } else if (target.kind === "background") {
          changeSlide(L("step.background"), (s) => {
            s.background = { ...(s.background ?? {}), image };
            delete s.background.gradient;
          });
        } else {
          act(L("step.background"), (draft) => {
            draft.background = { ...(draft.background ?? {}), image };
            delete draft.background.gradient;
          });
        }
      } catch (error) {
        setImageError(
          error instanceof ImageTooLargeError ? L("image.too_large") : error instanceof ImageTypeError ? L("image.wrong_type") : L("image.failed"),
        );
      } finally {
        setImageBusy(false);
      }
    },
    [act, addElements, changeElements, changeSlide, freeSpot, insertSlide, L, tr],
  );

  const addSlide = useCallback(
    (layout: Layout) => {
      if (layout === "image") {
        pickImage({ kind: "add", at: current + 1 });
        return;
      }
      insertSlide(blankSlide(layout, tr), current + 1, L("step.add_slide"));
    },
    [current, insertSlide, L, pickImage, tr],
  );

  const duplicateSlide = useCallback(
    (index: number) => {
      const source = slides[index];
      if (!source || !canAddSlide(deck)) return;
      const copy = copySlide(source);
      if (copy.elements) copy.elements = copy.elements.map(cloneElement);
      act(L("step.duplicate"), (draft) => {
        draft.slides.splice(index + 1, 0, copy);
      });
      setSelected(index + 1);
    },
    [act, deck, L, slides],
  );

  const deleteSlide = useCallback(
    (index: number) => {
      if (count <= 1) return;
      act(L("step.delete"), (draft) => {
        draft.slides.splice(index, 1);
      });
      setSelected(Math.min(index, count - 2));
    },
    [act, count, L],
  );

  const toggleHidden = useCallback(
    (index: number) => {
      const target = slides[index];
      if (!target) return;
      act(target.hidden ? L("step.show_slide") : L("step.hide_slide"), (draft) => {
        const s = draft.slides[index];
        if (!s) return;
        if (s.hidden) delete s.hidden;
        else s.hidden = true;
      });
    },
    [act, L, slides],
  );

  const moveTo = useCallback(
    (from: number, to: number) => {
      act(L("step.move"), (draft) => moveSlide(draft, from, to));
      setSelected(indexAfterMove(from, from, to));
    },
    [act, L],
  );

  const changeLayout = useCallback(
    (index: number, layout: Layout) => {
      const source = slides[index];
      if (!source || source.layout === layout) return;
      if (layout === "image" && !source.image) {
        pickImage({ kind: "layout", index });
        return;
      }
      act(L("step.layout"), (draft) => {
        draft.slides[index] = switchLayout(source, layout, tr);
      });
    },
    [act, L, pickImage, slides, tr],
  );

  const setText = useCallback(
    (path: FieldPath, value: string) => {
      const key = `text:${current}:${pathKey(path)}`;
      lastTextKey.current = key;
      act(
        path[0] === "notes" ? L("step.notes") : L("step.type"),
        (draft) => {
          const s = draft.slides[current];
          if (s) setSlideText(s, path, value);
        },
        key,
      );
    },
    [act, current, L],
  );

  /** A field was left: texts emptied in it go, as part of the same typing step. */
  const leaveField = useCallback(() => {
    const s = slides[current];
    if (!s) return;
    act(
      L("step.type"),
      (draft) => {
        const target = draft.slides[current];
        if (target) pruneEmpty(target);
      },
      lastTextKey.current,
    );
  }, [act, current, L, slides]);

  // --- element actions ---------------------------------------------------------------------------
  const removeSelected = useCallback(() => {
    if (!selectedIdx.length) return;
    const gone = new Set(selectedIdx);
    changeElements(L("step.delete_element"), (list) => {
      for (let i = list.length - 1; i >= 0; i--) if (gone.has(i)) list.splice(i, 1);
    });
    setSelection([]);
    setWriting(-1);
  }, [changeElements, L, selectedIdx]);

  const duplicateSelected = useCallback(() => {
    const made = selectedIdx.map((i) => {
      const copy = cloneElement(elements[i]);
      translate(copy, 24, 24);
      delete copy.locked;
      return copy;
    });
    addElements(made, L("step.duplicate_element"));
  }, [addElements, elements, L, selectedIdx]);

  const copySelected = useCallback(
    (cut: boolean) => {
      if (!selectedIdx.length) return;
      clipboard = selectedIdx.map((i) => JSON.parse(JSON.stringify(elements[i])) as SlideElement);
      clipboardSynced = false;
      // The system clipboard may refuse; then a paste takes the editor's own copy.
      Promise.resolve()
        .then(() => navigator.clipboard?.writeText(JSON.stringify({ [CLIPBOARD_MARK]: clipboard })))
        .then(
          () => {
            clipboardSynced = !!navigator.clipboard;
          },
          () => {
            clipboardSynced = false;
          },
        );
      if (cut) removeSelected();
    },
    [elements, removeSelected, selectedIdx],
  );

  const pasteElements = useCallback(
    (source: SlideElement[]) => {
      if (!source.length) return;
      const made = source.map((element) => {
        const copy = cloneElement(element);
        // Pasted onto the same place as the original: a little offset, so both show.
        const b = boundsOf(copy);
        if (elements.some((e) => {
          const o = boundsOf(e);
          return o.x === b.x && o.y === b.y;
        })) translate(copy, 24, 24);
        delete copy.locked;
        return copy;
      });
      addElements(made, L("step.paste"));
    },
    [addElements, elements, L],
  );

  const orderSelected = useCallback(
    (how: "front" | "forward" | "backward" | "back") => {
      if (!selectedIdx.length) return;
      const keys = new Set(selectedIdx.map((i) => elementKey(elements[i], i)));
      changeElements(L("step.order"), (list) => {
        const picked = list.filter((element, i) => keys.has(elementKey(element, i)));
        const rest = list.filter((element, i) => !keys.has(elementKey(element, i)));
        let next: SlideElement[];
        if (how === "front") next = [...rest, ...picked];
        else if (how === "back") next = [...picked, ...rest];
        else {
          next = [...list];
          const indices = selectedIdx.slice().sort((a, b) => (how === "forward" ? b - a : a - b));
          for (const i of indices) {
            const to = how === "forward" ? i + 1 : i - 1;
            if (to < 0 || to >= next.length || keys.has(elementKey(next[to], to))) continue;
            [next[i], next[to]] = [next[to], next[i]];
          }
        }
        list.splice(0, list.length, ...next);
      });
    },
    [changeElements, elements, L, selectedIdx],
  );

  const stopWriting = useCallback(() => {
    setWriting((index) => {
      if (index >= 0) {
        // A text box left empty goes, as in any presentation program.
        const element = slides[current]?.elements?.[index];
        if (element?.type === "text" && !element.text?.trim()) {
          const gone = elementKey(element, index);
          queueMicrotask(() =>
            changeElements(
              L("step.type"),
              (list) => {
                const at = list.findIndex((e, i) => elementKey(e, i) === gone);
                const target = list[at];
                if (target?.type === "text" && !target.text?.trim()) list.splice(at, 1);
              },
              `eltext:${current}:${index}`,
            ),
          );
          setSelection((keys) => keys.filter((key) => key !== gone));
        }
      }
      return -1;
    });
  }, [changeElements, current, L, slides]);

  const elementEditing: ElementEditing = useMemo(
    () => ({
      writing,
      setText: (index, path, value) =>
        changeElements(
          L("step.type"),
          (list) => {
            let holder: unknown = list[index];
            for (const part of path.slice(0, -1)) holder = (holder as Record<string | number, unknown>)?.[part];
            if (holder && typeof holder === "object") (holder as Record<string | number, unknown>)[path[path.length - 1]] = value;
          },
          `eltext:${current}:${index}`,
        ),
      stopWriting,
      undo: editor.undo,
      redo: editor.redo,
    }),
    [changeElements, current, editor.redo, editor.undo, L, stopWriting, writing],
  );

  // --- inserting --------------------------------------------------------------------------------
  const insertText = () => {
    const spot = freeSpot(640, 120);
    addElements([{ type: "text", ...spot, w: 640, h: 120, text: "", size: 36 }], L("step.add_text"), true);
  };
  const insertShape = (shape: string) => {
    const size = shape === "arrow" || shape === "chevron" ? { w: 280, h: 160 } : shape === "callout" ? { w: 320, h: 200 } : { w: 220, h: 220 };
    const spot = freeSpot(size.w, size.h);
    addElements([{ type: "shape", shape, ...spot, ...size }], L("step.add_shape"));
  };
  const insertLine = (kind: "line" | "arrow" | "double" | "dashed") => {
    const spot = freeSpot(400, 0);
    const line: SlideElement = { type: "line", x1: spot.x, y1: spot.y, x2: spot.x + 400, y2: spot.y, width: 4 };
    if (kind === "arrow" || kind === "double") line.end = "arrow";
    if (kind === "double") line.start = "arrow";
    if (kind === "dashed") line.dash = "dash";
    addElements([line], L("step.add_line"));
  };
  const insertTable = () => {
    const spot = freeSpot(800, 240);
    const head = [1, 2, 3].map((n) => fill(L("sample.column"), { n }));
    addElements(
      [{ type: "table", ...spot, w: 800, h: 240, rows: [head, ["", "", ""], ["", "", ""]] }],
      L("step.add_table"),
    );
  };

  // --- charts ---------------------------------------------------------------------------------
  const [chartTarget, setChartTarget] = useState<ChartTarget | null>(null);
  const chartValue: ChartJson | null = useMemo(() => {
    if (!chartTarget) return null;
    if (chartTarget.kind === "slide") return slide?.chart ? validateChart(slide.chart).chart : null;
    if (chartTarget.kind === "element") {
      const element = elements[chartTarget.index];
      return element?.type === "chart" ? validateChart(element.chart).chart : null;
    }
    return null;
  }, [chartTarget, elements, slide]);

  // --- presenting --------------------------------------------------------------------------
  const [presenting, setPresenting] = useState<{ from: number; presenter: boolean } | null>(null);

  // --- following the agent ------------------------------------------------------------------
  // An agent's revision moves the stage to the slide it wrote, unless the person is busy
  // (a selection, a text in hand, a presentation): then the stage stays on the person's slide
  // (kept under them when slides were added before it) and the strip thumbnail plays the build.
  // Decided while rendering, so the reveal finds the stage already on the right slide.
  const remote = editor.remote ?? null;
  const [followed, setFollowed] = useState(remote?.seq ?? 0);
  const [agentSlide, setAgentSlide] = useState<number | null>(null);
  if (remote && remote.seq !== followed) {
    setFollowed(remote.seq);
    const diff = diffDecks(remote.previous, remote.next);
    const written = firstWritten(diff);
    const busy = presenting !== null || selection.length > 0 || writing >= 0 || activeField !== null;
    const kept = indexAfterRevision(diff, current, remote.next.slides?.length ?? 0);
    const target = written !== null && !busy ? written : kept;
    if (target !== selected) setSelected(target);
    setAgentSlide(written !== null && written !== target ? written : null);
  }
  useEffect(() => {
    if (agentSlide === null) return;
    const timer = window.setTimeout(() => setAgentSlide(null), 4_000);
    return () => window.clearTimeout(timer);
  }, [agentSlide, followed]);
  const liveAuthor = useNodeLive((state) => state.nodes[nodeId]?.author ?? null);
  const assistantName = useEventStore((state) => state.assistantName);

  // --- view -----------------------------------------------------------------------------------
  const [grid, setGrid] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [snap, setSnap] = useState(true);
  /* Panels stay closed until asked for, from the node bar: the deck opens as
   * its slides and nothing else (the maintainer's request, 2026-11-18). */
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [panel, setPanel] = useState<"find" | "keys" | null>(null);
  const notesBox = useRef<HTMLDivElement>(null);
  const { height: notesHeight } = useElementSize(notesBox);
  const [menu, setMenu] = useState<{ x: number; y: number; index: number | null } | null>(null);

  // --- pictures and text dropped or pasted onto the deck -----------------------------------------
  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, [contenteditable]")) return;
    const file = firstImage(event.clipboardData.files);
    if (file) {
      event.preventDefault();
      if (slide?.layout === "image" && !selectedIdx.length && slide.image === undefined) void placeImage(file, { kind: "replace", index: current });
      else void placeImage(file, { kind: "element-add" });
      return;
    }
    const text = event.clipboardData.getData("text/plain");
    if (!clipboardSynced && clipboard.length && !elementsFromText(text)) {
      // A copy the system clipboard did not take: the editor's own copy is the newest.
      event.preventDefault();
      pasteElements(clipboard);
      return;
    }
    const ours = text ? elementsFromText(text) : null;
    if (ours?.length) {
      event.preventDefault();
      pasteElements(ours);
      return;
    }
    if (text.trim() && event.currentTarget.contains(target)) {
      event.preventDefault();
      const spot = freeSpot(720, 160);
      addElements([{ type: "text", ...spot, w: 720, h: 160, text: text.trim().slice(0, 2000), size: 28 }], L("step.paste"));
      return;
    }
    if (clipboard.length) {
      event.preventDefault();
      pasteElements(clipboard);
    }
  };

  const [dropping, setDropping] = useState(false);
  const canvasBox = useRef<HTMLDivElement>(null);
  const onCanvasDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDropping(false);
    const file = firstImage(event.dataTransfer.files);
    if (!file) return;
    const host = canvasBox.current?.querySelector<HTMLElement>("[data-testid='slides-canvas-editor']");
    const rect = host?.getBoundingClientRect();
    const at = rect && rect.width ? { x: ((event.clientX - rect.left) / rect.width) * SLIDE_W, y: ((event.clientY - rect.top) / rect.height) * SLIDE_H } : undefined;
    void placeImage(file, { kind: "element-add", at });
  };

  // --- keys on the slide -----------------------------------------------------------------------------
  const onCanvasKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    // Only keys pressed on the slide itself: a menu of the format bar keeps its own.
    if (event.defaultPrevented || !target.closest("[data-testid='slides-canvas-editor']")) return;
    if (target.closest("input, textarea, [contenteditable], [role='textbox']")) return;
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key;
    const lower = key.toLowerCase();
    if (mod && lower === "a") {
      event.preventDefault();
      setSelection(elements.map((element, i) => elementKey(element, i)));
      return;
    }
    if (mod && lower === "v") return; // the paste event follows
    if (!selectedIdx.length) return;
    if (key === "Delete" || key === "Backspace") {
      event.preventDefault();
      removeSelected();
    } else if (key === "Escape") {
      event.preventDefault();
      setSelection([]);
    } else if (key === "Enter") {
      const index = selectedIdx[0];
      const element = elements[index];
      if (element && (hasText(element) || element.type === "table")) {
        event.preventDefault();
        setWriting(index);
      }
    } else if (key.startsWith("Arrow")) {
      event.preventDefault();
      const step = event.shiftKey ? 10 : 1;
      const dx = key === "ArrowLeft" ? -step : key === "ArrowRight" ? step : 0;
      const dy = key === "ArrowUp" ? -step : key === "ArrowDown" ? step : 0;
      changeElements(
        L("step.move_element"),
        (list) => {
          for (const i of selectedIdx) if (list[i] && !list[i].locked) translate(list[i], dx, dy);
        },
        `nudge:${current}:${selection.join(",")}`,
      );
    } else if (mod && lower === "d") {
      event.preventDefault();
      duplicateSelected();
    } else if (mod && lower === "c") {
      event.preventDefault();
      copySelected(false);
    } else if (mod && lower === "x") {
      event.preventDefault();
      copySelected(true);
    } else if (mod && (key === "]" || key === "}")) {
      event.preventDefault();
      orderSelected(event.shiftKey ? "front" : "forward");
    } else if (mod && (key === "[" || key === "{")) {
      event.preventDefault();
      orderSelected(event.shiftKey ? "back" : "backward");
    } else return;
    event.stopPropagation();
  };

  // --- the canvas's editing context (the layout's texts) ------------------------------------------------
  const editing: SlideEditing = useMemo(
    () => ({
      setText,
      splitItem: (path) => {
        const at = Number(path[path.length - 1]);
        const listPath = path.slice(0, -1);
        const list = listOf(slides[current], listPath);
        const max = listPath.length === 1 ? (slides[current]?.layout === "closing" ? LIMITS.closingBullets : LIMITS.bullets) : LIMITS.columnBullets;
        if (!list || list.length >= max) return;
        act(L("step.add_point"), (draft) => {
          listOf(draft.slides[current], listPath)?.splice(at + 1, 0, "");
        });
        setFocusRequest({ key: pathKey([...listPath, at + 1]), select: "end" });
      },
      removeItem: (path) => {
        const at = Number(path[path.length - 1]);
        const listPath = path.slice(0, -1);
        act(L("step.remove_point"), (draft) => {
          const s = draft.slides[current];
          const list = listOf(s, listPath);
          if (!list) return;
          list.splice(at, 1);
          if (!list.length && s) {
            if (listPath.length === 1) delete s.bullets;
            else {
              const column = s.columns?.[Number(listPath[1])];
              if (column) delete column.bullets;
            }
          }
        });
        if (at > 0) setFocusRequest({ key: pathKey([...listPath, at - 1]), select: "end" });
      },
      undo: editor.undo,
      redo: editor.redo,
      breakRun: editor.breakCoalesce,
      focusRequest,
      clearFocusRequest,
      placeholder: (field) => L(`placeholder.${field}`),
      onFieldFocus: (path) => {
        if (path === null) leaveField();
        else setSelection([]);
        setActiveField(path ? pathKey(path) : null);
      },
    }),
    [act, clearFocusRequest, current, editor.breakCoalesce, editor.redo, editor.undo, focusRequest, L, leaveField, setText, slides],
  );

  // --- deck settings -------------------------------------------------------------------------
  const setAccent = (next: string) => {
    act(L("step.accent"), (draft) => {
      if (next) draft.accent = next.toLowerCase();
      else delete draft.accent;
    });
  };
  const applyBackgroundToAll = () => {
    const background = slide?.background;
    if (!background) return;
    act(L("step.background_all"), (draft) => {
      draft.background = JSON.parse(JSON.stringify(background)) as Background;
      for (const s of draft.slides) delete s.background;
    });
  };

  const accentHex = deck.accent?.startsWith("#") ? deck.accent.toUpperCase() : "";

  /* The node bar at the bottom of the deck. With an element selected it is
   * the element's format; with none, what is added to a slide, the slide's
   * own settings, the deck's look and Present. Everything used now and then
   * is in its "⋯". */
  const formatting =
    slide && css ? (
      <FormatBar
        slide={slide}
        deck={deck}
        elements={elements}
        selected={selectedIdx}
        onElements={changeElements}
        onSlide={changeSlide}
        onLayout={(layout) => changeLayout(current, layout)}
        onPickBackground={() => pickImage({ kind: "background" })}
      />
    ) : null;
  const shapesPanel = (close: () => void, extra?: ReactNode) => (
    <div className="w-64 p-2">
      {extra}
      <p className="pb-2 text-xs text-muted-foreground">{L("insert.shape")}</p>
      <div className="grid grid-cols-5 gap-1">
        {SHAPES.map((shape) => (
          <button
            key={shape}
            type="button"
            aria-label={L(`shape.${shape}`)}
            title={L(`shape.${shape}`)}
            onClick={() => {
              close();
              insertShape(shape);
            }}
            className="grid h-10 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid={`slides-insert-shape-${shape}`}
          >
            <ShapeGlyph shape={shape} className="h-6 w-6" />
          </button>
        ))}
      </div>
      <p className="pb-2 pt-3 text-xs text-muted-foreground">{L("insert.line")}</p>
      <div className="grid grid-cols-2 gap-1">
        {(["line", "arrow", "double", "dashed"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => {
              close();
              insertLine(kind);
            }}
            className="flex h-8 items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid={`slides-insert-line-${kind}`}
          >
            {kind === "line" || kind === "dashed" ? <Minus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /> : <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
            <span className="truncate">{L(`insert.line_${kind}`)}</span>
          </button>
        ))}
      </div>
    </div>
  );

  /* With an element selected the bar is its format; inserting stays one
   * press away, every insert behind one "+". */
  const insertMore = (
    <Popover
      label={L("toolbar.insert")}
      trigger={
        <ToolbarButton
          label={L("toolbar.insert")}
          icon={<Plus aria-hidden />}
          trailing={<ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden />}
          data-testid="slides-insert-more"
        />
      }
    >
      {(close) =>
        shapesPanel(
          close,
          <div className="mb-3 grid grid-cols-4 gap-1">
            {(
              [
                ["text", <Type key="i" aria-hidden />, insertText, "slides-insert-text"],
                ["image", <ImagePlus key="i" aria-hidden />, () => pickImage({ kind: "element-add" }), "slides-insert-image"],
                ["table", <Table2 key="i" aria-hidden />, insertTable, "slides-insert-table"],
                ["chart", <BarChart3 key="i" aria-hidden />, () => setChartTarget({ kind: "new" }), "slides-insert-chart"],
              ] as const
            ).map(([kind, icon, run, testId]) => (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  close();
                  run();
                }}
                className="flex h-14 flex-col items-center justify-center gap-1 rounded-md text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-4 [&_svg]:w-4"
                data-testid={testId}
              >
                {icon}
                <span className="max-w-full truncate px-1">{L(`insert.${kind}`)}</span>
              </button>
            ))}
          </div>,
        )
      }
    </Popover>
  );
  const propertiesToggle = (
    <ToolbarButton
      label={t("nodes.editor.inspector")}
      icon={<SlidersHorizontal aria-hidden />}
      active={inspectorOpen}
      onClick={() => setInspectorOpen((open) => !open)}
      data-testid="slides-inspector-toggle"
    />
  );
  const toolbar =
    selectedIdx.length > 0 ? (
      <>
        {insertMore}
        <ToolbarSeparator />
        {formatting}
        <ToolbarSeparator />
        {propertiesToggle}
      </>
    ) : (
      <>
        <Popover
          label={L("add.label")}
          trigger={
            <ToolbarButton
              label={L("add.button")}
              icon={<Plus aria-hidden />}
              trailing={<ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden />}
              disabled={!canAddSlide(deck)}
              data-testid="slides-add"
            />
          }
        >
          {(close) => (
            <div className="w-72 p-1">
              <p className="px-1 pb-2 text-xs text-muted-foreground">{L("add.pick")}</p>
              <LayoutPicker
                onPick={(layout) => {
                  close();
                  addSlide(layout);
                }}
              />
            </div>
          )}
        </Popover>
        <ToolbarSeparator />
        <ToolbarButton label={L("insert.text")} icon={<Type aria-hidden />} onClick={insertText} disabled={!slide} data-testid="slides-insert-text" />
        <Popover label={L("insert.shape")} trigger={<ToolbarButton label={L("insert.shape")} icon={<Shapes aria-hidden />} data-testid="slides-insert-shape" />}>
          {(close) => shapesPanel(close)}
        </Popover>
        <ToolbarButton label={L("insert.image")} icon={<ImagePlus aria-hidden />} onClick={() => pickImage({ kind: "element-add" })} disabled={!slide} data-testid="slides-insert-image" />
        <ToolbarButton label={L("insert.table")} icon={<Table2 aria-hidden />} onClick={insertTable} disabled={!slide} data-testid="slides-insert-table" />
        <ToolbarButton label={L("insert.chart")} icon={<BarChart3 aria-hidden />} onClick={() => setChartTarget({ kind: "new" })} disabled={!slide} data-testid="slides-insert-chart" />
        <ToolbarSeparator />
        {formatting}
        <Popover
          label={L("design.label")}
          trigger={
            <ToolbarButton
              label={L("design.label")}
              icon={<Palette aria-hidden />}
              trailing={<ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden />}
              data-testid="slides-design-button"
            />
          }
        >
          {(close) => (
            <div className="flex flex-col">
              <DeckDesign deck={deck} onChange={act} onPickBackground={() => pickImage({ kind: "deck-background" })} close={close} />
              <div className="flex flex-col gap-2 border-t border-border p-2 pt-3" data-testid="slides-accent">
                <p className="text-xs font-medium text-muted-foreground">{L("accent.label")}</p>
                <div role="radiogroup" aria-label={L("accent.label")} className="flex flex-wrap items-center gap-1.5">
                  <AccentSwatch label={L("accent.default")} color={DEFAULT_ACCENT} on={!deck.accent} onPick={() => setAccent("")} />
                  {ACCENT_SWATCHES.map((name) => (
                    <AccentSwatch
                      key={name}
                      label={L(`accent.${name}`)}
                      color={SWATCH_COLORS[name]}
                      swatch={name}
                      on={deck.accent === name}
                      onPick={() => setAccent(name)}
                    />
                  ))}
                  <ColorPicker label={L("accent.custom")} value={accentHex} onChange={(hex) => setAccent(hex)} />
                </div>
              </div>
            </div>
          )}
        </Popover>
        <ToolbarSeparator />
        <ToolbarButton
          label={L("present.button")}
          icon={<Play aria-hidden />}
          disabled={!css}
          onClick={() => setPresenting({ from: current, presenter: false })}
          data-testid="slides-present-button"
        />
        {propertiesToggle}
        {imageBusy && <Loader2 className="mx-1 h-4 w-4 animate-spin text-muted-foreground" aria-label={L("image.working")} />}
      </>
    );

  const more = (
    <>
      {selectedIdx.length > 0 && (
        <>
          <MenuItem label={L("el.order.front")} icon={<BringToFront aria-hidden />} shortcut={`${MOD}⇧]`} onClick={() => orderSelected("front")} data-testid="slides-more-front" />
          <MenuItem label={L("el.order.back")} icon={<SendToBack aria-hidden />} shortcut={`${MOD}⇧[`} onClick={() => orderSelected("back")} />
          <MenuItem label={L("el.duplicate")} icon={<Copy aria-hidden />} shortcut={`${MOD}D`} onClick={duplicateSelected} />
          <MenuItem label={L("el.delete")} icon={<Trash2 aria-hidden />} destructive onClick={removeSelected} />
          <MenuDivider />
        </>
      )}
      <MenuItem label={L("action.duplicate")} icon={<Copy aria-hidden />} disabled={!canAddSlide(deck)} onClick={() => duplicateSlide(current)} data-testid="slides-duplicate" />
      <MenuItem label={L("action.delete")} icon={<Trash2 aria-hidden />} disabled={count <= 1} onClick={() => deleteSlide(current)} data-testid="slides-delete" />
      <MenuDivider />
      <MenuItem label={L("notes.toggle")} icon={<NotebookPen aria-hidden />} checked={notesOpen} onClick={() => setNotesOpen((open) => !open)} data-testid="slides-notes-toggle" />
      <MenuItem label={L("view.grid")} icon={<Grid3x3 aria-hidden />} checked={grid} onClick={() => setGrid((on) => !on)} data-testid="slides-grid" />
      <MenuItem label={L("view.snap")} icon={<Magnet aria-hidden />} checked={snap} onClick={() => setSnap((on) => !on)} data-testid="slides-snap" />
      <MenuItem label={L("view.zoom_in")} icon={<ZoomIn aria-hidden />} disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, Math.round((z + 0.25) * 100) / 100))} data-testid="slides-zoom-in" />
      <MenuItem label={L("view.zoom_out")} icon={<ZoomOut aria-hidden />} disabled={zoom <= 0.5} onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))} data-testid="slides-zoom-out" />
      <MenuItem label={L("view.zoom_fit")} icon={<Maximize aria-hidden />} disabled={zoom === 1} onClick={() => setZoom(1)} data-testid="slides-zoom" />
      <MenuItem label={L("find.label")} icon={<Search aria-hidden />} onClick={() => setPanel("find")} data-testid="slides-find" />
      <MenuItem label={L("keys.label")} icon={<Keyboard aria-hidden />} onClick={() => setPanel("keys")} data-testid="slides-keys" />
      <MenuDivider />
      <MenuItem label={L("present.from_start")} icon={<Play aria-hidden />} disabled={!css} onClick={() => setPresenting({ from: 0, presenter: false })} data-testid="slides-present-start" />
      <MenuItem label={L("present.presenter_view")} icon={<MonitorPlay aria-hidden />} disabled={!css} onClick={() => setPresenting({ from: current, presenter: true })} data-testid="slides-present-presenter-view" />
    </>
  );

  const side = inspectorOpen && slide ? (
    selectedIdx.length ? (
      <ElementInspector
        elements={elements}
        selected={selectedIdx}
        slideIndex={current}
        onChange={changeElements}
        onDuplicate={duplicateSelected}
        onDelete={removeSelected}
        onOrder={orderSelected}
        onReplaceImage={(index) => pickImage({ kind: "element-replace", index })}
        onEditChart={(index) => setChartTarget({ kind: "element", index })}
      />
    ) : (
      <div
        className="flex flex-col gap-4"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) leaveField();
        }}
      >
        <SlideInspector
          slide={slide}
          index={current}
          onText={setText}
          onChange={changeSlide}
          onLayout={(layout) => changeLayout(current, layout)}
          onEditChart={() => setChartTarget({ kind: "slide" })}
          onPickImage={() => pickImage({ kind: "replace", index: current })}
          onDropImage={(file) => void placeImage(file, { kind: "replace", index: current })}
          imageError={imageError}
          activeField={activeField}
        />
        <SlideDesign
          slide={slide}
          deck={deck}
          onChange={changeSlide}
          onPickBackground={() => pickImage({ kind: "background" })}
          onApplyBackgroundToAll={applyBackgroundToAll}
        />
      </div>
    )
  ) : null;

  const menuElement = menu?.index !== null && menu?.index !== undefined ? elements[menu.index] : null;

  return (
    <DeckLookProvider value={look}>
      <ElementFiguresProvider value={figures}>
        <EditorShell
          editor={editor}
          title={node.title}
          onDone={onDone}
          toolbar={toolbar}
          more={more}
          side={side}
          bodyClassName="flex overflow-hidden"
          barInset={notesOpen && slide ? notesHeight : 0}
        >
          <div className="flex min-h-0 min-w-0 flex-1" onPaste={onPaste} data-testid="slides-editor">
            <div className="w-[220px] shrink-0 border-r border-border bg-sidebar/40">
              {css ? (
                <SlideStrip
                  slides={slides}
                  selected={current}
                  css={css}
                  theme={theme}
                  accent={accent}
                  deckTitle={deckTitle}
                  sections={sections}
                  figureOf={figureOf}
                  onSelect={select}
                  onMove={moveTo}
                  onDuplicate={duplicateSlide}
                  onDelete={deleteSlide}
                  onToggleHidden={toggleHidden}
                  onAdd={addSlide}
                  onOpen={(index) => {
                    setSelected(index);
                    const field = slides[index] && firstField(slides[index]);
                    if (field) setFocusRequest({ key: field, select: "end" });
                  }}
                />
              ) : (
                <StripSkeleton count={count} />
              )}
            </div>
            <div
              ref={canvasBox}
              className={cn("relative flex min-h-0 min-w-0 flex-1 flex-col bg-secondary/30", dropping && "ring-2 ring-inset ring-accent")}
              onDragOver={(event) => {
                if (Array.from(event.dataTransfer.types).includes("Files")) {
                  event.preventDefault();
                  setDropping(true);
                }
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropping(false);
              }}
              onDrop={onCanvasDrop}
              onKeyDown={onCanvasKeyDown}
            >
              {panel && (
                <div
                  className="absolute right-3 top-3 z-30 rounded-lg border border-border bg-popover text-popover-foreground shadow-float"
                  data-node-editor-popover=""
                >
                  <button
                    type="button"
                    aria-label={L("panel.close")}
                    onClick={() => setPanel(null)}
                    className="absolute right-1.5 top-1.5 grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"
                    data-testid="slides-panel-close"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                  {panel === "find" ? (
                    <FindReplace
                      deck={deck}
                      onReplace={(query, replacement, matchCase) => act(L("step.replace"), (draft) => void replaceAll(draft, query, replacement, matchCase))}
                      onShow={(index) => setSelected(index)}
                    />
                  ) : (
                    <ShortcutList />
                  )}
                </div>
              )}
              {agentSlide !== null && liveAuthor && (
                <div
                  className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-full border px-2.5 py-0.5 text-[11.5px] leading-[18px]"
                  style={{
                    background: "hsl(var(--presence-pill-bg))",
                    color: "hsl(var(--presence-pill-ink))",
                    borderColor: "hsl(var(--presence-ink) / 0.16)",
                  }}
                  role="status"
                  data-testid="slides-agent-slide"
                >
                  {fill(L("live.working_on"), { name: authorName(liveAuthor, assistantName), n: agentSlide + 1 })}
                </div>
              )}
              <CanvasArea zoom={zoom}>
                {(width) =>
                  css && slide ? (
                    <ElementEditingProvider value={elementEditing}>
                      <SlideEditingProvider value={editing}>
                        <CanvasEditor
                          elements={elements}
                          width={width}
                          selection={selection}
                          onSelect={setSelection}
                          writing={writing}
                          onWrite={(index) => (index < 0 ? stopWriting() : setWriting(index))}
                          onChange={changeElements}
                          onOpenElement={(index) => {
                            const element = elements[index];
                            if (element?.type === "chart") setChartTarget({ kind: "element", index });
                            else if (element?.type === "image") pickImage({ kind: "element-replace", index });
                          }}
                          onContextMenu={(at, index) => setMenu({ ...at, index })}
                          labels={{ move: L("step.move_element"), resize: L("step.resize"), rotate: L("step.rotate"), nudge: L("step.move_element") }}
                          snap={snap}
                          grid={grid}
                        >
                          <SlideCanvas
                            css={css}
                            width={width}
                            theme={theme}
                            accent={accent}
                            editable
                            testId="slides-canvas"
                            slideIndex={current}
                            className="overflow-hidden rounded-lg shadow-[0_1px_3px_rgba(0,0,0,.12),0_8px_24px_-8px_rgba(0,0,0,.18)] ring-1 ring-border"
                          >
                            <SlideView
                              slide={slide}
                              index={current}
                              deckTitle={deckTitle}
                              section={sections[current] ?? 0}
                              figure={figureOf(current)}
                              label={fill(L("canvas.label"), { n: current + 1, total: count })}
                            />
                          </SlideCanvas>
                        </CanvasEditor>
                      </SlideEditingProvider>
                    </ElementEditingProvider>
                  ) : cssFailed ? (
                    <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground" role="alert">
                      <p>{L("canvas.failed")}</p>
                      <button type="button" className="text-accent underline-offset-4 hover:underline" onClick={() => setCssAttempt((n) => n + 1)}>
                        {L("canvas.retry")}
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="slides-loading">
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      {L("canvas.loading")}
                    </div>
                  )
                }
              </CanvasArea>
              {imageError && selectedIdx.length > 0 && (
                <p role="alert" className="px-4 pb-1 text-xs text-destructive">
                  {imageError}
                </p>
              )}
              {slide && notesOpen && (
                <div ref={notesBox} className="shrink-0 border-t border-border bg-background px-4 py-2" data-testid="slides-notes-panel">
                  <label htmlFor="slides-notes" className="mb-1 block text-xs text-muted-foreground">
                    {fill(L("notes.label"), { n: current + 1 })}
                  </label>
                  <textarea
                    id="slides-notes"
                    data-spec-undo=""
                    value={slide.notes ?? ""}
                    maxLength={LIMITS.noteChars}
                    placeholder={L("notes.placeholder")}
                    onChange={(event) => setText(["notes"], event.target.value)}
                    onBlur={leaveField}
                    rows={3}
                    className="block max-h-40 min-h-[64px] w-full resize-y rounded-md border border-border-strong bg-input px-3 py-2 text-sm leading-6 text-foreground placeholder:text-foreground-faint focus-visible:border-accent focus-visible:outline-none"
                    data-testid="slides-notes"
                  />
                </div>
              )}
            </div>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
            className="hidden"
            tabIndex={-1}
            aria-hidden
            data-testid="slides-image-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              const target = imageTarget.current;
              event.target.value = "";
              if (file && target) void placeImage(file, target);
            }}
          />
          <ChartEditor
            open={chartTarget !== null}
            value={chartValue}
            onCancel={() => setChartTarget(null)}
            onSave={(chart) => {
              const target = chartTarget;
              setChartTarget(null);
              if (!target) return;
              if (target.kind === "slide") {
                changeSlide(L("step.chart"), (s) => {
                  s.chart = chart as unknown as DeckChart;
                });
              } else if (target.kind === "element") {
                changeElements(L("step.chart"), (list) => {
                  const element = list[target.index];
                  if (element?.type === "chart") element.chart = chart as unknown as Record<string, unknown>;
                });
              } else {
                const spot = freeSpot(760, 440);
                addElements([{ type: "chart", ...spot, w: 760, h: 440, chart: chart as unknown as Record<string, unknown> }], L("step.add_chart"));
              }
            }}
          />
          {menu && (
            <ContextMenu at={menu} label={L("menu.label")} onClose={() => setMenu(null)}>
              {menuElement ? (
                <>
                  <MenuItem label={L("menu.cut")} icon={<Scissors aria-hidden />} shortcut={`${MOD}X`} onClick={() => copySelected(true)} />
                  <MenuItem label={L("menu.copy")} icon={<Copy aria-hidden />} shortcut={`${MOD}C`} onClick={() => copySelected(false)} data-testid="slides-menu-copy" />
                  <MenuItem label={L("menu.paste")} icon={<ClipboardPaste aria-hidden />} shortcut={`${MOD}V`} disabled={!clipboard.length} onClick={() => pasteElements(clipboard)} />
                  <MenuItem label={L("el.duplicate")} icon={<Copy aria-hidden />} shortcut={`${MOD}D`} onClick={duplicateSelected} data-testid="slides-menu-duplicate" />
                  <MenuSeparator />
                  <MenuItem label={L("el.order.front")} shortcut={`${MOD}⇧]`} onClick={() => orderSelected("front")} />
                  <MenuItem label={L("el.order.forward")} shortcut={`${MOD}]`} onClick={() => orderSelected("forward")} />
                  <MenuItem label={L("el.order.backward")} shortcut={`${MOD}[`} onClick={() => orderSelected("backward")} />
                  <MenuItem label={L("el.order.back")} shortcut={`${MOD}⇧[`} onClick={() => orderSelected("back")} />
                  <MenuSeparator />
                  <MenuItem
                    label={menuElement.locked ? L("el.unlock") : L("el.lock")}
                    icon={menuElement.locked ? <Unlock aria-hidden /> : <Lock aria-hidden />}
                    onClick={() =>
                      changeElements(menuElement.locked ? L("el.unlock") : L("el.lock"), (list) => {
                        for (const i of selectedIdx) {
                          if (!list[i]) continue;
                          if (menuElement.locked) delete list[i].locked;
                          else list[i].locked = true;
                        }
                      })
                    }
                  />
                  <MenuItem label={L("el.delete")} icon={<Trash2 aria-hidden />} destructive onClick={removeSelected} data-testid="slides-menu-delete" />
                </>
              ) : (
                <>
                  <MenuItem label={L("menu.paste")} icon={<ClipboardPaste aria-hidden />} shortcut={`${MOD}V`} disabled={!clipboard.length} onClick={() => pasteElements(clipboard)} />
                  <MenuItem label={L("menu.select_all")} shortcut={`${MOD}A`} disabled={!elements.length} onClick={() => setSelection(elements.map((element, i) => elementKey(element, i)))} />
                  <MenuSeparator />
                  <MenuItem label={L("insert.text")} icon={<Type aria-hidden />} onClick={insertText} />
                  <MenuItem label={L("insert.image")} icon={<ImagePlus aria-hidden />} onClick={() => pickImage({ kind: "element-add" })} />
                  <MenuItem label={L("slide.hide")} onClick={() => toggleHidden(current)} checked={!!slide?.hidden} />
                </>
              )}
            </ContextMenu>
          )}
          {presenting && css && (
            <PresentView
              slides={slides}
              start={presenting.from}
              css={css}
              theme={theme}
              accent={accent}
              deckTitle={deckTitle}
              sections={sections}
              figureOf={figureOf}
              transition={deck.transition}
              presenter={presenting.presenter}
              onClose={(at) => {
                setPresenting(null);
                setSelected(at);
              }}
            />
          )}
        </EditorShell>
      </ElementFiguresProvider>
    </DeckLookProvider>
  );
}

/** The list at `path` inside a slide (`["bullets"]`, `["columns", 1, "bullets"]`). */
function listOf(slide: Slide | undefined, path: FieldPath): string[] | undefined {
  let value: unknown = slide;
  for (const part of path) {
    if (value === null || typeof value !== "object") return undefined;
    value = (value as Record<string | number, unknown>)[part];
  }
  return Array.isArray(value) ? (value as string[]) : undefined;
}

/** The middle of the editor: the largest 16:9 box that fits, with a margin, times the zoom. */
function CanvasArea({ zoom = 1, children }: { zoom?: number; children: (width: number) => ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const read = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const pad = size.width < 640 ? 16 : 40;
  const fit = Math.max(160, Math.floor(Math.min(size.width - 2 * pad, ((size.height - 2 * pad) * 16) / 9)));
  const width = Math.round(fit * zoom);
  return (
    <div ref={box} className={cn("min-h-0 flex-1", zoom > 1 ? "overflow-auto" : "overflow-hidden")}>
      <div
        className="flex min-h-full items-center justify-center"
        style={{ minWidth: zoom > 1 ? width + 2 * pad : undefined, minHeight: zoom > 1 ? (width * 9) / 16 + 2 * pad : undefined }}
      >
        {size.width > 0 ? children(width) : children(960)}
      </div>
    </div>
  );
}

function StripSkeleton({ count }: { count: number }) {
  return (
    <div className="flex flex-col gap-2 p-3" aria-hidden>
      {Array.from({ length: Math.min(count, 8) }, (_, i) => (
        <div key={i} className="ml-7 aspect-video w-[168px] animate-pulse rounded-md bg-secondary" />
      ))}
    </div>
  );
}

function AccentSwatch({ label, color, swatch, on, onPick }: { label: string; color: string; swatch?: string; on: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      aria-label={label}
      title={label}
      onClick={onPick}
      data-testid={swatch ? `slides-accent-${swatch}` : "slides-accent-default"}
      className={cn(
        "h-7 w-7 rounded-full ring-offset-2 ring-offset-popover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on && "ring-2 ring-foreground",
      )}
      style={{ background: color }}
    />
  );
}

/** The kit's own accent and series colours (light theme), as the accents look on a slide. */
const DEFAULT_ACCENT = "#2A6FD0";
const SWATCH_COLORS: Record<string, string> = {
  blue: "#2A6FD0",
  orange: "#D4532E",
  green: "#158F6B",
  amber: "#A86B00",
  violet: "#5B46C2",
  pink: "#C23F86",
};


/** Find a text anywhere in the deck and replace it everywhere. */
function FindReplace({
  deck,
  onReplace,
  onShow,
}: {
  deck: Deck;
  onReplace: (query: string, replacement: string, matchCase: boolean) => void;
  onShow: (index: number) => void;
}) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [matchCase, setMatchCase] = useState(false);
  const found = useMemo(() => findInDeck(deck, query, matchCase), [deck, query, matchCase]);
  const field = "h-8 w-full rounded-md border border-border-strong bg-input px-2 text-sm focus-visible:border-accent focus-visible:outline-none";
  return (
    <div className="flex w-72 flex-col gap-2 p-2" data-testid="slides-find-panel">
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={L("find.find")} aria-label={L("find.find")} className={field} data-testid="slides-find-query" />
      <input value={replacement} onChange={(event) => setReplacement(event.target.value)} placeholder={L("find.replace_with")} aria-label={L("find.replace_with")} className={field} data-testid="slides-find-replacement" />
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input type="checkbox" checked={matchCase} onChange={(event) => setMatchCase(event.target.checked)} />
        {L("find.match_case")}
      </label>
      <p className="text-xs text-muted-foreground" data-testid="slides-find-count">
        {query ? fill(L("find.count"), { n: found.count, slides: found.slides.length }) : L("find.hint")}
      </p>
      {found.slides.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {found.slides.slice(0, 20).map((index) => (
            <button key={index} type="button" onClick={() => onShow(index)} className="h-6 min-w-6 rounded bg-secondary px-1.5 text-xs tabular-nums hover:bg-secondary/70">
              {index + 1}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        disabled={!found.count}
        onClick={() => onReplace(query, replacement, matchCase)}
        className="h-8 rounded-md bg-accent px-3 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-40"
        data-testid="slides-find-replace-all"
      >
        {L("find.replace_all")}
      </button>
    </div>
  );
}

/** The editor's keys at a glance. */
function ShortcutList() {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const rows: [string, string][] = [
    [L("keys.select"), L("keys.select_how")],
    [L("keys.write"), L("keys.write_how")],
    [L("keys.nudge"), "← ↑ → ↓"],
    [`${L("menu.copy")} · ${L("menu.cut")} · ${L("menu.paste")}`, `${MOD}C · ${MOD}X · ${MOD}V`],
    [L("el.duplicate"), `${MOD}D`],
    [L("el.delete"), "Del"],
    [L("menu.select_all"), `${MOD}A`],
    [`${L("el.order.forward")} · ${L("el.order.backward")}`, `${MOD}] · ${MOD}[`],
    [`${L("el.order.front")} · ${L("el.order.back")}`, `${MOD}⇧] · ${MOD}⇧[`],
    [L("keys.bold_italic"), `${MOD}B · ${MOD}I`],
    [L("keys.free_move"), "Alt"],
    [L("keys.undo"), `${MOD}Z · ${MOD}Y`],
    [L("keys.present"), "← → · N · P · B · W · Esc"],
  ];
  return (
    <div className="w-[22rem] p-2" data-testid="slides-keys-panel">
      <p className="mb-2 text-xs font-medium text-muted-foreground">{L("keys.label")}</p>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-xs">
        {rows.map(([what, keys]) => (
          <div key={what} className="contents">
            <dt className="text-foreground">{what}</dt>
            <dd className="text-right font-mono text-muted-foreground">{keys}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
