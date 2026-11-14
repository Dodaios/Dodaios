/**
 * The deck editor: the person's own way to make and change a deck.
 *
 * Layout: the slide strip on the left (thumbnails; add, duplicate, delete,
 * drag to reorder), the selected slide in the middle, large and written into
 * directly, its speaker notes under it, and the inspector on the right with
 * every field of the slide's layout. The toolbar adds slides, sets the
 * deck's theme and accent, and presents the deck.
 *
 * How a slide is drawn: by `SlideView`, in React, with the deck page's own
 * stylesheet (taken from the server's preview of the page, `deckPage.ts`).
 * That is the page's exact look at the speed of local rendering: typing,
 * switching slides and sixty thumbnails cost no server round trip. Only a
 * chart's figure comes from the server (its renderer is the page's), and
 * only when the chart changes.
 *
 * Every change goes through `useNodeSpecEditor`: each structural action is
 * one labelled undo step, typing in one field is one step per run, and the
 * deck is saved shortly after each change.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type ReactNode } from "react";
import { Copy, Loader2, Monitor, Moon, Palette, Play, Plus, Sun, Trash2 } from "lucide-react";

import { fill, useT } from "@/i18n";
import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

import { ChartEditor } from "../charts/ChartEditor";
import { validateChart, type ChartJson } from "../charts/chartModel";
import { ColorPicker, MenuItem, Popover, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { EditorShell } from "../EditorShell";
import { produce } from "../produce";
import type { NodeEditorProps } from "../types";
import { useNodeSpecEditor } from "../useNodeSpecEditor";
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
  type DeckTheme,
  type Layout,
  type Slide,
  type Translate,
} from "./deckModel";
import { loadDeckCss } from "./deckPage";
import { MOD } from "./keys";
import { firstImage, imageForSlide, ImageTooLargeError, ImageTypeError } from "./images";
import { clean } from "./inline";
import { LayoutPicker } from "./LayoutPicker";
import { PresentView } from "./PresentView";
import { SlideCanvas } from "./SlideCanvas";
import { SlideInspector } from "./SlideInspector";
import { SlideStrip } from "./SlideStrip";
import { pathKey, SlideEditingProvider, SlideView, type FieldPath, type SlideEditing } from "./SlideView";
import { useChartFigures } from "./useChartFigures";


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

/** The field a new slide's writing starts in. */
function firstField(slide: Slide): string | null {
  if (slide.layout === "quote") return "quote";
  if (slide.layout === "image" && !slide.title) return null;
  return "title";
}

/** Chapter numbers of the section slides (0 for the others), in one pass. */
function sectionNumbers(slides: readonly Slide[]): number[] {
  let count = 0;
  return slides.map((slide) => (slide.layout === "section" ? ++count : count));
}

type ImageTarget = { kind: "replace"; index: number } | { kind: "add"; at: number } | { kind: "layout"; index: number };

