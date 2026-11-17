/**
 * The bar above the slide: the few settings used most, where the eye is.
 *
 * With a text box or a shape selected: font, size, bold, italic, underline,
 * text colour, alignment, list and fill. With other elements: fill or line
 * colour, and arranging. With nothing selected: the slide's layout, its
 * background, its transition and whether it is shown when presenting. The
 * inspector beside the slide holds every setting; this bar only repeats the
 * common ones.
 */
import { type ReactNode } from "react";
import { AlignCenter, AlignLeft, AlignRight, Bold, BringToFront, EyeOff, Eye, Italic, LayoutTemplate, List, ListOrdered, Minus, PaintBucket, Plus, SendToBack, Underline } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { ColorPicker, Popover, Select, ToolbarButton } from "../controls";
import type { Deck, Layout, Slide } from "./deckModel";
import { FONTS, hasText, TRANSITIONS, type ShapeElement, type SlideElement, type TextElement } from "./elementModel";
import { ELEMENT_COLORS } from "./ElementInspector";
import { LayoutGlyph, LayoutPicker } from "./LayoutPicker";
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
  onOrder: (how: "front" | "back") => void;
  onPickBackground: () => void;
}

function Divider() {
  return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border" />;
}

function Press({ on, label, onClick, children, testId }: { on?: boolean; label: string; onClick: () => void; children: ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={on}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:h-4 [&_svg]:w-4",
        on && "bg-secondary text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function FormatBar({ slide, deck, elements, selected, onElements, onSlide, onLayout, onOrder, onPickBackground }: FormatBarProps) {
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

  const shell = (children: ReactNode) => (
    <div
      className="flex h-10 shrink-0 items-center gap-0.5 overflow-x-auto border-b border-border bg-background px-3"
      role="toolbar"
      aria-label={L("format.label")}
      data-testid="slides-format-bar"
    >
      {children}
    </div>
  );

  if (!items.length) {
    return shell(
      <>
        <Popover
          label={L("layout.change")}
          trigger={
            <button type="button" className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs hover:bg-secondary" data-testid="slides-bar-layout">
              <LayoutTemplate className="h-4 w-4 text-muted-foreground" aria-hidden />
              <LayoutGlyph layout={slide.layout} className="h-[14px] w-[25px] border border-border" />
              {L(`layout.${slide.layout}`)}
            </button>
          }
        >
          {(close) => (
            <div className="w-72 p-1">
              <LayoutPicker
                current={slide.layout}
                onPick={(layout) => {
                  close();
                  onLayout(layout);
                }}
              />
            </div>
          )}
        </Popover>
        <Divider />
        <Popover
          label={L("bg.title")}
          trigger={
            <button type="button" className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs hover:bg-secondary" data-testid="slides-bar-background">
              <PaintBucket className="h-4 w-4 text-muted-foreground" aria-hidden />
              {L("bg.title")}
            </button>
          }
        >
          <div className="w-72 p-2">
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
        </Popover>
        <Divider />
        <Select
          label={L("transition.label")}
          value={slide.transition ?? "deck"}
          options={[{ value: "deck", label: L("transition.deck") }, ...TRANSITIONS.map((name) => ({ value: name, label: L(`transition.${name}`) }))]}
          onChange={(value) =>
            onSlide(L("step.transition"), (s) => {
              if (value === "deck") delete s.transition;
              else s.transition = value as Slide["transition"];
            })
          }
          className="w-36"
        />
        <Divider />
        <Press
          on={!!slide.hidden}
          label={slide.hidden ? L("slide.is_hidden") : L("slide.hide")}
          onClick={() =>
            onSlide(slide.hidden ? L("step.show_slide") : L("step.hide_slide"), (s) => {
              if (s.hidden) delete s.hidden;
              else s.hidden = true;
            })
          }
          testId="slides-bar-hide"
        >
          {slide.hidden ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
        </Press>
        <span className="ml-2 truncate text-xs text-muted-foreground">{L("format.hint")}</span>
      </>,
    );
  }

  const texts = items.filter(hasText) as (TextElement | ShapeElement)[];
  const first = texts[0];
  const fillable = items.find((item) => item.type === "text" || item.type === "shape") as TextElement | ShapeElement | undefined;
  const line = items.find((item) => item.type === "line");

  return shell(
    <>
      {first && (
        <>
          <Select
            label={L("el.font")}
            value={first.font ?? "sans"}
            options={FONTS.map((font) => ({ value: font, label: L(`font.${font}`) }))}
            onChange={(value) => set("font", value === "sans" ? undefined : value)}
            className="w-36"
            testId="slides-bar-font"
          />
          <div className="ml-1 flex items-center rounded-md border border-border-strong">
            <button
              type="button"
              aria-label={L("el.smaller")}
              title={L("el.smaller")}
              className="grid h-7 w-6 place-items-center text-muted-foreground hover:text-foreground"
              onClick={() => set("size", Math.max(8, Math.round((first.size ?? (first.type === "shape" ? 24 : 28)) - 2)))}
            >
              <Minus className="h-3.5 w-3.5" aria-hidden />
            </button>
            <span className="w-8 text-center text-xs tabular-nums" data-testid="slides-bar-size">
              {first.size ?? (first.type === "shape" ? 24 : 28)}
            </span>
            <button
              type="button"
              aria-label={L("el.bigger")}
              title={L("el.bigger")}
              className="grid h-7 w-6 place-items-center text-muted-foreground hover:text-foreground"
              onClick={() => set("size", Math.min(240, Math.round((first.size ?? (first.type === "shape" ? 24 : 28)) + 2)))}
              data-testid="slides-bar-bigger"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
          <Divider />
          <Press on={!!first.bold} label={L("el.bold")} onClick={() => set("bold", !first.bold)} testId="slides-bar-bold">
            <Bold aria-hidden />
          </Press>
          <Press on={!!first.italic} label={L("el.italic")} onClick={() => set("italic", !first.italic)}>
            <Italic aria-hidden />
          </Press>
          <Press on={!!first.underline} label={L("el.underline")} onClick={() => set("underline", !first.underline)}>
            <Underline aria-hidden />
          </Press>
          <ColorPicker label={L("el.text_color")} value={first.color?.startsWith("#") ? first.color.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("color", value || undefined)} className="ml-1 h-7" />
          <Divider />
          {(["left", "center", "right"] as const).map((align) => (
            <Press key={align} on={(first.align ?? (first.type === "shape" ? "center" : "left")) === align} label={L(`el.align.text_${align}`)} onClick={() => set("align", align)}>
              {align === "left" ? <AlignLeft aria-hidden /> : align === "center" ? <AlignCenter aria-hidden /> : <AlignRight aria-hidden />}
            </Press>
          ))}
          <Press on={first.list === "bullet"} label={L("el.list_bullet")} onClick={() => set("list", first.list === "bullet" ? undefined : "bullet")} testId="slides-bar-bullets">
            <List aria-hidden />
          </Press>
          <Press on={first.list === "number"} label={L("el.list_number")} onClick={() => set("list", first.list === "number" ? undefined : "number")}>
            <ListOrdered aria-hidden />
          </Press>
          <Divider />
        </>
      )}
      {fillable && (
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">{L("el.fill")}</span>
          <ColorPicker label={L("el.fill")} value={fillable.fill?.startsWith("#") ? fillable.fill.toUpperCase() : ""} palette={ELEMENT_COLORS} onChange={(value) => set("fill", value || undefined)} className="h-7" />
        </div>
      )}
      {line && (
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">{L("el.line_color")}</span>
          <ColorPicker
            label={L("el.line_color")}
            value={line.type === "line" && line.color?.startsWith("#") ? line.color.toUpperCase() : ""}
            palette={ELEMENT_COLORS}
            onChange={(value) => each(L("step.format"), (element) => {
              if (element.type !== "line") return;
              if (value) element.color = value;
              else delete element.color;
            })}
            className="h-7"
          />
        </div>
      )}
      <Divider />
      <ToolbarButton label={L("el.order.front")} icon={<BringToFront aria-hidden />} onClick={() => onOrder("front")} className="h-7 w-7" />
      <ToolbarButton label={L("el.order.back")} icon={<SendToBack aria-hidden />} onClick={() => onOrder("back")} className="h-7 w-7" />
    </>,
  );
}
