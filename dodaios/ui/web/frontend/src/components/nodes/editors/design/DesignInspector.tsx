/**
 * The Visuals editor's inspector: the selected block's fields, or the page's.
 *
 * A block's words are typed here or in place on the preview (double-click);
 * its look is set here as the element's own inline style, which the design's
 * style sheet cannot override, so a change shows at once and stays put. The
 * page's panel holds what the spec holds for the whole design: how it is
 * shown (a scrolling page or a fixed artboard and its size), its ground, its
 * accent, whether it keeps one theme, and the style sheet itself.
 */
import { useId, useRef, useState, type ReactNode } from "react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  ArrowDown,
  ArrowUp,
  ArrowUpLeft,
  Copy,
  Eraser,
  ImageUp,
  Trash2,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/i18n";
import { InspectorField, NumberField, Select, ToolbarButton, ToolbarGroup } from "../controls";
import { DesignColorPicker } from "./DesignColorPicker";
import {
  ARTBOARD,
  SIZE_PRESETS,
  SPEC_COLORS,
  THEMES,
  TOKEN_COLORS,
  WEIGHTS,
  type DesignTheme,
} from "./designBlocks";
import {
  isPlainText,
  isSvgElement,
  isTextElement,
  layerKind,
  layerLabel,
  plainTextOf,
  setPlainText,
  setStyle,
  styleOf,
  type DesignSpec,
} from "./designDoc";
import { KIND_ICONS } from "./LayersPanel";

/**
 * A link the person typed, kept unless it names a scheme a page must not
 * follow. An address without a scheme (one being typed, a relative path, an
 * anchor) and http(s), mailto and tel pass; `javascript:`, `data:` and every
 * other scheme would run or load something when the link is clicked.
 */
export function safeLink(typed: string): string {
  const value = typed.trim();
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(value)?.[1]?.toLowerCase();
  if (scheme === undefined) return value;
  return ["http", "https", "mailto", "tel"].includes(scheme) ? value : "";
}

/**
 * A picture's source as the inspector may show it in the app itself: only a
 * picture embedded in the design. The design's page runs in a sandbox, this
 * preview does not, so it never loads an address from the web.
 */
export function embeddedPicture(src: string | null): string {
  return src && /^data:image\/(png|jpeg|gif|webp|avif);base64,/i.test(src) ? src : "";
}

/** A change to the selected element, made inside the editor's `apply`. */
export type ElementChange = (label: string, change: (element: Element) => void, coalesce?: string) => void;

