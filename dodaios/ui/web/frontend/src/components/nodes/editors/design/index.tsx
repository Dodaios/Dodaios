/**
 * The Visuals (``design``) editor.
 *
 * A design is freely written markup on the kit's tokens, so the editor works
 * on that markup's own elements, in three places that always agree:
 *
 * * the PREVIEW in the middle is the design's real page, drawn by the server
 *   from the unsaved spec (`useNodePreview`). A click selects a block there,
 *   a double-click types into a text in place; a small script in the frame
 *   (`picker.ts`) does that part and reports back;
 * * the LAYERS list on the left is the same blocks as a tree: select, move,
 *   drag, duplicate, delete, all from the keyboard too;
 * * the INSPECTOR on the right edits the selected block (its words, link,
 *   picture, colours, size, weight, alignment, spacing) or, with nothing
 *   selected, the page (scrolling page or artboard and its size, ground,
 *   accent, theme, the style sheet).
 *
 * Every change is one step of the shared hook (`useNodeSpecEditor`): undo and
 * redo, saving, and a revision the assistant makes meanwhile work as in every
 * other editor. A change parses the markup, edits the parsed copy and writes
 * it out again (`designDoc.editMarkup`); the server cleans it as it always
 * has when it is saved.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { ArrowDown, ArrowUp, Copy, Loader2, Plus, Trash2 } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { EditorShell } from "../EditorShell";
import { MenuItem, Popover, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { PreviewFrame, useNodePreview } from "../PreviewFrame";
import type { NodeEditorProps } from "../types";
import { hasOwnUndo, shortcutOf, useNodeSpecEditor } from "../useNodeSpecEditor";
import { ElementInspector, PageInspector, type ElementChange, type PageChange } from "./DesignInspector";
import { BLOCKS, imageMarkup, type BlockId, type BlockWords } from "./designBlocks";
import {
  duplicateElement,
  editMarkup,
  elementAt,
  insertBlock,
  layersOf,
  moveElement,
  moveElementTo,
  parseDesign,
  readDesignSpec,
  removeElement,
  samePath,
  setInlineMarkup,
  type DesignSpec,
} from "./designDoc";
import { ImageTooLargeError, ImageTypeError, embedImage } from "./embedImage";
import { LayersPanel } from "./LayersPanel";
import { PICKER_SOURCE, pickerScript, readPickerMessage } from "./picker";

/** The outline the preview draws around the hovered and the selected block. */
const SELECTION_COLOUR = "#2F7CF6";
const PICKER = pickerScript(SELECTION_COLOUR);
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = IS_MAC ? "⌘" : "Ctrl+";

/** A key press as the editor's shortcuts read it (from the app, or forwarded by the preview). */
interface KeyLike {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

export default function DesignEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const nodeId = node.id ?? "";
  const start = useMemo(() => ({ ...initial, spec: readDesignSpec(initial.spec) }), [initial]);
  const prepare = useCallback(
    (spec: DesignSpec) => (spec.html.trim() ? spec : { error: t("nodes.editor.design.empty") }),
    [t],
  );
  const editor = useNodeSpecEditor<DesignSpec>(nodeId, start, { prepare });
  const { spec, apply } = editor;

  // A read-only parse of the markup for the layers and the inspector; every
  // change parses its own copy inside `apply`.
  const root = useMemo(() => parseDesign(spec.html), [spec.html]);
  const layers = useMemo(() => layersOf(root), [root]);
  const [selected, setSelected] = useState<number[] | null>(null);
  const element = selected ? elementAt(root, selected) : null;
  const [panel, setPanel] = useState<"block" | "page">("page");
  const [imageError, setImageError] = useState("");

  // An undo can take the selected block away: then nothing is selected.
  useEffect(() => {
    if (selected && !element) setSelected(null);
  }, [selected, element]);

  const select = useCallback((path: number[] | null) => {
    setSelected(path);
    setImageError("");
    if (path) setPanel("block");
  }, []);

  /* ---------------------------------------------------------- changes */

