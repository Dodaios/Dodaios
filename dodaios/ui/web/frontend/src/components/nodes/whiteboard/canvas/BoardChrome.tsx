/**
 * The board's own controls, drawn over the canvas: the tool dock at the
 * bottom, the inspector for the selection on the right, the menu, undo and
 * the zoom in the corners, and the line that says the assistant is drawing.
 *
 * The editor's own toolbars are hidden (`whiteboard.css`); these replace them
 * with one calm set of floating panels in the app's own look. They read the
 * editor's state through `ChromeState` and act on it through the editor's API
 * (tools, styles) or its keyboard shortcuts (commands), never by reaching
 * into its internals.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  ArrowUpRight,
  BringToFront,
  Circle,
  Copy,
  Diamond,
  Download,
  Eraser,
  FileDown,
  FolderOpen,
  Frame,
  Grid3x3,
  Group,
  Hand,
  ImagePlus,
  Keyboard,
  Lasso,
  Library,
  Lock,
  LockOpen,
  Maximize,
  Menu,
  Minus,
  MousePointer2,
  MoreHorizontal,
  PaintBucket,
  Pencil,
  Redo2,
  Search,
  SendToBack,
  Shapes,
  Square,
  StickyNote,
  Trash2,
  Type,
  Undo2,
  Ungroup,
  Workflow,
} from "lucide-react";

import { QuickTooltip } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import type { StylePatch } from "./styleOps";

/* ------------------------------------------------------------------------ */
/* State the chrome reads                                                    */
/* ------------------------------------------------------------------------ */

/** What the controls show, taken from the editor on each change. */
export interface ChromeState {
  tool: string;
  zoom: number;
  /** Types of the selected elements (empty: nothing selected). */
  selected: string[];
  /** Values the inspector shows: the first selected element's, or the defaults. */
  sample: Record<string, unknown>;
  /** A text is being typed: the inspector keeps to text. */
  editingText: boolean;
  hasElements: boolean;
  gridOn: boolean;
  /** The tool stays after drawing (the editor's tool lock, Q). */
  toolLocked: boolean;
}

export const TOOLS_THAT_DRAW = new Set(["rectangle", "ellipse", "diamond", "arrow", "line", "freedraw", "text"]);

/* ------------------------------------------------------------------------ */
/* Small pieces                                                              */
/* ------------------------------------------------------------------------ */

function Panel({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cn(
        "pointer-events-auto rounded-xl border border-border bg-popover/95 text-popover-foreground shadow-float backdrop-blur-md",
        className,
      )}
    >
      {children}
    </div>
  );
}

function IconButton({
  label,
  shortcut,
  active,
  onClick,
  children,
  side = "top",
  testId,
  disabled,
}: {
  label: string;
  shortcut?: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  side?: "top" | "bottom" | "right";
  testId?: string;
  disabled?: boolean;
}) {
  return (
    <QuickTooltip
      side={side}
      content={
        <span className="inline-flex items-center gap-2">
          {label}
          {shortcut ? <kbd className="rounded bg-secondary px-1 font-mono text-[11px] text-muted-foreground">{shortcut}</kbd> : null}
        </span>
      }
    >
      <button
        type="button"
        aria-label={label}
        aria-pressed={active}
        data-testid={testId}
        disabled={disabled}
        onClick={onClick}
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary transition-colors duration-[var(--motion-fast)]",
          "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "disabled:pointer-events-none disabled:opacity-40",
          active && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground",
        )}
      >
        {children}
      </button>
    </QuickTooltip>
  );
}

function Divider({ vertical = true }: { vertical?: boolean }) {
  return <span aria-hidden className={vertical ? "mx-1 h-6 w-px bg-border" : "my-1 h-px w-full bg-border"} />;
}

/** Close a popover when the pointer goes down outside it or Escape is pressed. */
function useDismiss(open: boolean, close: () => void, ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, close, ref]);
}

/* ------------------------------------------------------------------------ */
/* Tool dock                                                                 */
/* ------------------------------------------------------------------------ */