export default function SlidesEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const tr: Translate = useCallback((key, vars) => (vars ? fill(t(key), vars) : t(key)), [t]);
  const L = useCallback((key: string) => t(`nodes.editor.slides.${key}`), [t]);
  const nodeId = node.id ?? "";

  // The hook keeps whatever the stage handed over; the editor reads it as a deck once.
  const [start] = useState(() => ({ ...initial, spec: readDeck(initial.spec) }));
  const editor = useNodeSpecEditor<Deck>(nodeId, start);
  const deck = editor.spec;
  const slides = useMemo(() => deck.slides ?? [], [deck.slides]);
  const count = slides.length;

  const [selected, setSelected] = useState(0);
  const current = Math.max(0, Math.min(selected, count - 1));
  const slide = slides[current];

  // --- the page's stylesheet -------------------------------------------------------
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

  // --- following undo, redo and the assistant's revisions --------------------------------
  // A change the editor made itself selects what it means to; any other change
  // (undo, redo, a revision) selects the first slide it touched, so the person
  // sees what changed.
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
    let first = 0;
    while (first < Math.min(before.length, slides.length) && before[first] === slides[first]) first++;
    if (first < slides.length || slides.length !== before.length) setSelected(Math.min(first, slides.length - 1));
  }, [slides]);
  // A change `act` asked for lands in the very next render; one that changed
  // nothing must not mark the next (undo, revision) as the editor's own.
  useEffect(() => {
    ownFrom.current = null;
  });

  /** One labelled step on the deck, made by the editor itself. */
  const act = useCallback(
    (label: string, change: (draft: Deck) => void, coalesce?: string) => {
      // A change that changes nothing (leaving a field with nothing to tidy)
      // makes no render, so it must not mark the next change as the editor's.
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
        } else {
          insertSlide({ ...blankSlide("image", tr), image }, target.at, L("step.add_image_slide"));
        }
      } catch (error) {
        setImageError(
          error instanceof ImageTooLargeError ? L("image.too_large") : error instanceof ImageTypeError ? L("image.wrong_type") : L("image.failed"),
        );
      } finally {
        setImageBusy(false);
      }
    },
    [act, insertSlide, L, tr],
  );

  const addSlide = useCallback(
    (layout: Layout) => {
      if (layout === "image") {
        // An image slide without its picture would not survive a save: the picture comes first.
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
      act(L("step.duplicate"), (draft) => {
        draft.slides.splice(index + 1, 0, copySlide(source));
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

  const moveTo = useCallback(
    (from: number, to: number) => {
      act(L("step.move"), (draft) => moveSlide(draft, from, to));
      // The slide being moved is the one the person handles: it is selected where it lands.
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

  const changeSlide = useCallback(
    (label: string, change: (s: Slide) => void) => {
      act(label, (draft) => {
        const s = draft.slides[current];
        if (s) change(s);
      });
    },
    [act, current],
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

  // --- the canvas's editing context ------------------------------------------------------
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
          // The last point gone: the list goes with it, as the page has it.
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
        setActiveField(path ? pathKey(path) : null);
      },
    }),
    [act, clearFocusRequest, current, editor.breakCoalesce, editor.redo, editor.undo, focusRequest, L, leaveField, setText, slides],
  );

  // --- charts -------------------------------------------------------------------------------
  const [chartOpen, setChartOpen] = useState(false);
  const chartValue: ChartJson | null = slide?.chart ? validateChart(slide.chart).chart : null;

  // --- presenting --------------------------------------------------------------------------
  const [presenting, setPresenting] = useState(false);

  // --- pictures dropped or pasted onto the deck -----------------------------------------------
  const takeImageFile = useCallback(
    (file: File) => {
      if (slide?.layout === "image") void placeImage(file, { kind: "replace", index: current });
      else void placeImage(file, { kind: "add", at: current + 1 });
    },
    [current, placeImage, slide],
  );

  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, [contenteditable]")) return;
    const file = firstImage(event.clipboardData.files);
    if (!file) return;
    event.preventDefault();
    takeImageFile(file);
  };

  const [dropping, setDropping] = useState(false);
  const onCanvasDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDropping(false);
    const file = firstImage(event.dataTransfer.files);
    if (file) takeImageFile(file);
  };

  // --- deck settings -------------------------------------------------------------------------
  const setTheme = (next: DeckTheme) => {
    if (next !== deck.theme) act(L("step.theme"), (draft) => void (draft.theme = next));
  };
  const setAccent = (next: string) => {
    act(L("step.accent"), (draft) => {
      if (next) draft.accent = next.toLowerCase();
      else delete draft.accent;
    });
  };

  const themeIcon = deck.theme === "dark" ? <Moon aria-hidden /> : deck.theme === "light" ? <Sun aria-hidden /> : <Monitor aria-hidden />;
  const accentHex = deck.accent?.startsWith("#") ? deck.accent.toUpperCase() : "";

  const toolbar = (
    <>
      <ToolbarGroup label={L("toolbar.slides")}>
        <Popover
          label={L("add.label")}
          trigger={
            <ToolbarButton
              label={L("add.button")}
              icon={<Plus aria-hidden />}
              showLabel
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
        <ToolbarButton
          label={L("action.duplicate")}
          icon={<Copy aria-hidden />}
          shortcut={`${MOD}D`}
          disabled={!canAddSlide(deck)}
          onClick={() => duplicateSlide(current)}
          data-testid="slides-duplicate"
        />
        <ToolbarButton
          label={L("action.delete")}
          icon={<Trash2 aria-hidden />}
          disabled={count <= 1}
          onClick={() => deleteSlide(current)}
          data-testid="slides-delete"
        />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={L("toolbar.look")}>
        <Popover
          role="menu"
          label={L("theme.label")}
          trigger={<ToolbarButton label={L("theme.label")} icon={themeIcon} data-testid="slides-theme" />}
        >
          {(close) => (
            <div className="w-48 p-1">
              {(["auto", "light", "dark"] as const).map((value) => (
                <MenuItem
                  key={value}
                  label={L(`theme.${value}`)}
                  checked={deck.theme === value}
                  onClick={() => {
                    close();
                    setTheme(value);
                  }}
                  data-testid={`slides-theme-${value}`}
                />
              ))}
            </div>
          )}
        </Popover>
        <Popover
          label={L("accent.label")}
          trigger={
            <ToolbarButton
              label={L("accent.label")}
              icon={
                <span className="relative inline-flex">
                  <Palette aria-hidden />
                </span>
              }
              data-testid="slides-accent"
            />
          }
        >
          {(close) => (
            <div className="flex w-60 flex-col gap-3 p-2">
              <div role="radiogroup" aria-label={L("accent.label")} className="flex flex-wrap gap-1.5">
                <AccentSwatch
                  label={L("accent.default")}
                  color={DEFAULT_ACCENT}
                  on={!deck.accent}
                  onPick={() => {
                    close();
                    setAccent("");
                  }}
                />
                {ACCENT_SWATCHES.map((name) => (
                  <AccentSwatch
                    key={name}
                    label={L(`accent.${name}`)}
                    color={SWATCH_COLORS[name]}
                    swatch={name}
                    on={deck.accent === name}
                    onPick={() => {
                      close();
                      setAccent(name);
                    }}
                  />
                ))}
              </div>
              <ColorPicker label={L("accent.custom")} value={accentHex} onChange={(hex) => setAccent(hex)} />
            </div>
          )}
        </Popover>
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarButton
        label={L("present.button")}
        icon={<Play aria-hidden />}
        showLabel
        disabled={!css}
        onClick={() => setPresenting(true)}
        data-testid="slides-present-button"
      />
      {imageBusy && <Loader2 className="ml-1 h-4 w-4 animate-spin text-muted-foreground" aria-label={L("image.working")} />}
    </>
  );

  const side = slide ? (
    <div
      onBlur={(event) => {
        // Leaving a field of the inspector drops what was emptied, as on the canvas.
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) leaveField();
      }}
    >
      <SlideInspector
        slide={slide}
        index={current}
        onText={setText}
        onChange={changeSlide}
        onLayout={(layout) => changeLayout(current, layout)}
        onEditChart={() => setChartOpen(true)}
        onPickImage={() => pickImage({ kind: "replace", index: current })}
        onDropImage={(file) => void placeImage(file, { kind: "replace", index: current })}
        imageError={imageError}
        activeField={activeField}
      />
    </div>
  ) : null;

  return (
    <EditorShell editor={editor} title={node.title} onDone={onDone} toolbar={toolbar} side={side} bodyClassName="flex overflow-hidden">
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
          className={cn("flex min-h-0 min-w-0 flex-1 flex-col bg-secondary/30", dropping && "ring-2 ring-inset ring-accent")}
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
        >
          <CanvasArea>
            {(width) =>
              css && slide ? (
                <SlideEditingProvider value={editing}>
                  <SlideCanvas
                    css={css}
                    width={width}
                    theme={theme}
                    accent={accent}
                    editable
                    testId="slides-canvas"
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
                </SlideEditingProvider>
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
          {slide && (
            <div className="shrink-0 border-t border-border bg-background px-4 py-2">
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
        open={chartOpen}
        value={chartValue}
        onCancel={() => setChartOpen(false)}
        onSave={(chart) => {
          setChartOpen(false);
          changeSlide(L("step.chart"), (s) => {
            s.chart = chart as unknown as DeckChart;
          });
        }}
      />
      {presenting && css && (
        <PresentView
          slides={slides}
          start={current}
          css={css}
          theme={theme}
          accent={accent}
          deckTitle={deckTitle}
          sections={sections}
          figureOf={figureOf}
          onClose={(at) => {
            setPresenting(false);
            setSelected(at);
          }}
        />
      )}
    </EditorShell>
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

/** The middle of the editor: the largest 16:9 box that fits, with a margin. */
function CanvasArea({ children }: { children: (width: number) => ReactNode }) {
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
  const pad = size.width < 640 ? 16 : 32;
  const width = Math.max(160, Math.floor(Math.min(size.width - 2 * pad, ((size.height - 2 * pad) * 16) / 9)));
  return (
    <div ref={box} className="flex min-h-0 flex-1 items-center justify-center overflow-hidden">
      {size.width > 0 ? children(width) : children(960)}
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