  /** Change the markup as one undo step; returns what `change` returned. */
  const changeMarkup = useCallback(
    <T,>(label: string, change: (root: HTMLElement) => T, coalesce?: string): T | undefined => {
      let result: T | undefined;
      apply(
        (draft) => {
          const out = editMarkup(draft.html, change);
          result = out.result;
          if (out.html !== draft.html) draft.html = out.html;
        },
        { label, coalesce },
      );
      return result;
    },
    [apply],
  );

  const changeElement: ElementChange = useCallback(
    (label, change, coalesce) => {
      if (!selected) return;
      const path = selected;
      changeMarkup(
        label,
        (doc) => {
          const target = elementAt(doc, path);
          if (target) change(target);
        },
        coalesce,
      );
    },
    [changeMarkup, selected],
  );

  const changePage: PageChange = useCallback(
    (label, change, coalesce) => apply((draft) => void change(draft), { label, coalesce }),
    [apply],
  );

  const duplicate = useCallback(() => {
    if (!selected) return;
    const path = selected;
    const next = changeMarkup(t("nodes.editor.design.history.duplicate"), (doc) => duplicateElement(doc, path));
    if (next) select(next);
  }, [changeMarkup, select, selected, t]);

  const remove = useCallback(() => {
    if (!selected) return;
    const path = selected;
    const next = changeMarkup(t("nodes.editor.design.history.delete"), (doc) => removeElement(doc, path));
    select(next ?? null);
    if (!next) setPanel("page");
  }, [changeMarkup, select, selected, t]);

  const move = useCallback(
    (step: -1 | 1) => {
      if (!selected) return;
      const path = selected;
      const next = changeMarkup(t("nodes.editor.design.history.move"), (doc) => moveElement(doc, path, step));
      if (next) select(next);
    },
    [changeMarkup, select, selected, t],
  );

  const drop = useCallback(
    (from: number[], to: number[], where: "before" | "after" | "inside") => {
      const next = changeMarkup(t("nodes.editor.design.history.move"), (doc) => moveElementTo(doc, from, to, where));
      if (next) select(next);
    },
    [changeMarkup, select, t],
  );

  const words: BlockWords = useMemo(
    () => ({
      heading: t("nodes.editor.design.block_text.heading"),
      text: t("nodes.editor.design.block_text.text"),
      button: t("nodes.editor.design.block_text.button"),
      item: t("nodes.editor.design.block_text.item"),
      quote: t("nodes.editor.design.block_text.quote"),
      label: t("nodes.editor.design.block_text.label"),
      value: t("nodes.editor.design.block_text.value"),
    }),
    [t],
  );

  const addBlock = useCallback(
    (markup: string) => {
      const at = selected;
      const next = changeMarkup(t("nodes.editor.design.history.add"), (doc) => insertBlock(doc, at, markup));
      if (next) select(next);
    },
    [changeMarkup, select, selected, t],
  );

  /* A picture is embedded in the spec, scaled down to the size a design may
   * carry. `replaceOn` replaces the src of that image; null adds a block. */
  const imageInput = useRef<HTMLInputElement>(null);
  const [embedding, setEmbedding] = useState(false);
  const takeImage = useCallback(
    async (file: File, replaceOn: number[] | null) => {
      setImageError("");
      setEmbedding(true);
      try {
        const src = await embedImage(file);
        const alt = file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ");
        if (replaceOn) {
          const path = replaceOn;
          changeMarkup(t("nodes.editor.design.history.image"), (doc) => elementAt(doc, path)?.setAttribute("src", src));
        } else {
          addBlock(imageMarkup(src, alt));
        }
      } catch (error) {
        setImageError(
          t(
            error instanceof ImageTypeError
              ? "nodes.editor.design.image.wrong_type"
              : error instanceof ImageTooLargeError
                ? "nodes.editor.design.image.too_large"
                : "nodes.editor.design.image.failed",
          ),
        );
        if (!replaceOn) setPanel(selected ? "block" : "page");
      } finally {
        setEmbedding(false);
      }
    },
    [addBlock, changeMarkup, selected, t],
  );