export type DockTool =
  | "selection"
  | "hand"
  | "frame"
  | "rectangle"
  | "ellipse"
  | "diamond"
  | "arrow"
  | "line"
  | "freedraw"
  | "text"
  | "image"
  | "eraser"
  | "laser"
  /* The board's own tools (the editor does not ship them). */
  | "lasso"
  | "bucket"
  | "shape";

/** The laser pointer: a pen-like stick with a glowing tip. */
function LaserIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" className={className} aria-hidden>
      <path d="M4 20 13 11" />
      <path d="M3 21l1.6-1.6" strokeWidth={2.6} />
      <circle cx="16.5" cy="7.5" r="2.4" fill="#D4A72C" stroke="#D4A72C" />
      <path d="M16.5 2.2v1.3M21.8 7.5h-1.3M20.3 3.7l-.9.9M20.3 11.3l-.9-.9M12.7 3.7l.9.9" strokeWidth={1.4} stroke="#D4A72C" />
    </svg>
  );
}

export function BoardDock({
  tool,
  locked,
  onLock,
  onTool,
  onNote,
  onMermaid,
  onLibrary,
}: {
  tool: string;
  locked: boolean;
  onLock: () => void;
  onTool: (tool: DockTool) => void;
  onNote: () => void;
  onMermaid: () => void;
  onLibrary: () => void;
}) {
  const t = useT();
  const [more, setMore] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  useDismiss(more, () => setMore(false), moreRef);
  const item = (id: DockTool, icon: ReactNode, shortcut: string) => (
    <IconButton
      key={id}
      label={t(`nodes.whiteboard.tool.${id}`)}
      shortcut={shortcut}
      active={tool === id}
      onClick={() => onTool(id)}
      testId={`board-tool-${id}`}
    >
      {icon}
    </IconButton>
  );
  const size = "h-[18px] w-[18px]";
  return (
    <Panel className="flex items-center gap-0.5 p-1" data-testid="board-dock" role="toolbar" aria-label={t("nodes.whiteboard.tool.label")}>
      <IconButton
        label={t(locked ? "nodes.whiteboard.tool.unlock" : "nodes.whiteboard.tool.lock")}
        shortcut="Q"
        active={locked}
        onClick={onLock}
        testId="board-tool-lock"
      >
        {locked ? <Lock className={size} /> : <LockOpen className={size} />}
      </IconButton>
      <Divider />
      {item("selection", <MousePointer2 className={size} />, "V")}
      {item("hand", <Hand className={size} />, "H")}
      <Divider />
      {item("frame", <Frame className={size} />, "F")}
      {item("rectangle", <Square className={size} />, "R")}
      {item("ellipse", <Circle className={size} />, "O")}
      {item("diamond", <Diamond className={size} />, "D")}
      {item("arrow", <ArrowUpRight className={size} />, "A")}
      {item("line", <Minus className={size} />, "L")}
      <Divider />
      {item("freedraw", <Pencil className={size} />, "P")}
      {item("text", <Type className={size} />, "T")}
      <IconButton label={t("nodes.whiteboard.tool.note")} shortcut="N" onClick={onNote} testId="board-tool-note">
        <StickyNote className={size} />
      </IconButton>
      {item("image", <ImagePlus className={size} />, "9")}
      <Divider />
      {item("eraser", <Eraser className={size} />, "E")}
      {item("laser", <LaserIcon className={size} />, "K")}
      <div className="relative" ref={moreRef}>
        <IconButton
          label={t("nodes.whiteboard.tool.more")}
          active={more || tool === "lasso" || tool === "bucket" || tool === "shape"}
          onClick={() => setMore((v) => !v)}
          testId="board-tool-more"
        >
          <MoreHorizontal className={size} />
        </IconButton>
        {more ? (
          <Panel className="absolute bottom-12 right-0 w-64 p-1" data-testid="board-more-menu">
            <MenuItem
              icon={<Lasso className="h-4 w-4" />}
              label={t("nodes.whiteboard.tool.lasso")}
              hint="W"
              active={tool === "lasso"}
              testId="board-tool-lasso"
              onClick={() => {
                setMore(false);
                onTool("lasso");
              }}
            />
            <MenuItem
              icon={<PaintBucket className="h-4 w-4" />}
              label={t("nodes.whiteboard.tool.bucket")}
              hint="B"
              active={tool === "bucket"}
              testId="board-tool-bucket"
              onClick={() => {
                setMore(false);
                onTool("bucket");
              }}
            />
            <MenuItem
              icon={<Shapes className="h-4 w-4" />}
              label={t("nodes.whiteboard.tool.shape")}
              hint="⇧ X"
              active={tool === "shape"}
              testId="board-tool-shape"
              onClick={() => {
                setMore(false);
                onTool("shape");
              }}
            />
            <Divider vertical={false} />
            <MenuItem
              icon={<Workflow className="h-4 w-4" />}
              label={t("nodes.whiteboard.tool.mermaid")}
              onClick={() => {
                setMore(false);
                onMermaid();
              }}
            />
            <MenuItem
              icon={<Library className="h-4 w-4" />}
              label={t("nodes.whiteboard.tool.library")}
              onClick={() => {
                setMore(false);
                onLibrary();
              }}
            />
          </Panel>
        ) : null}
      </div>
    </Panel>
  );
}

