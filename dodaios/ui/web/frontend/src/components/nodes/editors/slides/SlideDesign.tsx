/**
 * How a slide looks besides its layout, and the deck's look as a whole.
 *
 * `SlideDesign` (in the slide's inspector): its background (none, a colour,
 * a gradient or a picture, with a veil for text on a photo), its text tone
 * (light or dark, or what the background asks for), its transition, whether
 * it is shown when presenting, and its footer.
 *
 * `DeckDesign` (the toolbar's "Design" menu): ready-made looks that set the
 * theme, accent, type pairing and background at once, and each of them on
 * its own: the theme, the type pairing, the transition every slide takes and
 * the footers.
 */
import { type ReactNode } from "react";
import { Eye, EyeOff, ImagePlus, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { ColorPicker, NumberField, Select } from "../controls";
import type { Deck, Slide } from "./deckModel";
import { DECK_FONTS, FONT_STACKS, TRANSITIONS, type Background } from "./elementModel";
import { ELEMENT_COLORS } from "./ElementInspector";

/** Gradients offered with one click. */
export const GRADIENTS: readonly { from: string; to: string; angle: number }[] = [
  { from: "#0F172A", to: "#312E81", angle: 135 },
  { from: "#0B1E3A", to: "#0E4C6E", angle: 160 },
  { from: "#111827", to: "#7C2D12", angle: 135 },
  { from: "#022C22", to: "#065F46", angle: 150 },
  { from: "#FFF7ED", to: "#FCE7F3", angle: 135 },
  { from: "#EFF6FF", to: "#E0E7FF", angle: 180 },
  { from: "#F0FDF4", to: "#ECFEFF", angle: 135 },
  { from: "#FDF2F8", to: "#EDE9FE", angle: 120 },
];

/** Ready-made looks for the whole deck. */
export const PRESETS: readonly {
  id: string;
  theme: Deck["theme"];
  accent?: string;
  font?: Deck["font"];
  background?: Background;
  /** The swatch's own colours: ground, ink, accent. */
  swatch: [string, string, string];
}[] = [
  { id: "clean", theme: "light", swatch: ["#FDFDFC", "#1F2328", "#2A6FD0"] },
  { id: "midnight", theme: "dark", accent: "violet", swatch: ["#141413", "#F2F1EE", "#8B7CF6"] },
  { id: "editorial", theme: "light", accent: "#B4472B", font: "editorial", background: { color: "#F7F3EA" }, swatch: ["#F7F3EA", "#1F2328", "#B4472B"] },
  {
    id: "ocean",
    theme: "dark",
    accent: "#38BDF8",
    font: "geometric",
    background: { gradient: { from: "#0B1E3A", to: "#0E4C6E", angle: 160 } },
    swatch: ["#0E3456", "#F2F1EE", "#38BDF8"],
  },
  {
    id: "sunset",
    theme: "light",
    accent: "orange",
    font: "rounded",
    background: { gradient: { from: "#FFF7ED", to: "#FCE7F3", angle: 135 } },
    swatch: ["#FDEFEF", "#1F2328", "#D4532E"],
  },
  { id: "forest", theme: "dark", accent: "#4ADE80", font: "classic", background: { color: "#0F1F17" }, swatch: ["#0F1F17", "#F2F1EE", "#4ADE80"] },
  { id: "terminal", theme: "dark", accent: "#22C55E", font: "mono", background: { color: "#0A0A0A" }, swatch: ["#0A0A0A", "#E5E5E5", "#22C55E"] },
  { id: "bold", theme: "light", accent: "pink", font: "condensed", swatch: ["#FFFFFF", "#111111", "#C23F86"] },
  { id: "paper", theme: "light", accent: "ink", font: "serif", background: { color: "#FAF8F3" }, swatch: ["#FAF8F3", "#1F2328", "#1F2328"] },
];

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

function hex(value: string | undefined): string {
  return value?.startsWith("#") ? value.toUpperCase() : "";
}

/** A gradient or colour as a swatch's CSS. */
function swatchOf(background: Background | undefined): string {
  if (!background) return "transparent";
  if (background.gradient) return `linear-gradient(${background.gradient.angle}deg, ${background.gradient.from}, ${background.gradient.to})`;
  return background.color && background.color.startsWith("#") ? background.color : "transparent";
}

export interface BackgroundEditorProps {
  background: Background | undefined;
  onChange: (label: string, next: Background | undefined, coalesce?: string) => void;
  onPickImage: () => void;
  testId: string;
}

/** A background: none, colour, gradient or picture, and the veil over it. */
export function BackgroundEditor({ background, onChange, onPickImage, testId }: BackgroundEditorProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const kind = background?.image ? "image" : background?.gradient ? "gradient" : background?.color ? "color" : "none";
  const step = L("step.background");
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <div role="radiogroup" aria-label={L("bg.kind")} className="grid grid-cols-4 gap-1 rounded-md bg-secondary/60 p-0.5">
        {(["none", "color", "gradient", "image"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={kind === value}
            onClick={() => {
              if (value === kind) return;
              if (value === "none") onChange(step, undefined);
              else if (value === "color") onChange(step, { color: "#0F172A" });
              else if (value === "gradient") onChange(step, { gradient: { ...GRADIENTS[0] } });
              else onPickImage();
            }}
            className={cn(
              "h-7 rounded text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              kind === value ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
            data-testid={`${testId}-${value}`}
          >
            {L(`bg.${value}`)}
          </button>
        ))}
      </div>
      {kind === "color" && (
        <Row label={L("bg.color")}>
          <ColorPicker label={L("bg.color")} value={hex(background?.color)} palette={ELEMENT_COLORS} allowDefault={false} onChange={(value) => onChange(step, { ...background, color: value })} />
        </Row>
      )}
      {kind === "gradient" && background?.gradient && (
        <>
          <div className="grid grid-cols-4 gap-1.5">
            {GRADIENTS.map((gradient, i) => (
              <button
                key={i}
                type="button"
                aria-label={`${L("bg.gradient")} ${i + 1}`}
                onClick={() => onChange(step, { ...background, gradient: { ...gradient } })}
                className="h-8 rounded-md border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                style={{ background: `linear-gradient(${gradient.angle}deg, ${gradient.from}, ${gradient.to})` }}
              />
            ))}
          </div>
          <Row label={L("bg.from_to")}>
            <ColorPicker label={L("bg.from")} value={hex(background.gradient.from)} palette={ELEMENT_COLORS} allowDefault={false} onChange={(value) => onChange(step, { ...background, gradient: { ...background.gradient!, from: value } })} />
            <ColorPicker label={L("bg.to")} value={hex(background.gradient.to)} palette={ELEMENT_COLORS} allowDefault={false} onChange={(value) => onChange(step, { ...background, gradient: { ...background.gradient!, to: value } })} />
            <NumberField label={L("bg.angle")} value={background.gradient.angle} min={0} max={360} suffix="°" className="w-20" onChange={(value) => onChange(step, { ...background, gradient: { ...background.gradient!, angle: value ?? 135 } })} />
          </Row>
        </>
      )}
      {kind === "image" && background?.image && (
        <>
          <div className="relative aspect-video overflow-hidden rounded-md border border-border">
            <img src={background.image} alt="" className={cn("h-full w-full", background.fit === "contain" ? "object-contain" : "object-cover")} />
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={onPickImage}
              className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md border border-border-strong text-xs hover:bg-secondary"
            >
              <ImagePlus className="h-3.5 w-3.5" aria-hidden />
              {L("image.replace")}
            </button>
            <Select
              label={L("image.fit")}
              value={background.fit ?? "cover"}
              options={[
                { value: "cover", label: L("image.fit_cover") },
                { value: "contain", label: L("image.fit_contain") },
              ]}
              onChange={(value) => {
                const next = { ...background };
                if (value === "contain") next.fit = "contain";
                else delete next.fit;
                onChange(step, next);
              }}
              className="w-32"
            />
          </div>
        </>
      )}
      {kind !== "none" && (
        <Row label={L("bg.dim")}>
          <input
            type="range"
            min={0}
            max={90}
            step={1}
            aria-label={L("bg.dim")}
            value={background?.dim ?? 0}
            onChange={(event) => {
              const value = Number(event.target.value);
              const next = { ...background };
              if (value > 0) next.dim = value;
              else delete next.dim;
              onChange(step, next, `dim:${testId}`);
            }}
            className="w-28 accent-[hsl(var(--accent))]"
          />
          <span className="w-9 text-right text-xs tabular-nums text-muted-foreground">{background?.dim ?? 0}%</span>
        </Row>
      )}
    </div>
  );
}

export interface SlideDesignProps {
  slide: Slide;
  deck: Deck;
  onChange: (label: string, change: (slide: Slide) => void, coalesce?: string) => void;
  onPickBackground: () => void;
  onApplyBackgroundToAll: () => void;
}

export function SlideDesign({ slide, deck, onChange, onPickBackground, onApplyBackgroundToAll }: SlideDesignProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const inherited = !slide.background && !!deck.background;
  return (
    <>
      <Section title={L("bg.title")}>
        {inherited && <p className="text-xs text-muted-foreground">{L("bg.inherited")}</p>}
        <BackgroundEditor
          background={slide.background}
          onPickImage={onPickBackground}
          testId="slides-bg"
          onChange={(label, next, coalesce) =>
            onChange(
              label,
              (s) => {
                if (next) s.background = next;
                else delete s.background;
              },
              coalesce,
            )
          }
        />
        {slide.background && (
          <button
            type="button"
            onClick={onApplyBackgroundToAll}
            className="h-7 self-start rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            data-testid="slides-bg-all"
          >
            {L("bg.apply_all")}
          </button>
        )}
        <Row label={L("tone.label")}>
          <Select
            label={L("tone.label")}
            value={slide.tone ?? "auto"}
            options={[
              { value: "auto", label: L("tone.auto") },
              { value: "light", label: L("tone.light") },
              { value: "dark", label: L("tone.dark") },
            ]}
            onChange={(value) =>
              onChange(L("step.tone"), (s) => {
                if (value === "light" || value === "dark") s.tone = value;
                else delete s.tone;
              })
            }
            className="w-36"
            testId="slides-tone"
          />
        </Row>
      </Section>
      <Section title={L("slide.section")}>
        <Row label={L("transition.label")}>
          <Select
            label={L("transition.label")}
            value={slide.transition ?? "deck"}
            options={[{ value: "deck", label: L("transition.deck") }, ...TRANSITIONS.map((name) => ({ value: name, label: L(`transition.${name}`) }))]}
            onChange={(value) =>
              onChange(L("step.transition"), (s) => {
                if (value === "deck") delete s.transition;
                else s.transition = value as Slide["transition"];
              })
            }
            className="w-36"
            testId="slides-transition"
          />
        </Row>
        <Row label={L("slide.hidden")}>
          <button
            type="button"
            aria-pressed={!!slide.hidden}
            onClick={() =>
              onChange(slide.hidden ? L("step.show_slide") : L("step.hide_slide"), (s) => {
                if (s.hidden) delete s.hidden;
                else s.hidden = true;
              })
            }
            className={cn(
              "flex h-7 items-center gap-1.5 rounded-md px-2 text-xs hover:bg-secondary",
              slide.hidden ? "bg-secondary text-foreground" : "text-muted-foreground",
            )}
            data-testid="slides-hide"
          >
            {slide.hidden ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
            {slide.hidden ? L("slide.is_hidden") : L("slide.is_shown")}
          </button>
        </Row>
        <Row label={L("slide.footer")}>
          <button
            type="button"
            aria-pressed={slide.footer !== false}
            onClick={() =>
              onChange(L("step.footer"), (s) => {
                if (s.footer === false) delete s.footer;
                else s.footer = false;
              })
            }
            className={cn(
              "h-7 rounded-md px-2 text-xs hover:bg-secondary",
              slide.footer !== false ? "bg-secondary text-foreground" : "text-muted-foreground",
            )}
          >
            {slide.footer !== false ? L("slide.footer_on") : L("slide.footer_off")}
          </button>
        </Row>
      </Section>
    </>
  );
}

export interface DeckDesignProps {
  deck: Deck;
  onChange: (label: string, change: (deck: Deck) => void, coalesce?: string) => void;
  onPickBackground: () => void;
  close: () => void;
}

/** The "Design" menu: looks for the whole deck. */
export function DeckDesign({ deck, onChange, onPickBackground, close }: DeckDesignProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  return (
    <div className="flex w-[340px] flex-col gap-3 p-2" data-testid="slides-design">
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">{L("design.presets")}</p>
        <div className="grid grid-cols-3 gap-2">
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => {
                onChange(L("step.design"), (draft) => {
                  draft.theme = preset.theme;
                  if (preset.accent) draft.accent = preset.accent;
                  else delete draft.accent;
                  if (preset.font) draft.font = preset.font;
                  else delete draft.font;
                  if (preset.background) draft.background = JSON.parse(JSON.stringify(preset.background)) as Background;
                  else delete draft.background;
                });
                close();
              }}
              className="group flex flex-col gap-1 rounded-md p-1 text-left hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid={`slides-preset-${preset.id}`}
            >
              <span
                className="relative block aspect-video w-full overflow-hidden rounded border border-border"
                style={{ background: preset.background ? swatchOf(preset.background) : preset.swatch[0] }}
              >
                <span className="absolute left-[12%] top-[30%] h-[10%] w-[50%] rounded-sm" style={{ background: preset.swatch[1], fontFamily: FONT_STACKS.sans }} />
                <span className="absolute left-[12%] top-[48%] h-[6%] w-[34%] rounded-sm opacity-60" style={{ background: preset.swatch[1] }} />
                <span className="absolute left-[12%] top-[66%] h-[6%] w-[16%] rounded-sm" style={{ background: preset.swatch[2] }} />
              </span>
              <span className="truncate text-xs">{L(`design.preset.${preset.id}`)}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 border-t border-border pt-3">
        <Select
          label={L("theme.label")}
          showLabel
          value={deck.theme}
          options={(["auto", "light", "dark"] as const).map((value) => ({ value, label: L(`theme.${value}`) }))}
          onChange={(value) => onChange(L("step.theme"), (draft) => void (draft.theme = value as Deck["theme"]))}
          testId="slides-design-theme"
        />
        <Select
          label={L("design.font")}
          showLabel
          value={deck.font ?? "sans"}
          options={DECK_FONTS.map((font) => ({ value: font, label: L(`deckfont.${font}`) }))}
          onChange={(value) =>
            onChange(L("step.font"), (draft) => {
              if (value === "sans") delete draft.font;
              else draft.font = value as Deck["font"];
            })
          }
          testId="slides-design-font"
        />
        <Select
          label={L("design.transition")}
          showLabel
          value={deck.transition ?? "default"}
          options={[{ value: "default", label: L("transition.default") }, ...TRANSITIONS.map((name) => ({ value: name, label: L(`transition.${name}`) }))]}
          onChange={(value) =>
            onChange(L("step.transition"), (draft) => {
              if (value === "default") delete draft.transition;
              else draft.transition = value as Deck["transition"];
            })
          }
          testId="slides-design-transition"
        />
        <Select
          label={L("design.footer")}
          showLabel
          value={deck.footer === false ? "off" : "on"}
          options={[
            { value: "on", label: L("slide.footer_on") },
            { value: "off", label: L("slide.footer_off") },
          ]}
          onChange={(value) =>
            onChange(L("step.footer"), (draft) => {
              if (value === "off") draft.footer = false;
              else delete draft.footer;
            })
          }
        />
      </div>
      <div className="border-t border-border pt-3">
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">{L("design.background")}</p>
          {deck.background && (
            <button type="button" aria-label={L("bg.none")} onClick={() => onChange(L("step.background"), (draft) => void delete draft.background)} className="grid h-6 w-6 place-items-center rounded hover:bg-secondary">
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </div>
        <BackgroundEditor
          background={deck.background}
          onPickImage={onPickBackground}
          testId="slides-deck-bg"
          onChange={(label, next, coalesce) =>
            onChange(
              label,
              (draft) => {
                if (next) draft.background = next;
                else delete draft.background;
              },
              coalesce,
            )
          }
        />
      </div>
    </div>
  );
}
