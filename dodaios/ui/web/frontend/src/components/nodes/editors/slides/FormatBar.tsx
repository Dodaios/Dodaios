/**
 * The deck's formatting tools in the node bar at the bottom of the open deck.
 *
 * With a text box or a shape selected: font, size, bold, italic, underline,
 * text colour, alignment, lists and fill (a line: its colour). With nothing
 * selected: one "Slide" button for the slide's layout, background,
 * transition and whether it is shown when presenting. The inspector (opened
 * from the bar) holds every setting; this repeats the common ones where the
 * hand already is, the way an office suite's format bar does.
 */
import { type ReactNode } from "react";
import { AlignCenter, AlignLeft, AlignRight, Baseline, Bold, ChevronDown, Eye, EyeOff, Italic, LayoutTemplate, List, ListOrdered, Minus, PaintBucket, PenLine, Plus, Underline } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { ColorPicker, MenuItem, Popover, Select, ToolbarButton } from "../controls";
import type { Deck, Layout, Slide } from "./deckModel";
import { FONTS, hasText, TRANSITIONS, type ShapeElement, type SlideElement, type TextElement } from "./elementModel";
import { ELEMENT_COLORS } from "./ElementInspector";
import { LayoutPicker } from "./LayoutPicker";
import { BackgroundEditor } from "./SlideDesign";
import type { ElementsChange } from "./CanvasEditor";

export interface FormatBarProps {
  slide: Slide;
  deck: Deck;
  elements: readonly SlideElement[];
  selected: readonly number[];
  onElements: ElementsChange;
  onSlide: (label: string, change: (slide: Slide) => void, coalesce?: string) => void;
  onLayout: (layout: Layout) => void;
  onPickBackground: () => void;
}

/** A colour swatch that sits in the bar like its icons do. */
const SWATCH = "h-8 border-0 px-2 hover:bg-secondary";