function MenuItem({
  icon,
  label,
  hint,
  onClick,
  danger,
  active,
  testId,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  onClick: () => void;
  danger?: boolean;
  active?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-left text-sm transition-colors hover:bg-secondary",
        danger ? "text-destructive" : "text-foreground",
        active && "bg-secondary",
      )}
    >
      <span className={danger ? "text-destructive" : "text-muted-foreground"}>{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      {hint ? <span className="font-mono text-[11px] text-muted-foreground">{hint}</span> : null}
    </button>
  );
}

/* ------------------------------------------------------------------------ */
/* Top-left: menu, undo, redo                                                */
/* ------------------------------------------------------------------------ */

/** Board backgrounds the menu offers (the first is the dotted default). */
export const BACKGROUNDS = ["default", "#f8f9fa", "#fff9db", "#ebfbee", "#e7f5ff", "#f3f0ff", "#1e1e1e"] as const;

export function BoardMenu({
  gridOn,
  background,
  onExportImage,
  onSaveFile,
  onOpenFile,
  onFind,
  onShortcuts,
  onBackground,
  onGrid,
  onClear,
  onUndo,
  onRedo,
}: {
  gridOn: boolean;
  background: string;
  onExportImage: () => void;
  onSaveFile: () => void;
  onOpenFile: () => void;
  onFind: () => void;
  onShortcuts: () => void;
  onBackground: (color: string) => void;
  onGrid: () => void;
  onClear: () => void;
  onUndo: () => void;
  onRedo: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = () => {
    setOpen(false);
    setConfirmClear(false);
  };
  useDismiss(open, close, ref);
  const run = (fn: () => void) => () => {
    close();
    fn();
  };
  return (
    <div className="pointer-events-auto flex items-center gap-2" ref={ref}>
      <Panel className="relative flex items-center gap-0.5 p-1">
        <IconButton label={t("nodes.whiteboard.menu.label")} side="bottom" active={open} onClick={() => setOpen((v) => !v)} testId="board-menu">
          <Menu className="h-[18px] w-[18px]" />
        </IconButton>
        <Divider />
        <IconButton label={t("nodes.whiteboard.undo")} shortcut="Ctrl Z" side="bottom" onClick={onUndo} testId="board-undo">
          <Undo2 className="h-[18px] w-[18px]" />
        </IconButton>
        <IconButton label={t("nodes.whiteboard.redo")} shortcut="Ctrl ⇧ Z" side="bottom" onClick={onRedo} testId="board-redo">
          <Redo2 className="h-[18px] w-[18px]" />
        </IconButton>
        {open ? (
          <Panel className="absolute left-0 top-12 z-10 w-64 p-1" data-testid="board-menu-panel">
            <MenuItem icon={<Download className="h-4 w-4" />} label={t("nodes.whiteboard.menu.export_image")} hint="Ctrl ⇧ E" onClick={run(onExportImage)} />
            <MenuItem icon={<FileDown className="h-4 w-4" />} label={t("nodes.whiteboard.menu.save_file")} onClick={run(onSaveFile)} />
            <MenuItem icon={<FolderOpen className="h-4 w-4" />} label={t("nodes.whiteboard.menu.open_file")} onClick={run(onOpenFile)} />
            <Divider vertical={false} />
            <MenuItem icon={<Search className="h-4 w-4" />} label={t("nodes.whiteboard.menu.find")} hint="Ctrl F" onClick={run(onFind)} />
            <MenuItem icon={<Grid3x3 className="h-4 w-4" />} label={t(gridOn ? "nodes.whiteboard.menu.grid_off" : "nodes.whiteboard.menu.grid_on")} hint="Ctrl '" onClick={run(onGrid)} />
            <MenuItem icon={<Keyboard className="h-4 w-4" />} label={t("nodes.whiteboard.menu.shortcuts")} hint="?" onClick={run(onShortcuts)} />
            <Divider vertical={false} />
            <div className="px-2 pb-1 pt-1.5 text-xs text-muted-foreground">{t("nodes.whiteboard.menu.background")}</div>
            <div className="flex flex-wrap gap-1.5 px-2 pb-2">
              {BACKGROUNDS.map((color) => (
                <Swatch
                  key={color}
                  color={color === "default" ? "dots" : color}
                  label={color === "default" ? t("nodes.whiteboard.menu.background_default") : color}
                  active={background === color}
                  onClick={() => onBackground(color)}
                />
              ))}
            </div>
            <Divider vertical={false} />
            {confirmClear ? (
              <div className="flex items-center gap-2 px-2 py-1.5">
                <span className="flex-1 text-sm text-foreground">{t("nodes.whiteboard.menu.clear_confirm")}</span>
                <button type="button" className="rounded-md bg-destructive px-2 py-1 text-xs text-destructive-foreground" onClick={run(onClear)}>
                  {t("nodes.whiteboard.menu.clear_yes")}
                </button>
              </div>
            ) : (
              <MenuItem icon={<Trash2 className="h-4 w-4" />} label={t("nodes.whiteboard.menu.clear")} danger onClick={() => setConfirmClear(true)} />
            )}
          </Panel>
        ) : null}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Zoom                                                                      */
/* ------------------------------------------------------------------------ */

export function ZoomBar({
  zoom,
  onIn,
  onOut,
  onFit,
  onReset,
}: {
  zoom: number;
  onIn: () => void;
  onOut: () => void;
  onFit: () => void;
  onReset: () => void;
}) {
  const t = useT();
  return (
    <Panel className="flex items-center gap-0.5 p-1" data-testid="board-zoom">
      <IconButton label={t("nodes.whiteboard.zoom.out")} shortcut="Ctrl −" onClick={onOut} testId="board-zoom-out">
        <Minus className="h-4 w-4" />
      </IconButton>
      <QuickTooltip side="top" content={t("nodes.whiteboard.zoom.reset")}>
        <button
          type="button"
          onClick={onReset}
          data-testid="board-zoom-value"
          className="h-9 min-w-[3.25rem] rounded-lg px-1.5 text-center font-mono text-xs tabular-nums text-foreground-secondary hover:bg-secondary hover:text-foreground"
        >
          {Math.round(zoom * 100)}%
        </button>
      </QuickTooltip>
      <IconButton label={t("nodes.whiteboard.zoom.in")} shortcut="Ctrl +" onClick={onIn} testId="board-zoom-in">
        <span className="text-base leading-none">+</span>
      </IconButton>
      <Divider />
      <IconButton label={t("nodes.whiteboard.zoom.fit")} shortcut="⇧ 1" onClick={onFit} testId="board-zoom-fit">
        <Maximize className="h-4 w-4" />
      </IconButton>
    </Panel>
  );
}

/* ------------------------------------------------------------------------ */
/* Inspector                                                                 */
/* ------------------------------------------------------------------------ */

/** Ink colours, from the editor's own palette so the assistant's names match. */
export const STROKES = ["#1e1e1e", "#868e96", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#6741d9", "#c2255c"] as const;
/** Fill colours: the same hues, light. */
export const FILLS = ["transparent", "#f1f3f5", "#ffc9c9", "#ffec99", "#b2f2bb", "#a5d8ff", "#d0bfff", "#fcc2d7"] as const;

/** The editor's font ids: hand-drawn, normal (sans) and code. */
export const FONTS = { hand: 5, sans: 6, mono: 8 } as const;
export const FONT_SIZES = { s: 16, m: 20, l: 28, xl: 36 } as const;

function Swatch({
  color,
  label,
  active,
  onClick,
}: {
  color: string;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  const style: React.CSSProperties =
    color === "transparent"
      ? {
          backgroundImage:
            "linear-gradient(135deg, transparent 45%, hsl(var(--destructive)) 45%, hsl(var(--destructive)) 55%, transparent 55%)",
        }
      : color === "dots"
        ? {
            backgroundColor: "hsl(var(--background))",
            backgroundImage: "radial-gradient(rgb(var(--stage-dot-rgb) / 0.45) 1px, transparent 1px)",
            backgroundSize: "5px 5px",
          }
        : { backgroundColor: color };
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-6 w-6 rounded-full border border-border-strong/70 transition-transform duration-[var(--motion-fast)] hover:scale-110",
        active && "ring-2 ring-accent ring-offset-2 ring-offset-popover",
      )}
      style={style}
    />
  );
}

function Segmented<T extends string | number>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode; title: string }[];
  value: unknown;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex rounded-lg bg-secondary p-0.5">
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          title={option.title}
          aria-label={option.title}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "flex h-7 flex-1 items-center justify-center rounded-md text-xs text-muted-foreground transition-colors",
            value === option.value ? "bg-popover text-foreground shadow-sm" : "hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

function ColorRow({
  colors,
  value,
  onChange,
  customLabel,
}: {
  colors: readonly string[];
  value: unknown;
  onChange: (color: string) => void;
  customLabel: string;
}) {
  const known = colors.includes(String(value));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {colors.map((color) => (
        <Swatch key={color} color={color} label={color} active={value === color} onClick={() => onChange(color)} />
      ))}
      <label
        title={customLabel}
        className={cn(
          "relative h-6 w-6 cursor-pointer overflow-hidden rounded-full border border-border-strong/70",
          !known && value !== undefined && "ring-2 ring-accent ring-offset-2 ring-offset-popover",
        )}
        style={{ background: "conic-gradient(#e03131, #f08c00, #ffd43b, #2f9e44, #1971c2, #6741d9, #c2255c, #e03131)" }}
      >
        <input
          type="color"
          aria-label={customLabel}
          className="absolute inset-0 cursor-pointer opacity-0"
          value={typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value : "#1e1e1e"}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    </div>
  );
}