/** A px length as a number, or null when unset or written another way (`clamp()`, `em`). */
export function pxOf(value: string): number | null {
  const found = /^(-?\d+(?:\.\d+)?)px$/.exec(value.trim());
  return found ? Number(found[1]) : null;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export interface ElementInspectorProps {
  element: Element;
  /** A stable key of the element, so typing runs merge per element. */
  pathKey: string;
  onChange: ElementChange;
  onDuplicate: () => void;
  onRemove: () => void;
  onMove: (step: -1 | 1) => void;
  onSelectParent: (() => void) | null;
  onReplaceImage: (file: File) => void;
  imageError: string;
}

export function ElementInspector({
  element,
  pathKey,
  onChange,
  onDuplicate,
  onRemove,
  onMove,
  onSelectParent,
  onReplaceImage,
  imageError,
}: ElementInspectorProps) {
  const t = useT();
  const kind = layerKind(element);
  const Icon = KIND_ICONS[kind];
  const tag = element.localName.toLowerCase();
  const svg = isSvgElement(element);
  const textual = isTextElement(element);
  const plain = isPlainText(element);
  const file = useRef<HTMLInputElement>(null);
  const style = (property: string) => styleOf(element, property);
  const setOne = (label: string, property: string, coalesce?: string) => (value: string) =>
    onChange(label, (el) => setStyle(el, property, value), coalesce);
  const pxField = (property: string, label: string, max: number) => {
    const raw = style(property);
    const value = pxOf(raw);
    return (
      <NumberField
        label={label}
        showLabel
        value={value}
        allowEmpty
        min={0}
        max={max}
        suffix="px"
        onChange={(next) => setOne(label, property)(next === null ? "" : `${next}px`)}
        className="min-w-0 flex-1"
      />
    );
  };
  const align = style("text-align");

  return (
    <div className="flex flex-col gap-5" data-testid="design-element-inspector">
      <div className="flex items-center gap-2">
        <Icon aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{t(`nodes.editor.design.kind.${kind}`)}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {tag}
            {element.getAttribute("class") ? `.${element.getAttribute("class")!.trim().split(/\s+/).join(".")}` : ""}
          </p>
        </div>
        {onSelectParent && (
          <ToolbarButton
            label={t("nodes.editor.design.select_parent")}
            icon={<ArrowUpLeft aria-hidden />}
            onClick={onSelectParent}
          />
        )}
      </div>

      <ToolbarGroup label={t("nodes.editor.design.block_actions")} className="-mt-2 flex-wrap">
        <ToolbarButton label={t("nodes.editor.design.move_up")} icon={<ArrowUp aria-hidden />} shortcut="⌥↑" onClick={() => onMove(-1)} />
        <ToolbarButton label={t("nodes.editor.design.move_down")} icon={<ArrowDown aria-hidden />} shortcut="⌥↓" onClick={() => onMove(1)} />
        <ToolbarButton label={t("nodes.editor.design.duplicate")} icon={<Copy aria-hidden />} onClick={onDuplicate} />
        <ToolbarButton label={t("nodes.editor.design.delete")} icon={<Trash2 aria-hidden />} onClick={onRemove} />
      </ToolbarGroup>

      {(textual || tag === "a" || tag === "img") && (
        <Section title={t("nodes.editor.design.content")}>
          {plain && (
            <InspectorField label={t("nodes.editor.design.text")} hint={t("nodes.editor.design.text_hint")}>
              {(id) => (
                <Textarea
                  id={id}
                  value={plainTextOf(element)}
                  rows={Math.min(8, Math.max(2, plainTextOf(element).split("\n").length + 1))}
                  onChange={(event) =>
                    onChange(t("nodes.editor.design.history.text"), (el) => setPlainText(el, event.target.value), `text:${pathKey}`)
                  }
                  data-testid="design-text"
                />
              )}
            </InspectorField>
          )}
          {textual && !plain && (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted-foreground">{t("nodes.editor.design.rich_hint")}</p>
              <p className="line-clamp-3 rounded-md border border-border bg-input px-2 py-1.5 text-sm">{layerLabel(element)}</p>
              <ToolbarButton
                showLabel
                label={t("nodes.editor.design.clear_formatting")}
                icon={<Eraser aria-hidden />}
                onClick={() =>
                  onChange(t("nodes.editor.design.clear_formatting"), (el) => setPlainText(el, plainTextOf(el)))
                }
                className="self-start"
              />
            </div>
          )}
          {tag === "a" && (
            <InspectorField label={t("nodes.editor.design.link")} hint={t("nodes.editor.design.link_hint")}>
              {(id) => (
                <Input
                  id={id}
                  value={element.getAttribute("href") ?? ""}
                  placeholder="https://"
                  spellCheck={false}
                  onChange={(event) =>
                    onChange(
                      t("nodes.editor.design.history.link"),
                      (el) => {
                        const href = safeLink(event.target.value);
                        if (href) el.setAttribute("href", href);
                        else el.removeAttribute("href");
                      },
                      `href:${pathKey}`,
                    )
                  }
                />
              )}
            </InspectorField>
          )}
          {tag === "img" && (
            <>
              <div className="overflow-hidden rounded-md border border-border bg-input">
                {embeddedPicture(element.getAttribute("src")) && (
                  <img
                    src={embeddedPicture(element.getAttribute("src"))}
                    alt=""
                    className="mx-auto max-h-40 object-contain"
                  />
                )}
              </div>
              <input
                ref={file}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(event) => {
                  const picked = event.target.files?.[0];
                  if (picked) onReplaceImage(picked);
                  event.target.value = "";
                }}
              />
              <ToolbarButton
                showLabel
                label={t("nodes.editor.design.image.replace")}
                icon={<ImageUp aria-hidden />}
                onClick={() => file.current?.click()}
                className="self-start"
              />
              {imageError && (
                <p role="alert" className="text-sm text-destructive">
                  {imageError}
                </p>
              )}
              <InspectorField label={t("nodes.editor.design.image.alt")} hint={t("nodes.editor.design.image.alt_hint")}>
                {(id) => (
                  <Input
                    id={id}
                    value={element.getAttribute("alt") ?? ""}
                    onChange={(event) =>
                      onChange(t("nodes.editor.design.history.alt"), (el) => el.setAttribute("alt", event.target.value), `alt:${pathKey}`)
                    }
                  />
                )}
              </InspectorField>
            </>
          )}
        </Section>
      )}

      <Section title={t("nodes.editor.design.look")}>
        {svg ? (
          <>
            <div className="grid grid-cols-2 gap-2">
              <InspectorField label={t("nodes.editor.design.fill")}>
                {() => (
                  <DesignColorPicker
                    label={t("nodes.editor.design.fill")}
                    value={style("fill")}
                    choices={TOKEN_COLORS}
                    onChange={setOne(t("nodes.editor.design.fill"), "fill")}
                  />
                )}
              </InspectorField>
              <InspectorField label={t("nodes.editor.design.stroke")}>
                {() => (
                  <DesignColorPicker
                    label={t("nodes.editor.design.stroke")}
                    value={style("stroke")}
                    choices={TOKEN_COLORS}
                    onChange={setOne(t("nodes.editor.design.stroke"), "stroke")}
                  />
                )}
              </InspectorField>
            </div>
            {pxField("stroke-width", t("nodes.editor.design.stroke_width"), 64)}
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              <InspectorField label={t("nodes.editor.design.color")}>
                {() => (
                  <DesignColorPicker
                    label={t("nodes.editor.design.color")}
                    value={style("color")}
                    choices={TOKEN_COLORS}
                    onChange={setOne(t("nodes.editor.design.color"), "color")}
                    testId="design-color"
                  />
                )}
              </InspectorField>
              <InspectorField label={t("nodes.editor.design.background")}>
                {() => (
                  <DesignColorPicker
                    label={t("nodes.editor.design.background")}
                    value={style("background")}
                    choices={TOKEN_COLORS}
                    onChange={setOne(t("nodes.editor.design.background"), "background")}
                  />
                )}
              </InspectorField>
            </div>
            {(textual || kind === "box" || kind === "list" || kind === "button") && (
              <>
                <div className="flex gap-2">
                  {pxField("font-size", t("nodes.editor.design.size"), 600)}
                  <Select
                    label={t("nodes.editor.design.weight")}
                    showLabel
                    value={style("font-weight")}
                    options={[
                      { value: "", label: t("nodes.editor.design.weight_default") },
                      ...WEIGHTS.map((weight) => ({ value: weight, label: t(`nodes.editor.design.weights.${weight}`) })),
                    ]}
                    onChange={setOne(t("nodes.editor.design.weight"), "font-weight")}
                    className="min-w-0 flex-1"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">{t("nodes.editor.design.align")}</span>
                  <ToolbarGroup label={t("nodes.editor.design.align")}>
                    {(
                      [
                        ["left", AlignLeft],
                        ["center", AlignCenter],
                        ["right", AlignRight],
                      ] as const
                    ).map(([value, AlignIcon]) => (
                      <ToolbarButton
                        key={value}
                        label={t(`nodes.editor.design.align_${value}`)}
                        icon={<AlignIcon aria-hidden />}
                        active={align === value}
                        onClick={() => setOne(t("nodes.editor.design.align"), "text-align")(align === value ? "" : value)}
                      />
                    ))}
                  </ToolbarGroup>
                </div>
              </>
            )}
            <div className="flex gap-2">
              {pxField("padding", t("nodes.editor.design.padding"), 400)}
              {pxField("border-radius", t("nodes.editor.design.radius"), 400)}
            </div>
          </>
        )}
        {element.getAttribute("style") && (
          <ToolbarButton
            showLabel
            label={t("nodes.editor.design.clear_style")}
            icon={<Eraser aria-hidden />}
            onClick={() => onChange(t("nodes.editor.design.clear_style"), (el) => el.removeAttribute("style"))}
            className="self-start"
          />
        )}
      </Section>
    </div>
  );
}

