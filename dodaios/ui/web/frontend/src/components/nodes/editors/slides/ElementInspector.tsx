/**
 * The format panel of the selected elements: where they are, how they look,
 * how they come in, and the order they lie in.
 *
 * One element shows every setting of its type (a text box: font, size,
 * colour, style, alignment, lists, spacing, fill and outline; a picture: how
 * it fills its box, its corners and outline; a line: its ends; a table: its
 * cells; a chart: its editor). Several elements show what they share:
 * arranging, aligning, spreading out, opacity and the fill.
 *
 * Every change is one labelled undo step of the deck; typing into a number
 * or a text is one step per run.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  AlignCenter,
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignJustify,
  AlignLeft,
  AlignRight,
  AlignStartHorizontal,
  AlignStartVertical,
  ArrowDownToLine,
  ArrowUpToLine,
  BarChart3,
  Bold,
  BringToFront,
  CaseUpper,
  ChevronDown,
  ChevronUp,
  Copy,
  ImagePlus,
  Italic,
  List,
  ListOrdered,
  Lock,
  SendToBack,
  Strikethrough,
  Trash2,
  Underline,
  Unlock,
  AlignHorizontalSpaceAround,
  AlignVerticalSpaceAround,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { fill as fillText, useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { ColorPicker, NumberField, Select, ToolbarButton } from "../controls";
import {
  ANIMATIONS,
  boundsOf,
  CELL_CHARS,
  DASHES,
  FONTS,
  FONT_STACKS,
  hasText,
  MAX_TABLE_COLUMNS,
  MAX_TABLE_ROWS,
  PATH_SHAPES,
  round1,
  SHAPES,
  SLIDE_H,
  SLIDE_W,
  translate,
  unionOf,
  type ImageElement,
  type LineElement,
  type ShapeElement,
  type SlideElement,
  type TableElement,
  type TextElement,
} from "./elementModel";
import type { ElementsChange } from "./CanvasEditor";

/** The colours offered for elements: the kit's series, then neutrals. */
export const ELEMENT_COLORS: readonly string[] = [
  "#2A6FD0",
  "#D4532E",
  "#158F6B",
  "#A86B00",
  "#5B46C2",
  "#C23F86",
  "#0F172A",
  "#1F2328",
  "#59636E",
  "#94A3B8",
  "#D1D9E0",
  "#F1F5F9",
  "#FFFFFF",
  "#FDE68A",
  "#BFDBFE",
];

export interface ElementInspectorProps {
  elements: readonly SlideElement[];
  /** The selected elements' places in `elements`. */
  selected: readonly number[];
  slideIndex: number;
  onChange: ElementsChange;
  onDuplicate: () => void;
  onDelete: () => void;
  onOrder: (how: "front" | "forward" | "backward" | "back") => void;
  onReplaceImage: (index: number) => void;
  onEditChart: (index: number) => void;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{label}</span>
      <div className="flex shrink-0 items-center gap-1">{children}</div>
    </div>
  );
}

/** A row of toggle or choice buttons with icons. */
export function Segmented<T extends string>({
  value,
  options,
  onPick,
  label,
  testId,
}: {
  value: T | T[] | undefined;
  options: readonly { value: T; label: string; icon: ReactNode }[];
  onPick: (value: T) => void;
  label: string;
  testId?: string;
}) {
  const on = (v: T) => (Array.isArray(value) ? value.includes(v) : value === v);
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5 rounded-md bg-secondary/60 p-0.5" data-testid={testId}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-label={option.label}
          title={option.label}
          aria-pressed={on(option.value)}
          onClick={() => onPick(option.value)}
          data-testid={testId ? `${testId}-${option.value}` : undefined}
          className={cn(
            "grid h-7 w-7 place-items-center rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-4 [&_svg]:w-4",
            on(option.value) && "bg-background text-foreground shadow-sm",
          )}
        >
          {option.icon}
        </button>
      ))}
    </div>
  );
}