export function FormatBar({ slide, deck, elements, selected, onElements, onSlide, onLayout, onPickBackground }: FormatBarProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const items = selected.map((i) => elements[i]).filter(Boolean);

  const each = (label: string, change: (element: SlideElement) => void) =>
    onElements(label, (list) => {
      for (const i of selected) if (list[i]) change(list[i]);
    });
  const set = (key: string, value: unknown) =>
    each(L("step.format"), (element) => {
      const record = element as unknown as Record<string, unknown>;
      if (value === undefined || value === false || value === "") delete record[key];
      else record[key] = value;
    });

  const group = (children: ReactNode) => (
    <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label={L("format.label")} data-testid="slides-format-bar">
      {children}
    </div>
  );

  if (!items.length) {
    return group(
      <Popover
        label={L("format.slide")}
        trigger={
          <ToolbarButton
            label={L("format.slide")}
            icon={<LayoutTemplate aria-hidden />}
            trailing={<ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden />}
            data-testid="slides-bar-layout"
          />
        }
      >
        <div className="flex w-80 flex-col gap-3 p-2" data-testid="slides-bar-slide">
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">{L("layout.change")}</p>
            <LayoutPicker current={slide.layout} onPick={(layout) => onLayout(layout)} />
          </div>
          <div className="border-t border-border pt-3">
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">{L("bg.title")}</p>
            <BackgroundEditor
              background={slide.background}
              onPickImage={onPickBackground}
              testId="slides-bar-bg"
              onChange={(label, next, coalesce) =>
                onSlide(
                  label,
                  (s) => {
                    if (next) s.background = next;
                    else delete s.background;
                  },
                  coalesce,
                )
              }
            />
            {!slide.background && deck.background && <p className="mt-2 text-xs text-muted-foreground">{L("bg.inherited")}</p>}
          </div>
          <div className="flex items-end gap-2 border-t border-border pt-3">
            <Select
              label={L("transition.label")}
              showLabel
              value={slide.transition ?? "deck"}
              options={[{ value: "deck", label: L("transition.deck") }, ...TRANSITIONS.map((name) => ({ value: name, label: L(`transition.${name}`) }))]}
              onChange={(value) =>
                onSlide(L("step.transition"), (s) => {
                  if (value === "deck") delete s.transition;
                  else s.transition = value as Slide["transition"];
                })
              }
              className="min-w-0 flex-1"
            />
            <button
              type="button"
              aria-pressed={!!slide.hidden}
              onClick={() =>
                onSlide(slide.hidden ? L("step.show_slide") : L("step.hide_slide"), (s) => {
                  if (s.hidden) delete s.hidden;
                  else s.hidden = true;
                })
              }
              className={cn(
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2 text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                slide.hidden && "bg-secondary",
              )}
              data-testid="slides-bar-hide"
            >
              {slide.hidden ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
              {slide.hidden ? L("slide.is_hidden") : L("slide.hide")}
            </button>
          </div>
        </div>
      </Popover>,
    );
  }

  const texts = items.filter(hasText) as (TextElement | ShapeElement)[];
  const first = texts[0];
  const fillable = items.find((item) => item.type === "text" || item.type === "shape") as TextElement | ShapeElement | undefined;
  const line = items.find((item) => item.type === "line");
  const size = first ? (first.size ?? (first.type === "shape" ? 24 : 28)) : 0;
  const align = first ? (first.align ?? (first.type === "shape" ? "center" : "left")) : "left";
  const AlignIcon = align === "center" ? AlignCenter : align === "right" ? AlignRight : AlignLeft;

  return group(
    <>
      {first && (
        <>
          <Select
            variant="bar"
            label={L("el.font")}
            value={first.font ?? "sans"}
            options={FONTS.map((font) => ({ value: font, label: L(`font.${font}`) }))}
            onChange={(value) => set("font", value === "sans" ? undefined : value)}
            testId="slides-bar-font"
          />
          <ToolbarButton label={L("el.smaller")} icon={<Minus aria-hidden />} onClick={() => set("size", Math.max(8, Math.round(size - 2)))} className="w-7" />
          <span className="w-7 text-center text-sm tabular-nums" data-testid="slides-bar-size">
            {size}
          </span>
          <ToolbarButton
            label={L("el.bigger")}
            icon={<Plus aria-hidden />}
            onClick={() => set("size", Math.min(240, Math.round(size + 2)))}
            className="w-7"
            data-testid="slides-bar-bigger"
          />
          <ToolbarButton label={L("el.bold")} icon={<Bold aria-hidden />} active={!!first.bold} onClick={() => set("bold", !first.bold)} data-testid="slides-bar-bold" />
          <ToolbarButton label={L("el.italic")} icon={<Italic aria-hidden />} active={!!first.italic} onClick={() => set("italic", !first.italic)} />
          <ToolbarButton label={L("el.underline")} icon={<Underline aria-hidden />} active={!!first.underline} onClick={() => set("underline", !first.underline)} />
          <ColorPicker
            label={L("el.text_color")}
            value={first.color?.startsWith("#") ? first.color.toUpperCase() : ""}
            palette={ELEMENT_COLORS}
            onChange={(value) => set("color", value || undefined)}
            className={SWATCH}
            icon={<Baseline />}
          />
          <Popover
            label={L("el.align.label")}
            role="menu"
            trigger={
              <ToolbarButton
                label={L("el.align.label")}
                icon={<AlignIcon aria-hidden />}
                trailing={<ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden />}
                data-testid="slides-bar-align"
              />
            }
          >
            {(["left", "center", "right"] as const).map((value) => (
              <MenuItem
                key={value}
                label={L(`el.align.text_${value}`)}
                icon={value === "left" ? <AlignLeft aria-hidden /> : value === "center" ? <AlignCenter aria-hidden /> : <AlignRight aria-hidden />}
                checked={align === value}
                onClick={() => set("align", value)}
              />
            ))}
          </Popover>
          <ToolbarButton
            label={L("el.list_bullet")}
            icon={<List aria-hidden />}
            active={first.list === "bullet"}
            onClick={() => set("list", first.list === "bullet" ? undefined : "bullet")}
            data-testid="slides-bar-bullets"
          />
          <ToolbarButton
            label={L("el.list_number")}
            icon={<ListOrdered aria-hidden />}
            active={first.list === "number"}
            onClick={() => set("list", first.list === "number" ? undefined : "number")}
          />
        </>
      )}
      {fillable && (
        <ColorPicker
          label={L("el.fill")}
          value={fillable.fill?.startsWith("#") ? fillable.fill.toUpperCase() : ""}
          palette={ELEMENT_COLORS}
          onChange={(value) => set("fill", value || undefined)}
          className={SWATCH}
          icon={<PaintBucket />}
        />
      )}
      {line && (
        <ColorPicker
          label={L("el.line_color")}
          value={line.type === "line" && line.color?.startsWith("#") ? line.color.toUpperCase() : ""}
          palette={ELEMENT_COLORS}
          onChange={(value) =>
            each(L("step.format"), (element) => {
              if (element.type !== "line") return;
              if (value) element.color = value;
              else delete element.color;
            })
          }
          className={SWATCH}
          icon={<PenLine />}
        />
      )}
    </>,
  );
}