/* ------------------------------------------------------------------ page */

export type PageChange = (label: string, change: (draft: DesignSpec) => void, coalesce?: string) => void;

export function PageInspector({ spec, onChange }: { spec: DesignSpec; onChange: PageChange }) {
  const t = useT();
  const cssId = useId();
  const [cssOpen, setCssOpen] = useState(false);
  const canvas = spec.fit === "canvas";
  const width = spec.width ?? ARTBOARD.width;
  const height = spec.height ?? ARTBOARD.height;
  const theme: DesignTheme = spec.theme ?? "auto";
  return (
    <div className="flex flex-col gap-5" data-testid="design-page-inspector">
      <Section title={t("nodes.editor.design.page.format")}>
        <Select
          label={t("nodes.editor.design.page.fit")}
          showLabel
          value={spec.fit}
          options={[
            { value: "page", label: t("nodes.editor.design.page.fit_page"), hint: t("nodes.editor.design.page.fit_page_hint") },
            { value: "canvas", label: t("nodes.editor.design.page.fit_canvas"), hint: t("nodes.editor.design.page.fit_canvas_hint") },
          ]}
          onChange={(value) =>
            onChange(t("nodes.editor.design.page.fit"), (draft) => {
              if (value === "canvas") {
                draft.fit = "canvas";
                draft.width = draft.width ?? ARTBOARD.width;
                draft.height = draft.height ?? ARTBOARD.height;
              } else {
                draft.fit = "page";
                delete draft.width;
                delete draft.height;
              }
            })
          }
          testId="design-fit"
        />
        {canvas && (
          <>
            <div className="grid grid-cols-2 gap-1.5" role="group" aria-label={t("nodes.editor.design.page.presets")}>
              {SIZE_PRESETS.map((preset) => {
                const active = preset.width === width && preset.height === height;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      onChange(t("nodes.editor.design.page.size"), (draft) => {
                        draft.width = preset.width;
                        draft.height = preset.height;
                      })
                    }
                    className={
                      "flex flex-col items-start rounded-md border px-2 py-1.5 text-left text-sm hover:bg-secondary " +
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
                      (active ? "border-accent bg-secondary" : "border-border")
                    }
                  >
                    <span>{t(`nodes.editor.design.page.preset.${preset.id}`)}</span>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {preset.width} × {preset.height}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex gap-2">
              <NumberField
                label={t("nodes.editor.design.page.width")}
                showLabel
                value={width}
                min={ARTBOARD.min}
                max={ARTBOARD.maxWidth}
                suffix="px"
                onChange={(next) => onChange(t("nodes.editor.design.page.size"), (draft) => void (draft.width = next ?? ARTBOARD.width))}
                className="min-w-0 flex-1"
              />
              <NumberField
                label={t("nodes.editor.design.page.height")}
                showLabel
                value={height}
                min={ARTBOARD.min}
                max={ARTBOARD.maxHeight}
                suffix="px"
                onChange={(next) => onChange(t("nodes.editor.design.page.size"), (draft) => void (draft.height = next ?? ARTBOARD.height))}
                className="min-w-0 flex-1"
              />
            </div>
          </>
        )}
      </Section>

      <Section title={t("nodes.editor.design.page.colours")}>
        <InspectorField label={t("nodes.editor.design.page.background")} hint={t("nodes.editor.design.page.background_hint")}>
          {() => (
            <DesignColorPicker
              label={t("nodes.editor.design.page.background")}
              value={spec.background}
              choices={SPEC_COLORS}
              onChange={(value) => onChange(t("nodes.editor.design.page.background"), (draft) => void (draft.background = value))}
              testId="design-background"
            />
          )}
        </InspectorField>
        <InspectorField label={t("nodes.editor.design.page.accent")} hint={t("nodes.editor.design.page.accent_hint")}>
          {() => (
            <DesignColorPicker
              label={t("nodes.editor.design.page.accent")}
              value={spec.accent ?? ""}
              choices={SPEC_COLORS.filter((choice) => !["accent", "ink", "muted"].includes(choice.value))}
              onChange={(value) =>
                onChange(t("nodes.editor.design.page.accent"), (draft) => {
                  if (value) draft.accent = value;
                  else delete draft.accent;
                })
              }
              testId="design-accent"
            />
          )}
        </InspectorField>
        <Select
          label={t("nodes.editor.design.page.theme")}
          showLabel
          value={theme}
          options={THEMES.map((value) => ({ value, label: t(`nodes.editor.design.page.theme_${value}`) }))}
          onChange={(value) =>
            onChange(t("nodes.editor.design.page.theme"), (draft) => {
              if (value === "light" || value === "dark") draft.theme = value;
              else delete draft.theme;
            })
          }
          testId="design-theme"
        />
      </Section>

      <Section title={t("nodes.editor.design.page.styles")}>
        {cssOpen ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={cssId} className="text-xs text-muted-foreground">
              {t("nodes.editor.design.page.styles_hint")}
            </label>
            <Textarea
              id={cssId}
              value={spec.css}
              rows={14}
              spellCheck={false}
              className="font-mono text-xs"
              onChange={(event) => onChange(t("nodes.editor.design.history.css"), (draft) => void (draft.css = event.target.value), "css")}
              data-testid="design-css"
            />
          </div>
        ) : (
          <ToolbarButton
            showLabel
            label={t("nodes.editor.design.page.styles_open")}
            onClick={() => setCssOpen(true)}
            className="self-start"
          />
        )}
      </Section>
    </div>
  );
}