/** A small picture of a shape, for the shape menus. */
export function ShapeGlyph({ shape, className }: { shape: string; className?: string }) {
  const path = PATH_SHAPES[shape];
  return (
    <svg viewBox="-4 -4 108 108" className={cn("h-5 w-5", className)} aria-hidden>
      {path ? (
        <path d={path} fill="currentColor" opacity={0.85} />
      ) : shape === "ellipse" ? (
        <ellipse cx={50} cy={50} rx={50} ry={50} fill="currentColor" opacity={0.85} />
      ) : (
        <rect x={0} y={10} width={100} height={80} rx={shape === "rounded" ? 22 : 2} fill="currentColor" opacity={0.85} />
      )}
    </svg>
  );
}

function Toggle({ on, label, onClick, children, testId }: { on: boolean; label: string; onClick: () => void; children: ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      title={label}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-4 [&_svg]:w-4",
        on && "bg-secondary text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function ElementInspector({
  elements,
  selected,
  slideIndex,
  onChange,
  onDuplicate,
  onDelete,
  onOrder,
  onReplaceImage,
  onEditChart,
}: ElementInspectorProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const items = selected.map((i) => elements[i]).filter(Boolean);
  if (!items.length) return null;
  const single = items.length === 1 ? items[0] : null;
  const index = selected[0];

  /** Set something on every selected element (one undo step, or a typing run). */
  const each = (label: string, change: (element: SlideElement) => void, coalesce?: string) =>
    onChange(
      label,
      (list) => {
        for (const i of selected) if (list[i]) change(list[i]);
      },
      coalesce,
    );

  const set = <K extends string>(key: K, value: unknown, label = L("step.format")) =>
    each(label, (element) => {
      const record = element as unknown as Record<string, unknown>;
      if (value === undefined || value === "" || value === false || value === null) delete record[key];
      else record[key] = value;
    });

  const kindName = single ? L(`el.kind.${single.type}`) : fillText(L("el.many"), { n: items.length });
  const locked = items.every((item) => item.locked);

  // --- the head: what is selected, and the quick actions --------------------------------
  const head = (
    <div className="flex items-center gap-1">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" data-testid="slides-element-kind">
          {kindName}
        </p>
        <p className="text-xs text-muted-foreground">{fillText(L("inspector.slide"), { n: slideIndex + 1 })}</p>
      </div>
      <ToolbarButton label={L("el.duplicate")} icon={<Copy aria-hidden />} onClick={onDuplicate} className="h-8 w-8" data-testid="slides-el-duplicate" />
      <ToolbarButton
        label={locked ? L("el.unlock") : L("el.lock")}
        icon={locked ? <Lock aria-hidden /> : <Unlock aria-hidden />}
        onClick={() => set("locked", !locked, locked ? L("el.unlock") : L("el.lock"))}
        className="h-8 w-8"
        data-testid="slides-el-lock"
      />
      <ToolbarButton label={L("el.delete")} icon={<Trash2 aria-hidden />} onClick={onDelete} className="h-8 w-8" data-testid="slides-el-delete" />
    </div>
  );

  // --- position and size ------------------------------------------------------------------
  const position = single ? (
    <Section title={L("el.section.position")}>
      {single.type === "line" ? (
        <div className="grid grid-cols-2 gap-2">
          {(["x1", "y1", "x2", "y2"] as const).map((key) => (
            <NumberField
              key={key}
              label={L(`el.${key}`)}
              showLabel
              value={(single as LineElement)[key]}
              min={-SLIDE_W}
              max={2 * SLIDE_W}
              suffix="px"
              onChange={(value) => set(key, value ?? 0, L("step.resize"))}
            />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="X" showLabel value={single.x} min={-SLIDE_W} max={2 * SLIDE_W} suffix="px" onChange={(v) => set("x", v ?? 0, L("step.move_element"))} />
            <NumberField label="Y" showLabel value={single.y} min={-SLIDE_H} max={2 * SLIDE_H} suffix="px" onChange={(v) => set("y", v ?? 0, L("step.move_element"))} />
            <NumberField label={L("el.width")} showLabel value={single.w} min={4} max={2 * SLIDE_W} suffix="px" onChange={(v) => set("w", v ?? 4, L("step.resize"))} />
            <NumberField label={L("el.height")} showLabel value={single.h} min={4} max={2 * SLIDE_H} suffix="px" onChange={(v) => set("h", v ?? 4, L("step.resize"))} />
          </div>
          <NumberField
            label={L("el.rotate")}
            showLabel
            value={single.rotate ?? 0}
            min={-360}
            max={360}
            suffix="°"
            onChange={(v) => set("rotate", v || undefined, L("step.rotate"))}
          />
        </>
      )}
    </Section>
  ) : null;

  // --- arrange, align, spread ------------------------------------------------------------------
  const alignTo = (how: "left" | "center" | "right" | "top" | "middle" | "bottom") => {
    const boxes = selected.map((i) => boundsOf(elements[i]));
    // One element aligns to the slide; several to the frame around them.
    const frame = items.length === 1 ? { x: 0, y: 0, w: SLIDE_W, h: SLIDE_H } : unionOf(boxes)!;
    onChange(L("step.align"), (list) => {
      selected.forEach((i, n) => {
        const b = boxes[n];
        const element = list[i];
        if (!element || element.locked) return;
        let dx = 0;
        let dy = 0;
        if (how === "left") dx = frame.x - b.x;
        if (how === "center") dx = frame.x + frame.w / 2 - (b.x + b.w / 2);
        if (how === "right") dx = frame.x + frame.w - (b.x + b.w);
        if (how === "top") dy = frame.y - b.y;
        if (how === "middle") dy = frame.y + frame.h / 2 - (b.y + b.h / 2);
        if (how === "bottom") dy = frame.y + frame.h - (b.y + b.h);
        translate(element, dx, dy);
      });
    });
  };
  const spread = (axis: "x" | "y") => {
    const order = selected
      .map((i) => ({ i, b: boundsOf(elements[i]) }))
      .sort((a, b) => (axis === "x" ? a.b.x - b.b.x : a.b.y - b.b.y));
    if (order.length < 3) return;
    const first = order[0].b;
    const last = order[order.length - 1].b;
    const span = axis === "x" ? last.x + last.w - first.x : last.y + last.h - first.y;
    const sizes = order.reduce((sum, o) => sum + (axis === "x" ? o.b.w : o.b.h), 0);
    const gap = (span - sizes) / (order.length - 1);
    onChange(L("step.align"), (list) => {
      let at = axis === "x" ? first.x : first.y;
      for (const { i, b } of order) {
        const element = list[i];
        if (element && !element.locked) {
          if (axis === "x") translate(element, at - b.x, 0);
          else translate(element, 0, at - b.y);
        }
        at += (axis === "x" ? b.w : b.h) + gap;
      }
    });
  };

  const arrange = (
    <Section title={L("el.section.arrange")}>
      <div className="flex flex-wrap items-center gap-1">
        <ToolbarButton label={L("el.order.front")} icon={<BringToFront aria-hidden />} onClick={() => onOrder("front")} className="h-8 w-8" data-testid="slides-order-front" />
        <ToolbarButton label={L("el.order.forward")} icon={<ChevronUp aria-hidden />} onClick={() => onOrder("forward")} className="h-8 w-8" />
        <ToolbarButton label={L("el.order.backward")} icon={<ChevronDown aria-hidden />} onClick={() => onOrder("backward")} className="h-8 w-8" />
        <ToolbarButton label={L("el.order.back")} icon={<SendToBack aria-hidden />} onClick={() => onOrder("back")} className="h-8 w-8" data-testid="slides-order-back" />
      </div>
      <p className="text-xs text-muted-foreground">{items.length === 1 ? L("el.align.to_slide") : L("el.align.to_selection")}</p>
      <div className="flex flex-wrap items-center gap-1" data-testid="slides-align">
        <ToolbarButton label={L("el.align.left")} icon={<AlignStartVertical aria-hidden />} onClick={() => alignTo("left")} className="h-8 w-8" data-testid="slides-align-left" />
        <ToolbarButton label={L("el.align.center")} icon={<AlignCenterVertical aria-hidden />} onClick={() => alignTo("center")} className="h-8 w-8" data-testid="slides-align-center" />
        <ToolbarButton label={L("el.align.right")} icon={<AlignEndVertical aria-hidden />} onClick={() => alignTo("right")} className="h-8 w-8" />
        <ToolbarButton label={L("el.align.top")} icon={<AlignStartHorizontal aria-hidden />} onClick={() => alignTo("top")} className="h-8 w-8" />
        <ToolbarButton label={L("el.align.middle")} icon={<AlignCenterHorizontal aria-hidden />} onClick={() => alignTo("middle")} className="h-8 w-8" data-testid="slides-align-middle" />
        <ToolbarButton label={L("el.align.bottom")} icon={<AlignEndHorizontal aria-hidden />} onClick={() => alignTo("bottom")} className="h-8 w-8" />
        {items.length >= 3 && (
          <>
            <ToolbarButton label={L("el.spread.x")} icon={<AlignHorizontalSpaceAround aria-hidden />} onClick={() => spread("x")} className="h-8 w-8" />
            <ToolbarButton label={L("el.spread.y")} icon={<AlignVerticalSpaceAround aria-hidden />} onClick={() => spread("y")} className="h-8 w-8" />
          </>
        )}
      </div>
    </Section>
  );

  // --- text ------------------------------------------------------------------------------------
  const texts = items.filter(hasText) as (TextElement | ShapeElement)[];
  const first = texts[0];
  const textSection = first ? (
    <Section title={L("el.section.text")}>
      <div className="grid grid-cols-[1fr_88px] gap-2">
        <Select
          label={L("el.font")}
          value={first.font ?? "sans"}
          options={FONTS.map((font) => ({ value: font, label: L(`font.${font}`) }))}
          onChange={(value) => set("font", value === "sans" ? undefined : value)}
          testId="slides-el-font"
        />
        <NumberField
          label={L("el.size")}
          value={first.size ?? (first.type === "shape" ? 24 : 28)}
          min={8}
          max={240}
          suffix="px"
          onChange={(value) => set("size", value ?? undefined)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Toggle on={!!first.bold} label={L("el.bold")} onClick={() => set("bold", !first.bold)} testId="slides-el-bold">
          <Bold aria-hidden />
        </Toggle>
        <Toggle on={!!first.italic} label={L("el.italic")} onClick={() => set("italic", !first.italic)} testId="slides-el-italic">
          <Italic aria-hidden />
        </Toggle>
        <Toggle on={!!first.underline} label={L("el.underline")} onClick={() => set("underline", !first.underline)}>
          <Underline aria-hidden />
        </Toggle>
        <Toggle on={!!first.strike} label={L("el.strike")} onClick={() => set("strike", !first.strike)}>
          <Strikethrough aria-hidden />
        </Toggle>
        <Toggle on={!!first.caps} label={L("el.caps")} onClick={() => set("caps", !first.caps)}>
          <CaseUpper aria-hidden />
        </Toggle>
        <span className="ml-auto" />
        <ColorPicker label={L("el.text_color")} value={first.color?.startsWith("#") ? first.color.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("color", value || undefined)} />
      </div>
      <Row label={L("el.align_text")}>
        <Segmented
          label={L("el.align_text")}
          value={first.align ?? (first.type === "shape" ? "center" : "left")}
          options={[
            { value: "left", label: L("el.align.text_left"), icon: <AlignLeft aria-hidden /> },
            { value: "center", label: L("el.align.text_center"), icon: <AlignCenter aria-hidden /> },
            { value: "right", label: L("el.align.text_right"), icon: <AlignRight aria-hidden /> },
            { value: "justify", label: L("el.align.text_justify"), icon: <AlignJustify aria-hidden /> },
          ]}
          onPick={(value) => set("align", value)}
          testId="slides-el-align"
        />
      </Row>
      <Row label={L("el.valign")}>
        <Segmented
          label={L("el.valign")}
          value={first.valign ?? (first.type === "shape" ? "middle" : "top")}
          options={[
            { value: "top", label: L("el.valign_top"), icon: <ArrowUpToLine aria-hidden /> },
            { value: "middle", label: L("el.valign_middle"), icon: <AlignCenterHorizontal aria-hidden /> },
            { value: "bottom", label: L("el.valign_bottom"), icon: <ArrowDownToLine aria-hidden /> },
          ]}
          onPick={(value) => set("valign", value)}
        />
      </Row>
      <Row label={L("el.list")}>
        <Segmented
          label={L("el.list")}
          value={first.list ?? ("none" as const)}
          options={[
            { value: "none", label: L("el.list_none"), icon: <span className="text-xs">Aa</span> },
            { value: "bullet", label: L("el.list_bullet"), icon: <List aria-hidden /> },
            { value: "number", label: L("el.list_number"), icon: <ListOrdered aria-hidden /> },
          ]}
          onPick={(value) => set("list", value === "none" ? undefined : value)}
          testId="slides-el-list"
        />
      </Row>
      <div className="grid grid-cols-2 gap-2">
        <NumberField label={L("el.line_height")} showLabel value={first.line ?? 1.25} min={0.8} max={3} step={0.05} decimals={2} onChange={(v) => set("line", v ?? undefined)} />
        <NumberField label={L("el.spacing")} showLabel value={first.spacing ?? 0} min={-0.1} max={0.5} step={0.01} decimals={2} suffix="em" onChange={(v) => set("spacing", v || undefined)} />
      </div>
      <Row label={L("el.padding")}>
        <NumberField label={L("el.padding")} value={first.padding ?? (first.type === "shape" || first.fill || first.stroke ? 16 : 0)} min={0} max={120} suffix="px" className="w-24" onChange={(v) => set("padding", v ?? undefined)} />
      </Row>
    </Section>
  ) : null;

  // --- shape kind ------------------------------------------------------------------------------
  const shape = single?.type === "shape" ? (single as ShapeElement) : null;
  const shapeSection = shape ? (
    <Section title={L("el.section.shape")}>
      <div className="grid grid-cols-7 gap-1" role="radiogroup" aria-label={L("el.section.shape")}>
        {SHAPES.map((name) => (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={shape.shape === name}
            aria-label={L(`shape.${name}`)}
            title={L(`shape.${name}`)}
            onClick={() =>
              each(L("step.format"), (element) => {
                if (element.type !== "shape") return;
                element.shape = name;
                if (name !== "rect") delete element.radius;
              })
            }
            className={cn(
              "grid h-8 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              shape.shape === name && "bg-secondary text-foreground",
            )}
          >
            <ShapeGlyph shape={name} />
          </button>
        ))}
      </div>
    </Section>
  ) : null;

  // --- fill and outline ---------------------------------------------------------------------------
  const painted = items.filter((item) => item.type === "text" || item.type === "shape" || item.type === "image") as (TextElement | ShapeElement | ImageElement)[];
  const paintFirst = painted[0];
  const canFill = painted.some((item) => item.type !== "image");
  const canRadius = painted.some((item) => item.type === "text" || item.type === "image" || (item.type === "shape" && item.shape === "rect"));
  const paintSection = paintFirst ? (
    <Section title={L("el.section.fill")}>
      {canFill && (
        <Row label={L("el.fill")}>
          <ColorPicker
            label={L("el.fill")}
            value={"fill" in paintFirst && paintFirst.fill?.startsWith("#") ? paintFirst.fill.toUpperCase() : ""}
            palette={ELEMENT_COLORS}
            onChange={(value) => set("fill", value || undefined)}
          />
          <button
            type="button"
            className="h-8 rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => set("fill", "transparent")}
            data-testid="slides-el-no-fill"
          >
            {L("el.no_fill")}
          </button>
        </Row>
      )}
      <Row label={L("el.outline")}>
        <ColorPicker
          label={L("el.outline")}
          value={paintFirst.stroke?.startsWith("#") ? paintFirst.stroke.toUpperCase() : ""}
          palette={ELEMENT_COLORS}
          onChange={(value) =>
            each(L("step.format"), (element) => {
              const target = element as TextElement;
              if (!value) {
                delete target.stroke;
                delete target.stroke_width;
                delete target.dash;
              } else {
                target.stroke = value;
                target.stroke_width = target.stroke_width ?? 2;
              }
            })
          }
        />
        <NumberField label={L("el.outline_width")} value={paintFirst.stroke ? (paintFirst.stroke_width ?? 2) : 0} min={0} max={40} suffix="px" className="w-20" onChange={(v) => set("stroke_width", v || undefined)} />
      </Row>
      {paintFirst.stroke && (
        <Row label={L("el.dash")}>
          <Select
            label={L("el.dash")}
            value={paintFirst.dash ?? "solid"}
            options={DASHES.map((dash) => ({ value: dash, label: L(`el.dash_${dash}`) }))}
            onChange={(value) => set("dash", value === "solid" ? undefined : value)}
            className="w-32"
          />
        </Row>
      )}
      {canRadius && (
        <Row label={L("el.radius")}>
          <NumberField label={L("el.radius")} value={paintFirst.radius ?? 0} min={0} max={400} suffix="px" className="w-24" onChange={(v) => set("radius", v || undefined)} />
        </Row>
      )}
      <Row label={L("el.shadow")}>
        <Toggle on={!!paintFirst.shadow} label={L("el.shadow")} onClick={() => set("shadow", !paintFirst.shadow)}>
          <span className="h-3.5 w-3.5 rounded-sm bg-foreground/80 shadow-[2px_2px_0_hsl(var(--muted-foreground))]" />
        </Toggle>
      </Row>
    </Section>
  ) : null;

  // --- opacity (everything) ---------------------------------------------------------------------
  const opacitySection = (
    <Row label={L("el.opacity")}>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        aria-label={L("el.opacity")}
        value={items[0].opacity ?? 100}
        onChange={(event) => {
          const value = Number(event.target.value);
          each(L("el.opacity"), (element) => {
            if (value >= 100) delete element.opacity;
            else element.opacity = value;
          }, `opacity:${selected.join(",")}`);
        }}
        className="w-28 accent-[hsl(var(--accent))]"
        data-testid="slides-el-opacity"
      />
      <span className="w-9 text-right text-xs tabular-nums text-muted-foreground">{items[0].opacity ?? 100}%</span>
    </Row>
  );

  // --- picture ---------------------------------------------------------------------------------
  const image = single?.type === "image" ? (single as ImageElement) : null;
  const imageSection = image ? (
    <Section title={L("el.section.image")}>
      <button
        type="button"
        onClick={() => onReplaceImage(index)}
        className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-border-strong text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="slides-el-replace-image"
      >
        <ImagePlus className="h-4 w-4" aria-hidden />
        {L("image.replace")}
      </button>
      <Row label={L("image.fit")}>
        <Select
          label={L("image.fit")}
          value={image.fit ?? "cover"}
          options={[
            { value: "cover", label: L("image.fit_cover") },
            { value: "contain", label: L("image.fit_contain") },
            { value: "fill", label: L("image.fit_fill") },
          ]}
          onChange={(value) => set("fit", value === "cover" ? undefined : value)}
          className="w-36"
        />
      </Row>
      <Input
        value={image.alt ?? ""}
        maxLength={140}
        placeholder={L("el.alt")}
        aria-label={L("el.alt")}
        className="h-8 px-2 text-sm"
        onChange={(event) => onChange(L("step.format"), (list) => {
          const target = list[index] as ImageElement;
          if (event.target.value) target.alt = event.target.value;
          else delete target.alt;
        }, `alt:${index}`)}
      />
    </Section>
  ) : null;

  // --- line ------------------------------------------------------------------------------------
  const line = single?.type === "line" ? (single as LineElement) : null;
  const ends = [
    { value: "none" as const, label: L("el.end_none"), icon: <span className="block h-px w-4 bg-current" /> },
    { value: "arrow" as const, label: L("el.end_arrow"), icon: <span className="text-sm leading-none">→</span> },
    { value: "dot" as const, label: L("el.end_dot"), icon: <span className="text-sm leading-none">•</span> },
  ];
  const lineSection = line ? (
    <Section title={L("el.section.line")}>
      <Row label={L("el.line_color")}>
        <ColorPicker label={L("el.line_color")} value={line.color?.startsWith("#") ? line.color.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("color", value || undefined)} />
        <NumberField label={L("el.line_width")} value={line.width ?? 4} min={1} max={40} suffix="px" className="w-20" onChange={(v) => set("width", v ?? undefined)} />
      </Row>
      <Row label={L("el.dash")}>
        <Select
          label={L("el.dash")}
          value={line.dash ?? "solid"}
          options={DASHES.map((dash) => ({ value: dash, label: L(`el.dash_${dash}`) }))}
          onChange={(value) => set("dash", value === "solid" ? undefined : value)}
          className="w-32"
        />
      </Row>
      <Row label={L("el.start")}>
        <Segmented label={L("el.start")} value={line.start ?? "none"} options={ends} onPick={(value) => set("start", value === "none" ? undefined : value)} />
      </Row>
      <Row label={L("el.end")}>
        <Segmented label={L("el.end")} value={line.end ?? "none"} options={ends} onPick={(value) => set("end", value === "none" ? undefined : value)} testId="slides-el-end" />
      </Row>
    </Section>
  ) : null;

  // --- table -----------------------------------------------------------------------------------
  const table = single?.type === "table" ? (single as TableElement) : null;
  const tableSection = table ? (
    <Section title={L("el.section.table")}>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-1 text-xs" aria-label={L("el.section.table")}>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c} className="p-0">
                    <Input
                      value={cell}
                      maxLength={CELL_CHARS}
                      aria-label={fillText(L("table.cell"), { row: r + 1, column: c + 1 })}
                      className={cn("h-7 min-w-[72px] px-1.5 text-xs", r === 0 && table.head !== false && "font-medium")}
                      onChange={(event) =>
                        onChange(L("step.type"), (list) => {
                          const target = list[index] as TableElement;
                          target.rows[r][c] = event.target.value;
                        }, `cell:${index}:${r}:${c}`)
                      }
                      data-testid={`slides-el-cell-${r}-${c}`}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-1">
        {(
          [
            ["add_row", table.rows.length < MAX_TABLE_ROWS, (target: TableElement) => target.rows.push(target.rows[0].map(() => ""))],
            ["remove_row", table.rows.length > 1, (target: TableElement) => target.rows.pop()],
            ["add_column", table.rows[0].length < MAX_TABLE_COLUMNS, (target: TableElement) => target.rows.forEach((row) => row.push(""))],
            ["remove_column", table.rows[0].length > 1, (target: TableElement) => target.rows.forEach((row) => row.pop())],
          ] as const
        ).map(([key, enabled, change]) => (
          <button
            key={key}
            type="button"
            disabled={!enabled}
            onClick={() => onChange(L(`el.table.${key}`), (list) => change(list[index] as TableElement))}
            className="h-7 rounded-md border border-border px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40"
            data-testid={`slides-el-table-${key}`}
          >
            {L(`el.table.${key}`)}
          </button>
        ))}
      </div>
      <Row label={L("el.table.head")}>
        <Toggle on={table.head !== false} label={L("el.table.head")} onClick={() => set("head", table.head === false ? undefined : false)}>
          <span className="text-xs font-semibold">H</span>
        </Toggle>
      </Row>
      <div className="grid grid-cols-[1fr_88px] gap-2">
        <Select
          label={L("el.font")}
          value={table.font ?? "sans"}
          options={FONTS.map((font) => ({ value: font, label: L(`font.${font}`) }))}
          onChange={(value) => set("font", value === "sans" ? undefined : value)}
        />
        <NumberField label={L("el.size")} value={table.size ?? 20} min={8} max={72} suffix="px" onChange={(v) => set("size", v ?? undefined)} />
      </div>
      <Row label={L("el.text_color")}>
        <ColorPicker label={L("el.text_color")} value={table.color?.startsWith("#") ? table.color.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("color", value || undefined)} />
      </Row>
      <Row label={L("el.table.head_fill")}>
        <ColorPicker label={L("el.table.head_fill")} value={table.fill?.startsWith("#") ? table.fill.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("fill", value || undefined)} />
      </Row>
      <Row label={L("el.table.lines")}>
        <ColorPicker label={L("el.table.lines")} value={table.stroke?.startsWith("#") ? table.stroke.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("stroke", value || undefined)} />
      </Row>
    </Section>
  ) : null;

  // --- chart -----------------------------------------------------------------------------------
  const chartSection =
    single?.type === "chart" ? (
      <Section title={L("section.chart")}>
        <button
          type="button"
          onClick={() => onEditChart(index)}
          data-testid="slides-el-edit-chart"
          className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-border-strong text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <BarChart3 className="h-4 w-4" aria-hidden />
          {L("chart.edit")}
        </button>
      </Section>
    ) : null;

  // --- animation and link ------------------------------------------------------------------------
  const anim = items[0].anim ?? "";
  const motionSection = (
    <Section title={L("el.section.motion")}>
      <Row label={L("el.anim")}>
        <Select
          label={L("el.anim")}
          value={anim || "none"}
          options={[{ value: "none", label: L("anim.none") }, ...ANIMATIONS.map((name) => ({ value: name, label: L(`anim.${name}`) }))]}
          onChange={(value) =>
            each(L("step.anim"), (element) => {
              if (value === "none") {
                delete element.anim;
                delete element.click;
              } else element.anim = value as SlideElement["anim"];
            })
          }
          className="w-36"
          testId="slides-el-anim"
        />
      </Row>
      {anim && (
        <Row label={L("el.anim_on")}>
          <Select
            label={L("el.anim_on")}
            value={items[0].click ? "click" : "enter"}
            options={[
              { value: "enter", label: L("el.anim_enter") },
              { value: "click", label: L("el.anim_click") },
            ]}
            onChange={(value) => set("click", value === "click" || undefined, L("step.anim"))}
            className="w-36"
          />
        </Row>
      )}
      {single && (
        <LinkField
          key={single.id ?? index}
          value={single.link ?? ""}
          label={L("el.link")}
          invalid={L("el.link_invalid")}
          onCommit={(value) =>
            onChange(L("step.link"), (list) => {
              const target = list[index];
              if (!target) return;
              if (value) target.link = value;
              else delete target.link;
            })
          }
        />
      )}
    </Section>
  );

  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="slides-element-inspector">
      {head}
      {textSection}
      {shapeSection}
      {paintSection}
      {lineSection}
      {imageSection}
      {tableSection}
      {chartSection}
      <Section title={L("el.section.look")}>{opacitySection}</Section>
      {position}
      {arrange}
      {motionSection}
    </div>
  );
}

/** A link typed freely and taken on Enter or when the field is left (a web or mail address, or nothing). */
function LinkField({ value, label, invalid, onCommit }: { value: string; label: string; invalid: string; onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const clean = draft.trim();
  const ok = !clean || /^(https?:\/\/|mailto:)\S+$/i.test(clean);
  const take = () => {
    if (!ok) return;
    if (clean !== value) onCommit(clean);
  };
  return (
    <div className="flex flex-col gap-1">
      <Input
        value={draft}
        placeholder={label}
        aria-label={label}
        aria-invalid={!ok || undefined}
        className={cn("h-8 px-2 text-sm", !ok && "border-destructive")}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={take}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            take();
          }
        }}
        data-testid="slides-el-link"
      />
      {!ok && <p className="text-xs text-destructive">{invalid}</p>}
    </div>
  );
}

/** A font's preview style, for menus that show each family in itself. */
export function fontPreview(font: string): React.CSSProperties {
  return { fontFamily: FONT_STACKS[font] ?? undefined };
}

/** Round a rectangle to one decimal, as the server keeps it. */
export function roundRect(rect: { x: number; y: number; w: number; h: number }) {
  return { x: round1(rect.x), y: round1(rect.y), w: round1(rect.w), h: round1(rect.h) };
}