  const pickBlock = useCallback(
    (id: BlockId) => {
      if (id === "image") {
        imageInput.current?.click();
        return;
      }
      const template = BLOCKS.find((block) => block.id === id);
      if (template) addBlock(template.markup(words));
    },
    [addBlock, words],
  );

  /* ------------------------------------------------------------- keys */

  /** The editor's shortcuts on a block. Returns true when the key was one. */
  const onShortcut = useCallback(
    (event: KeyLike): boolean => {
      const wanted = shortcutOf(event);
      if (wanted) {
        if (wanted === "undo") editor.undo();
        else editor.redo();
        return true;
      }
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "d") {
        duplicate();
        return true;
      }
      if (!selected) return false;
      if (event.key === "Delete" || event.key === "Backspace") {
        remove();
        return true;
      }
      if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        move(event.key === "ArrowUp" ? -1 : 1);
        return true;
      }
      if (event.key === "Escape") {
        select(selected.length > 1 ? selected.slice(0, -1) : null);
        if (selected.length <= 1) setPanel("page");
        return true;
      }
      return false;
    },
    [duplicate, editor, move, remove, select, selected],
  );

  const onBodyKey = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.defaultPrevented || hasOwnUndo(event.target)) return;
    // Undo and redo are the shell's; everything else here is the editor's.
    if (shortcutOf(event)) return;
    if (onShortcut(event)) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const onRowKey = (event: ReactKeyboardEvent<HTMLElement>, path: number[]) => {
    if (!samePath(path, selected)) return false;
    if (event.key === "Enter") {
      event.preventDefault();
      setPanel("block");
      // The words of a text are typed in the inspector's field.
      window.requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-testid="design-text"]')?.focus());
      return true;
    }
    return false;
  };

  /* ---------------------------------------------------------- preview */

  const preview = useNodePreview(nodeId, spec, { delayMs: 250 });
  const stage = useRef<HTMLDivElement>(null);
  const scrollY = useRef(0);
  const post = useCallback((message: Record<string, unknown>) => {
    const frame = stage.current?.querySelector("iframe");
    frame?.contentWindow?.postMessage({ ...message, source: PICKER_SOURCE }, "*");
  }, []);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const onFrameMessage = useCallback(
    (data: unknown) => {
      const message = readPickerMessage(data);
      if (!message) return;
      switch (message.type) {
        case "ready":
          // A redrawn page comes back where the person was.
          post({ type: "state", selected: selectedRef.current, scrollY: scrollY.current });
          break;
        case "select":
          select(message.path);
          if (!message.path) setPanel("page");
          break;
        case "text": {
          // Only inline marks are kept (`setInlineMarkup`): typing in the
          // preview changes the words, never the structure.
          const { path, html } = message;
          changeMarkup(t("nodes.editor.design.history.text"), (doc) => {
            const target = elementAt(doc, path);
            if (target) setInlineMarkup(target, html);
          });
          break;
        }
        case "scroll":
          scrollY.current = message.y;
          break;
        case "key":
          onShortcut({
            key: message.key,
            metaKey: message.meta,
            ctrlKey: message.ctrl,
            shiftKey: message.shift,
            altKey: message.alt,
          });
          break;
        default:
      }
    },
    [changeMarkup, onShortcut, post, select, t],
  );

  // The layers list and the inspector select in the preview too.
  useEffect(() => {
    post({ type: "select", path: selected });
  }, [post, selected]);

  /* ---------------------------------------------------------- toolbar */

  const toolbar = (
    <>
      <ToolbarGroup label={t("nodes.editor.design.add_group")}>
        <Popover
          label={t("nodes.editor.design.add")}
          role="menu"
          trigger={
            <ToolbarButton
              label={t("nodes.editor.design.add")}
              icon={embedding ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
              showLabel
              data-testid="design-add"
            />
          }
        >
          {(close) => (
            <div className="grid w-64 grid-cols-1 p-1" data-testid="design-add-menu">
              {BLOCKS.map((block) => {
                const Icon = block.icon;
                return (
                  <MenuItem
                    key={block.id}
                    label={t(`nodes.editor.design.block.${block.id}`)}
                    icon={<Icon aria-hidden />}
                    onClick={() => {
                      close();
                      pickBlock(block.id);
                    }}
                    data-testid={`design-add-${block.id}`}
                  />
                );
              })}
            </div>
          )}
        </Popover>
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.design.block_actions")}>
        <ToolbarButton
          label={t("nodes.editor.design.move_up")}
          icon={<ArrowUp aria-hidden />}
          shortcut="⌥↑"
          disabled={!selected}
          onClick={() => move(-1)}
        />
        <ToolbarButton
          label={t("nodes.editor.design.move_down")}
          icon={<ArrowDown aria-hidden />}
          shortcut="⌥↓"
          disabled={!selected}
          onClick={() => move(1)}
        />
        <ToolbarButton
          label={t("nodes.editor.design.duplicate")}
          icon={<Copy aria-hidden />}
          shortcut={`${MOD}D`}
          disabled={!selected}
          onClick={duplicate}
          data-testid="design-duplicate"
        />
        <ToolbarButton
          label={t("nodes.editor.design.delete")}
          icon={<Trash2 aria-hidden />}
          shortcut="⌫"
          disabled={!selected}
          onClick={remove}
          data-testid="design-delete"
        />
      </ToolbarGroup>
    </>
  );

  const side = (
    <div className="flex flex-col gap-4">
      <div role="tablist" aria-label={t("nodes.editor.inspector")} className="grid grid-cols-2 gap-1 rounded-md bg-secondary p-0.5">
        {(["block", "page"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={panel === tab}
            disabled={tab === "block" && !element}
            onClick={() => setPanel(tab)}
            className={cn(
              "h-7 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40",
              panel === tab ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
            )}
            data-testid={`design-tab-${tab}`}
          >
            {t(`nodes.editor.design.tab.${tab}`)}
          </button>
        ))}
      </div>
      {panel === "block" && element && selected ? (
        <ElementInspector
          element={element}
          pathKey={selected.join(".")}
          onChange={changeElement}
          onDuplicate={duplicate}
          onRemove={remove}
          onMove={move}
          onSelectParent={selected.length > 1 ? () => select(selected.slice(0, -1)) : null}
          onReplaceImage={(file) => void takeImage(file, selected)}
          imageError={imageError}
        />
      ) : (
        <>
          {imageError && (
            <p role="alert" className="text-sm text-destructive">
              {imageError}
            </p>
          )}
          <PageInspector spec={spec} onChange={changePage} />
        </>
      )}
    </div>
  );

  return (
    <EditorShell editor={editor} title={node.title} onDone={onDone} toolbar={toolbar} side={side} bodyClassName="overflow-hidden">
      <input
        ref={imageInput}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) void takeImage(picked, null);
          event.target.value = "";
        }}
        data-testid="design-image-input"
      />
      <div className="flex h-full min-h-0" onKeyDown={onBodyKey}>
        <nav
          aria-label={t("nodes.editor.design.layers.label")}
          className="w-60 shrink-0 overflow-y-auto border-r border-border bg-sidebar"
        >
          <p className="px-3 pb-1 pt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t("nodes.editor.design.layers.title")}
          </p>
          <LayersPanel layers={layers} selected={selected} onSelect={select} onRowKey={onRowKey} onDrop={drop} />
        </nav>
        <div ref={stage} className="relative min-w-0 flex-1 bg-secondary/40">
          <PreviewFrame
            html={preview.html}
            title={t("nodes.editor.design.preview").replace("{0}", node.title)}
            script={PICKER}
            onMessage={onFrameMessage}
            className="h-full w-full border-0"
          />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center p-3">
            {preview.error ? (
              <p role="status" className="pointer-events-auto max-w-xl rounded-md bg-destructive/90 px-3 py-1.5 text-sm text-destructive-foreground shadow">
                {preview.error}
              </p>
            ) : (
              <p className="rounded-md bg-background/85 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
                {t("nodes.editor.design.preview_hint")}
              </p>
            )}
          </div>
        </div>
      </div>
    </EditorShell>
  );
}