export function BoardInspector({
  state,
  onStyle,
  onCommand,
}: {
  state: ChromeState;
  onStyle: (patch: StylePatch) => void;
  onCommand: (command: "duplicate" | "delete" | "front" | "back" | "group" | "ungroup" | "lock") => void;
}) {
  const t = useT();
  if (state.tool === "bucket") {
    return (
      <Panel className="w-[244px] space-y-2 p-3" data-testid="board-inspector">
        <Section title={t("nodes.whiteboard.inspector.bucket_color")}>
          <ColorRow
            colors={FILLS.filter((color) => color !== "transparent")}
            value={state.sample.backgroundColor}
            customLabel={t("nodes.whiteboard.inspector.custom")}
            onChange={(backgroundColor) => onStyle({ backgroundColor, fillStyle: "solid" })}
          />
        </Section>
        <p className="text-xs text-muted-foreground">{t("nodes.whiteboard.inspector.bucket_hint")}</p>
      </Panel>
    );
  }
  const kinds = state.selected.length > 0 ? state.selected : TOOLS_THAT_DRAW.has(state.tool) ? [state.tool] : [];
  if (kinds.length === 0) return null;
  const v = state.sample;
  const has = (...types: string[]) => kinds.some((kind) => types.includes(kind));
  const hasText = has("text") || Boolean(v.hasLabel) || state.editingText;
  const hasShape = has("rectangle", "ellipse", "diamond", "freedraw");
  const hasLine = has("arrow", "line");
  const strokeOwner = hasShape || hasLine || has("text") || state.editingText;
  const selection = state.selected.length > 0;
  const onlyMedia = kinds.every((kind) => kind === "image" || kind === "frame");
  const k = (key: string) => t(`nodes.whiteboard.inspector.${key}`);

  return (
    <Panel className="w-[244px] space-y-3.5 p-3" data-testid="board-inspector">
      {strokeOwner && !onlyMedia ? (
        <Section title={hasShape || hasLine ? k("stroke") : k("text_color")}>
          <ColorRow colors={STROKES} value={v.strokeColor} customLabel={k("custom")} onChange={(strokeColor) => onStyle({ strokeColor })} />
        </Section>
      ) : null}
      {hasShape && !state.editingText ? (
        <Section title={k("fill")}>
          <ColorRow
            colors={FILLS}
            value={v.backgroundColor}
            customLabel={k("custom")}
            onChange={(backgroundColor) => onStyle({ backgroundColor, fillStyle: "solid" })}
          />
        </Section>
      ) : null}
      {(hasShape || hasLine) && !state.editingText ? (
        <div className="grid grid-cols-2 gap-2">
          <Section title={k("width")}>
            <Segmented
              value={v.strokeWidth}
              onChange={(strokeWidth) => onStyle({ strokeWidth })}
              options={[
                { value: 1, title: k("thin"), label: <span className="block h-px w-4 bg-current" /> },
                { value: 2, title: k("regular"), label: <span className="block h-0.5 w-4 bg-current" /> },
                { value: 4, title: k("bold"), label: <span className="block h-1 w-4 rounded bg-current" /> },
              ]}
            />
          </Section>
          <Section title={k("style")}>
            <Segmented
              value={v.strokeStyle}
              onChange={(strokeStyle) => onStyle({ strokeStyle })}
              options={[
                { value: "solid", title: k("solid"), label: <span className="block h-0.5 w-4 bg-current" /> },
                { value: "dashed", title: k("dashed"), label: <span className="block h-0.5 w-4 border-t-2 border-dashed border-current" /> },
                { value: "dotted", title: k("dotted"), label: <span className="block h-0.5 w-4 border-t-2 border-dotted border-current" /> },
              ]}
            />
          </Section>
        </div>
      ) : null}
      {(has("rectangle", "diamond") || has("arrow", "line")) && !state.editingText ? (
        <div className="grid grid-cols-2 gap-2">
          <Section title={k("corners")}>
            <Segmented
              value={v.roundness ? "round" : "sharp"}
              onChange={(value) => onStyle({ roundness: value === "round" ? { type: has("rectangle") ? 3 : 2 } : null })}
              options={[
                { value: "sharp", title: k("sharp"), label: <span className="block h-3 w-3 border-l-2 border-t-2 border-current" /> },
                { value: "round", title: k("round"), label: <span className="block h-3 w-3 rounded-tl-md border-l-2 border-t-2 border-current" /> },
              ]}
            />
          </Section>
          <Section title={k("look")}>
            <Segmented
              value={Number(v.roughness ?? 0) > 0 ? 1 : 0}
              onChange={(roughness) => onStyle({ roughness })}
              options={[
                { value: 0, title: k("clean"), label: k("clean") },
                { value: 1, title: k("sketch"), label: k("sketch") },
              ]}
            />
          </Section>
        </div>
      ) : null}
      {has("arrow") && !state.editingText ? (
        <Section title={k("arrowheads")}>
          <Segmented
            value={`${v.startArrowhead ? "s" : ""}${v.endArrowhead ? "e" : ""}` || "none"}
            onChange={(value) =>
              onStyle({
                startArrowhead: String(value).includes("s") ? "arrow" : null,
                endArrowhead: String(value).includes("e") ? "arrow" : null,
              })
            }
            options={[
              { value: "none", title: k("arrow_none"), label: "—" },
              { value: "e", title: k("arrow_end"), label: "→" },
              { value: "se", title: k("arrow_both"), label: "↔" },
            ]}
          />
        </Section>
      ) : null}
      {hasText ? (
        <>
          <Section title={k("font")}>
            <Segmented
              value={v.fontFamily}
              onChange={(fontFamily) => onStyle({ fontFamily })}
              options={[
                { value: FONTS.sans, title: k("sans"), label: <span className="font-sans">Aa</span> },
                { value: FONTS.hand, title: k("hand"), label: <span className="font-serif italic">Aa</span> },
                { value: FONTS.mono, title: k("mono"), label: <span className="font-mono">Aa</span> },
              ]}
            />
          </Section>
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <Section title={k("size")}>
              <Segmented
                value={v.fontSize}
                onChange={(fontSize) => onStyle({ fontSize })}
                options={(Object.entries(FONT_SIZES) as [string, number][]).map(([name, px]) => ({
                  value: px,
                  title: `${px}px`,
                  label: name.toUpperCase(),
                }))}
              />
            </Section>
            <Section title={k("align")}>
              <Segmented
                value={v.textAlign}
                onChange={(textAlign) => onStyle({ textAlign })}
                options={[
                  { value: "left", title: k("left"), label: <AlignLeft className="h-3.5 w-3.5" /> },
                  { value: "center", title: k("center"), label: <AlignCenter className="h-3.5 w-3.5" /> },
                  { value: "right", title: k("right"), label: <AlignRight className="h-3.5 w-3.5" /> },
                ]}
              />
            </Section>
          </div>
        </>
      ) : null}
      {!state.editingText ? (
        <Section title={k("opacity")}>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              aria-label={k("opacity")}
              value={Number(v.opacity ?? 100)}
              onChange={(event) => onStyle({ opacity: Number(event.target.value) })}
              className="h-1.5 flex-1 cursor-pointer accent-[hsl(var(--accent))]"
            />
            <span className="w-9 text-right font-mono text-xs tabular-nums text-muted-foreground">{Number(v.opacity ?? 100)}%</span>
          </div>
        </Section>
      ) : null}
      {selection && !state.editingText ? (
        <div className="flex items-center justify-between border-t border-border pt-2.5">
          <IconButton label={k("front")} shortcut="Ctrl ⇧ ]" onClick={() => onCommand("front")}>
            <BringToFront className="h-4 w-4" />
          </IconButton>
          <IconButton label={k("back")} shortcut="Ctrl ⇧ [" onClick={() => onCommand("back")}>
            <SendToBack className="h-4 w-4" />
          </IconButton>
          {state.selected.length > 1 ? (
            <IconButton label={k("group")} shortcut="Ctrl G" onClick={() => onCommand("group")}>
              <Group className="h-4 w-4" />
            </IconButton>
          ) : (
            <IconButton label={k("ungroup")} shortcut="Ctrl ⇧ G" onClick={() => onCommand("ungroup")}>
              <Ungroup className="h-4 w-4" />
            </IconButton>
          )}
          <IconButton label={k("duplicate")} shortcut="Ctrl D" onClick={() => onCommand("duplicate")}>
            <Copy className="h-4 w-4" />
          </IconButton>
          <IconButton label={k("lock")} shortcut="Ctrl ⇧ L" onClick={() => onCommand("lock")}>
            <Lock className="h-4 w-4" />
          </IconButton>
          <IconButton label={k("delete")} shortcut="Del" onClick={() => onCommand("delete")}>
            <Trash2 className="h-4 w-4" />
          </IconButton>
        </div>
      ) : null}
    </Panel>
  );
}

/* ------------------------------------------------------------------------ */
/* The assistant at work, and the empty board                                */
/* ------------------------------------------------------------------------ */

export function LiveBadge({ name }: { name: string }) {
  const t = useT();
  return (
    <Panel className="flex items-center gap-2 px-3 py-1.5 text-sm" data-testid="board-live" role="status">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#D4A72C] opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[#D4A72C]" />
      </span>
      {t("nodes.whiteboard.live.drawing").replace("{assistant}", () => name)}
    </Panel>
  );
}

export function EmptyHint({ name }: { name: string }) {
  const t = useT();
  return (
    <div className="pointer-events-none flex max-w-sm flex-col items-center gap-1.5 text-center" data-testid="board-empty">
      <p className="text-base font-medium text-foreground-secondary">{t("nodes.whiteboard.empty.title")}</p>
      <p className="text-sm text-muted-foreground">{t("nodes.whiteboard.empty.hint").replace("{assistant}", () => name)}</p>
    </div>
  );
}
