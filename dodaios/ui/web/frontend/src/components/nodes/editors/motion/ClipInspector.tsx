/**
 * The video editor's inspector: everything about the picked piece, and the
 * clip's own settings when nothing is picked.
 *
 * One panel per kind of thing on the timeline: a piece of video on the main
 * track, a text layer, a picture or video on top, a sound, a caption line.
 * (A card on the main track keeps the card inspector, `SceneInspector`.)
 *
 * Moving pictures: when a piece has keys, a change to zoom, position,
 * rotation or opacity is written into the key at the playhead (one is made
 * when there is none), as an editor of moving pictures does it; without keys
 * the change is the piece's one fixed value. Every change is one undo step;
 * a slider's drag is one step (`coalesce`).
 */
import { useState, type ReactNode } from "react";
import { Diamond, Loader2, Scissors, Trash2, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ColorPicker, InspectorField, NumberField, Select } from "../controls";
import { poseAt, removeKey, setKey, type Pose } from "./clipModel";
import { formatClock, type ClipFormat, type Look, type MediaEntry, type MotionSpec, type Scene, type Timing, type Track, type TrackItem } from "./motionModel";

export const FILTERS = ["none", "vivid", "warm", "cool", "mono", "fade", "noir", "film"] as const;
export const TEXT_STYLES = ["title", "subtitle", "body", "label", "caption", "quote"] as const;
export const ENTRANCES = ["rise", "fade", "pop", "slide", "zoom", "type", "none"] as const;
export const EXITS = ["fade", "rise", "pop", "slide", "zoom", "none"] as const;
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

/** The platforms a format is made for: one pick sets the format the export keeps. */
export const PLATFORM_PRESETS: { id: string; format: ClipFormat }[] = [
  { id: "shorts", format: "tall" },
  { id: "youtube", format: "wide" },
  { id: "feed", format: "portrait" },
  { id: "square", format: "square" },
];

export type Change<T> = (change: (draft: T) => void, label: string, coalesce?: string) => void;

/* ------------------------------------------------------------- pieces */

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A number with a slider: dragged for feel, typed for precision. */
function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  suffix,
  onChange,
  testId,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  onChange: (value: number, final: boolean) => void;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          aria-label={label}
          onChange={(event) => onChange(Number(event.target.value), false)}
          onPointerUp={(event) => onChange(Number((event.target as HTMLInputElement).value), true)}
          className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--accent)]"
          data-testid={testId}
        />
        <NumberField
          label={label}
          value={Math.round(value * 100) / 100}
          min={min}
          max={max}
          step={step}
          suffix={suffix}
          onChange={(next) => next !== null && onChange(next, true)}
          className="w-[84px]"
        />
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange, testId }: { label: string; checked: boolean; onChange: (on: boolean) => void; testId?: string }) {
  return (
    <label className="flex items-center justify-between gap-2 text-sm">
      <span>{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} data-testid={testId} />
    </label>
  );
}

/* ------------------------------------------------------------- shared sections */

/** Volume, mute and fades of anything with sound. */
function SoundSection<T extends Timing>({ value, change, prefix, extra }: { value: T; change: Change<T>; prefix: string; extra?: ReactNode }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  return (
    <Section title={k("sound")}>
      <Slider
        label={k("volume")}
        value={Math.round((value.volume ?? 1) * 100)}
        min={0}
        max={100}
        suffix="%"
        onChange={(v, final) =>
          change(
            (d) => {
              if (v === 100) delete d.volume;
              else d.volume = v / 100;
            },
            k("volume"),
            final ? undefined : `${prefix}-volume`,
          )
        }
        testId="clip-volume"
      />
      <Toggle label={k("mute")} checked={!!value.muted} onChange={(on) => change((d) => void (on ? (d.muted = true) : delete d.muted), k("mute"))} testId="clip-mute" />
      <div className="grid grid-cols-2 gap-2">
        <NumberField label={k("fadeIn")} showLabel value={value.fade_in ?? 0} min={0} max={10} step={0.1} decimals={1} suffix="s" onChange={(v) => change((d) => void (v ? (d.fade_in = v) : delete d.fade_in), k("fadeIn"))} />
        <NumberField label={k("fadeOut")} showLabel value={value.fade_out ?? 0} min={0} max={10} step={0.1} decimals={1} suffix="s" onChange={(v) => change((d) => void (v ? (d.fade_out = v) : delete d.fade_out), k("fadeOut"))} />
      </div>
      {extra}
    </Section>
  );
}

/** Where the piece starts in its source, how long and how fast it runs. */
function TimingSection<T extends Timing & { seconds: number }>({
  value,
  entry,
  change,
  longest,
  start,
  onStart,
}: {
  value: T;
  entry?: MediaEntry;
  change: Change<T>;
  longest: number;
  start?: number;
  onStart?: (start: number) => void;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const media = entry && entry.kind !== "image";
  return (
    <Section title={k("timing")}>
      <div className="grid grid-cols-2 gap-2">
        {onStart && <NumberField label={k("start")} showLabel value={start ?? 0} min={0} step={0.1} decimals={2} suffix="s" onChange={(v) => v !== null && onStart(v)} />}
        <NumberField
          label={k("length")}
          showLabel
          value={value.seconds}
          min={0.1}
          max={longest}
          step={0.1}
          decimals={2}
          suffix="s"
          onChange={(v) => v !== null && change((d) => void (d.seconds = Math.min(longest, v)), k("length"))}
        />
        {media && (
          <NumberField
            label={k("in")}
            showLabel
            value={value.in ?? 0}
            min={0}
            max={Math.max(0, (entry?.seconds ?? 0) - 0.1)}
            step={0.1}
            decimals={2}
            suffix="s"
            onChange={(v) => change((d) => void (v ? (d.in = v) : delete d.in), k("in"))}
          />
        )}
        {media && (
          <Select
            label={k("speed")}
            showLabel
            value={String(value.speed ?? 1)}
            options={SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))}
            onChange={(v) =>
              change((d) => {
                const next = Number(v);
                const before = d.speed ?? 1;
                // The same part of the source plays, faster or slower.
                d.seconds = Math.max(0.1, Math.round(((d.seconds * before) / next) * 1000) / 1000);
                if (next === 1) delete d.speed;
                else d.speed = next;
              }, k("speed"))
            }
            testId="clip-speed"
          />
        )}
      </div>
      {media && entry && <p className="text-xs text-muted-foreground">{fill(k("source"), { length: formatClock(entry.seconds) })}</p>}
    </Section>
  );
}

/** Filter and colour sliders. */
function LookSection<T extends Look>({ value, change, prefix }: { value: T; change: Change<T>; prefix: string }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const color = value.color ?? {};
  const setColor = (name: "brightness" | "contrast" | "saturation" | "warmth", v: number, final: boolean) =>
    change(
      (d) => {
        const next = { ...(d.color ?? {}), [name]: v };
        if (!v) delete next[name];
        if (Object.values(next).some(Boolean)) d.color = next;
        else delete d.color;
      },
      k(name),
      final ? undefined : `${prefix}-${name}`,
    );
  return (
    <Section title={k("look")}>
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={k("filter")}>
        {FILTERS.map((name) => (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={(value.filter ?? "none") === name}
            onClick={() => change((d) => void (name === "none" ? delete d.filter : (d.filter = name)), k("filter"))}
            className={cn(
              "rounded-md border px-2 py-1 text-xs",
              (value.filter ?? "none") === name ? "border-accent bg-accent/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground",
            )}
            data-testid={`clip-filter-${name}`}
          >
            {t(`nodes.editor.motion.video.filters.${name}`)}
          </button>
        ))}
      </div>
      {(["brightness", "contrast", "saturation", "warmth"] as const).map((name) => (
        <Slider key={name} label={k(name)} value={color[name] ?? 0} min={-100} max={100} onChange={(v, final) => setColor(name, v, final)} />
      ))}
    </Section>
  );
}

/**
 * Zoom, position, rotation and opacity. With keys, a change is written into
 * the key at the playhead; `local` is the playhead's time inside the piece.
 */
function MotionSection<T extends Look & { seconds: number }>({
  value,
  change,
  local,
  prefix,
  offsets,
}: {
  value: T;
  change: Change<T>;
  local: number;
  prefix: string;
  /** Track items: x/y keys move the layer from its place (an offset). */
  offsets?: boolean;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const inside = local >= 0 && local <= value.seconds + 1e-6;
  const keyed = !!value.keys?.length;
  const pose = poseAt(value, Math.max(0, Math.min(value.seconds, local)));
  const onKey = value.keys?.some((key) => Math.abs(key.t - local) < 0.02) ?? false;
  const set = (field: keyof Pose, v: number, final: boolean) =>
    change(
      (d) => {
        if (keyed && inside) setKey(d, local, { [field]: v });
        else if (field === "zoom" || field === "opacity") {
          if (v === 1) delete d[field];
          else d[field] = v;
        } else if (v === 0) delete d[field];
        else d[field] = v;
      },
      k(field === "rotate" ? "rotate" : field),
      final ? undefined : `${prefix}-${field}`,
    );
  const fields: { field: keyof Pose; min: number; max: number; step: number; scale: number; suffix: string; show: boolean }[] = [
    { field: "zoom", min: 10, max: 500, step: 1, scale: 100, suffix: "%", show: true },
    { field: "x", min: -100, max: 100, step: 1, scale: 1, suffix: "%", show: !offsets || keyed },
    { field: "y", min: -100, max: 100, step: 1, scale: 1, suffix: "%", show: !offsets || keyed },
    { field: "rotate", min: -180, max: 180, step: 1, scale: 1, suffix: "°", show: true },
    { field: "opacity", min: 0, max: 100, step: 1, scale: 100, suffix: "%", show: true },
  ];
  return (
    <Section
      title={k("motion")}
      action={
        inside && (
          <Button
            size="sm"
            variant={onKey ? "secondary" : "outline"}
            className="h-7 gap-1 px-2 text-xs"
            onClick={() =>
              change((d) => {
                if (onKey) removeKey(d, local);
                else setKey(d, local, poseAt(d, local));
              }, k(onKey ? "removeKey" : "addKey"))
            }
            data-testid="clip-key"
          >
            <Diamond className={cn("h-3 w-3", onKey && "fill-current")} aria-hidden />
            {k(onKey ? "removeKey" : "addKey")}
          </Button>
        )
      }
    >
      {fields
        .filter((f) => f.show)
        .map((f) => (
          <Slider
            key={f.field}
            label={offsets && (f.field === "x" || f.field === "y") ? k(`offset_${f.field}`) : k(f.field)}
            value={Math.round(pose[f.field] * f.scale * 100) / 100}
            min={f.min}
            max={f.max}
            step={f.step}
            suffix={f.suffix}
            onChange={(v, final) => set(f.field, v / f.scale, final)}
            testId={`clip-${f.field}`}
          />
        ))}
      {keyed && (
        <div className="flex flex-wrap gap-1" aria-label={k("keys")}>
          {value.keys!.map((key) => (
            <span key={key.t} className={cn("rounded border px-1.5 py-0.5 text-[10px] tabular-nums", Math.abs(key.t - local) < 0.02 ? "border-accent text-foreground" : "border-border text-muted-foreground")}>
              ◆ {key.t.toFixed(2)}s
            </span>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">{keyed ? k("keysHint") : k("noKeysHint")}</p>
    </Section>
  );
}

function CropSection<T extends Look>({ value, change, prefix }: { value: T; change: Change<T>; prefix: string }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const crop = value.crop ?? { l: 0, t: 0, r: 0, b: 0 };
  return (
    <Section title={k("crop")}>
      <div className="grid grid-cols-2 gap-2">
        {(["l", "t", "r", "b"] as const).map((side) => (
          <NumberField
            key={side}
            label={k(`crop_${side}`)}
            showLabel
            value={Math.round(crop[side] * 100)}
            min={0}
            max={45}
            suffix="%"
            onChange={(v) =>
              change(
                (d) => {
                  const next = { ...(d.crop ?? { l: 0, t: 0, r: 0, b: 0 }), [side]: (v ?? 0) / 100 };
                  if (Object.values(next).some(Boolean)) d.crop = next;
                  else delete d.crop;
                },
                k("crop"),
                `${prefix}-crop`,
              )
            }
          />
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------- panels */

export function VideoPieceInspector({
  scene,
  index,
  entry,
  spec,
  local,
  change,
  onRemoveSilences,
  busy,
  onSplit,
  onRemove,
}: {
  scene: Scene;
  index: number;
  entry?: MediaEntry;
  spec: MotionSpec;
  local: number;
  change: Change<Scene>;
  onRemoveSilences: () => void;
  busy: boolean;
  onSplit: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const longest = entry && entry.kind === "video" ? Math.max(0.1, (entry.seconds - (scene.in ?? 0)) / (scene.speed ?? 1)) : 3600;
  const prefix = `scene-${scene.id ?? index}`;
  void spec;
  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-video">
      <Header title={entry?.name ?? k("missing")} subtitle={fill(k("pieceN"), { n: index + 1 })} onSplit={onSplit} onRemove={onRemove} />
      <TimingSection value={scene} entry={entry} change={change} longest={longest} />
      {entry?.audio && (
        <SoundSection
          value={scene}
          change={change}
          prefix={prefix}
          extra={
            <Button size="sm" variant="outline" className="gap-1.5" onClick={onRemoveSilences} disabled={busy} data-testid="clip-remove-silences">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
              {k("removeSilences")}
            </Button>
          }
        />
      )}
      <Section title={k("frame")}>
        <Select
          label={k("fit")}
          showLabel
          value={scene.fit ?? "cover"}
          options={[
            { value: "cover", label: k("fitCover") },
            { value: "contain", label: k("fitContain") },
          ]}
          onChange={(v) => change((d) => void (v === "cover" ? delete d.fit : (d.fit = "contain")), k("fit"))}
        />
      </Section>
      <MotionSection value={scene} change={change} local={local} prefix={prefix} />
      <CropSection value={scene} change={change} prefix={prefix} />
      <LookSection value={scene} change={change} prefix={prefix} />
    </div>
  );
}

function Header({ title, subtitle, onSplit, onRemove }: { title: string; subtitle: string; onSplit?: () => void; onRemove: () => void }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-sm font-semibold" title={title}>
          {title}
        </h2>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </div>
      {onSplit && (
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onSplit} aria-label={k("split")} title={`${k("split")} (S)`}>
          <Scissors className="h-3.5 w-3.5" aria-hidden />
        </Button>
      )}
      <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onRemove} aria-label={k("delete")} title={`${k("delete")} (Del)`}>
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </div>
  );
}

export function ItemInspector({
  item,
  track,
  entry,
  local,
  change,
  onStart,
  onSplit,
  onRemove,
}: {
  item: TrackItem;
  track: Track;
  entry?: MediaEntry;
  local: number;
  change: Change<TrackItem>;
  onStart: (start: number) => void;
  onSplit: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const prefix = `item-${item.id}`;
  const longest = entry && entry.kind !== "image" ? Math.max(0.1, (entry.seconds - (item.in ?? 0)) / (item.speed ?? 1)) : 3600;
  // An item's look fields are the same as a piece's; only a text's colour is a CSS colour.
  const look = item as unknown as Look & { seconds: number };
  const lookChange = change as unknown as Change<Look & { seconds: number }>;
  if (track.kind === "text") {
    return (
      <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-text">
        <Header title={item.text?.split("\n")[0] || k("textLayer")} subtitle={k("textLayer")} onSplit={onSplit} onRemove={onRemove} />
        <Section title={k("text")}>
          <InspectorField label={k("text")}>
            {(id) => (
              <Textarea
                id={id}
                rows={3}
                value={item.text ?? ""}
                maxLength={300}
                onChange={(event) => {
                  const next = event.target.value;
                  change((d) => void (d.text = next), k("text"), `${prefix}-text`);
                }}
                className="min-h-[64px] text-sm"
                data-testid="clip-text"
              />
            )}
          </InspectorField>
          <div className="grid grid-cols-2 gap-2">
            <Select label={k("style")} showLabel value={item.style ?? "title"} options={TEXT_STYLES.map((s) => ({ value: s, label: t(`nodes.editor.motion.video.styles.${s}`) }))} onChange={(v) => change((d) => void ((d.style = v), delete d.size), k("style"))} testId="clip-text-style" />
            <NumberField label={k("size")} showLabel value={item.size ?? null} allowEmpty min={12} max={320} onChange={(v) => change((d) => void (v === null ? delete d.size : (d.size = v)), k("size"))} suffix="px" />
            <Select
              label={k("background")}
              showLabel
              value={item.bg ?? "shadow"}
              options={["shadow", "box", "pill", "none"].map((s) => ({ value: s, label: t(`nodes.editor.motion.video.backs.${s}`) }))}
              onChange={(v) => change((d) => void (d.bg = v), k("background"))}
            />
            <Select label={k("font")} showLabel value={item.font ?? "sans"} options={["sans", "serif", "mono"].map((s) => ({ value: s, label: t(`nodes.editor.motion.video.fonts.${s}`) }))} onChange={(v) => change((d) => void (v === "sans" ? delete d.font : (d.font = v)), k("font"))} />
            <Select label={k("align")} showLabel value={item.align ?? "center"} options={["center", "left", "right"].map((s) => ({ value: s, label: t(`nodes.editor.motion.video.aligns.${s}`) }))} onChange={(v) => change((d) => void (v === "center" ? delete d.align : (d.align = v)), k("align"))} />
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">{k("color")}</span>
              <ColorPicker label={k("color")} value={typeof item.color === "string" && /^#/.test(item.color) ? item.color : ""} onChange={(hex) => change((d) => void (hex ? (d.color = hex) : delete d.color), k("color"))} />
            </div>
          </div>
        </Section>
        <Section title={k("animation")}>
          <div className="grid grid-cols-2 gap-2">
            <Select label={k("entrance")} showLabel value={item.anim ?? "rise"} options={ENTRANCES.map((s) => ({ value: s, label: t(`nodes.editor.motion.video.anims.${s}`) }))} onChange={(v) => change((d) => void (d.anim = v), k("entrance"))} testId="clip-anim" />
            <Select label={k("exit")} showLabel value={item.out ?? "fade"} options={EXITS.map((s) => ({ value: s, label: t(`nodes.editor.motion.video.anims.${s}`) }))} onChange={(v) => change((d) => void (d.out = v), k("exit"))} />
          </div>
        </Section>
        <PlaceSection item={item} change={change} />
        <TimingSection value={item} change={change} longest={3600} start={item.start} onStart={onStart} />
        <MotionSection value={look} change={lookChange} local={local} prefix={prefix} offsets />
      </div>
    );
  }
  if (track.kind === "audio") {
    return (
      <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-audio">
        <Header title={entry?.name ?? k("missing")} subtitle={k("soundLayer")} onSplit={onSplit} onRemove={onRemove} />
        <TimingSection value={item} entry={entry} change={change} longest={longest} start={item.start} onStart={onStart} />
        <SoundSection
          value={item}
          change={change}
          prefix={prefix}
          extra={<Toggle label={k("duck")} checked={!!item.duck} onChange={(on) => change((d) => void (on ? (d.duck = true) : delete d.duck), k("duck"))} testId="clip-duck" />}
        />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-overlay">
      <Header title={entry?.name ?? k("missing")} subtitle={k("overlayLayer")} onSplit={onSplit} onRemove={onRemove} />
      <PlaceSection item={item} change={change} withWidth />
      <Section title={k("animation")}>
        <div className="grid grid-cols-2 gap-2">
          <Select label={k("entrance")} showLabel value={item.anim ?? "fade"} options={ENTRANCES.filter((a) => a !== "type").map((s) => ({ value: s, label: t(`nodes.editor.motion.video.anims.${s}`) }))} onChange={(v) => change((d) => void (d.anim = v), k("entrance"))} />
          <Select label={k("exit")} showLabel value={item.out ?? "fade"} options={EXITS.map((s) => ({ value: s, label: t(`nodes.editor.motion.video.anims.${s}`) }))} onChange={(v) => change((d) => void (d.out = v), k("exit"))} />
        </div>
      </Section>
      <TimingSection value={item} entry={entry} change={change} longest={longest} start={item.start} onStart={onStart} />
      {entry?.audio && <SoundSection value={item} change={change} prefix={prefix} />}
      <MotionSection value={look} change={lookChange} local={local} prefix={prefix} offsets />
      <CropSection value={look} change={lookChange} prefix={prefix} />
      <LookSection value={look} change={lookChange} prefix={prefix} />
    </div>
  );
}

/** Where a layer stands: its centre in percent of the frame (and an overlay's width). */
function PlaceSection({ item, change, withWidth }: { item: TrackItem; change: Change<TrackItem>; withWidth?: boolean }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  return (
    <Section title={k("place")}>
      <Slider label={k("centerX")} value={item.x ?? 50} min={0} max={100} suffix="%" onChange={(v, final) => change((d) => void (d.x = v), k("place"), final ? undefined : `item-${item.id}-x`)} />
      <Slider label={k("centerY")} value={item.y ?? 50} min={0} max={100} suffix="%" onChange={(v, final) => change((d) => void (d.y = v), k("place"), final ? undefined : `item-${item.id}-y`)} />
      {withWidth && (
        <>
          <Slider label={k("width")} value={item.w ?? 40} min={5} max={100} suffix="%" onChange={(v, final) => change((d) => void (d.w = v), k("width"), final ? undefined : `item-${item.id}-w`)} />
          <Slider label={k("radius")} value={item.radius ?? 0} min={0} max={50} suffix="px" onChange={(v, final) => change((d) => void (v ? (d.radius = v) : delete d.radius), k("radius"), final ? undefined : `item-${item.id}-r`)} />
        </>
      )}
      <p className="text-xs text-muted-foreground">{k("dragHint")}</p>
    </Section>
  );
}

export function CaptionInspector({
  spec,
  index,
  changeSpec,
  onRemove,
}: {
  spec: MotionSpec;
  index: number | null;
  changeSpec: Change<MotionSpec>;
  onRemove: () => void;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const captions = spec.captions;
  if (!captions) return null;
  const line = index !== null ? captions.items[index] : undefined;
  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-caption">
      {line && index !== null && (
        <>
          <Header title={line.text} subtitle={fill(k("captionN"), { n: index + 1 })} onRemove={onRemove} />
          <Section title={k("caption")}>
            <InspectorField label={k("text")}>
              {(id) => (
                <Input
                  id={id}
                  value={line.text}
                  maxLength={200}
                  onChange={(event) => {
                    const next = event.target.value;
                    changeSpec(
                      (d) => {
                        const target = d.captions?.items[index];
                        if (!target) return;
                        // Changed words lose their spoken times; the line spreads them evenly.
                        if (next.split(/\s+/).filter(Boolean).length !== target.text.split(/\s+/).filter(Boolean).length) delete target.words;
                        target.text = next;
                      },
                      k("caption"),
                      `caption-${index}`,
                    );
                  }}
                  className="h-8 text-sm"
                  data-testid="clip-caption-text"
                />
              )}
            </InspectorField>
            <div className="grid grid-cols-2 gap-2">
              <NumberField label={k("start")} showLabel value={line.start} min={0} step={0.1} decimals={2} suffix="s" onChange={(v) => v !== null && changeSpec((d) => void (d.captions!.items[index].start = Math.min(v, d.captions!.items[index].end - 0.1)), k("caption"))} />
              <NumberField label={k("end")} showLabel value={line.end} min={0} step={0.1} decimals={2} suffix="s" onChange={(v) => v !== null && changeSpec((d) => void (d.captions!.items[index].end = Math.max(v, d.captions!.items[index].start + 0.1)), k("caption"))} />
            </div>
          </Section>
        </>
      )}
      <CaptionStyle spec={spec} changeSpec={changeSpec} />
    </div>
  );
}

export function CaptionStyle({ spec, changeSpec }: { spec: MotionSpec; changeSpec: Change<MotionSpec> }) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const captions = spec.captions;
  if (!captions) return null;
  return (
    <Section title={k("captionStyle")}>
      <div className="grid grid-cols-2 gap-1.5">
        {(["karaoke", "bold", "clean", "boxed", "none"] as const).map((style) => (
          <button
            key={style}
            type="button"
            onClick={() => changeSpec((d) => void (d.captions!.style = style), k("captionStyle"))}
            className={cn(
              "rounded-md border px-2 py-1.5 text-xs",
              captions.style === style ? "border-accent bg-accent/15" : "border-border text-muted-foreground hover:text-foreground",
            )}
            aria-pressed={captions.style === style}
            data-testid={`clip-caption-style-${style}`}
          >
            {t(`nodes.editor.motion.video.captionStyles.${style}`)}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Select label={k("position")} showLabel value={captions.position} options={["bottom", "middle", "top"].map((s) => ({ value: s, label: t(`nodes.editor.motion.video.positions.${s}`) }))} onChange={(v) => changeSpec((d) => void (d.captions!.position = v as typeof captions.position), k("position"))} />
        <Select label={k("size")} showLabel value={captions.size} options={["s", "m", "l"].map((s) => ({ value: s, label: t(`nodes.editor.motion.video.sizes.${s}`) }))} onChange={(v) => changeSpec((d) => void (d.captions!.size = v as typeof captions.size), k("size"))} />
      </div>
    </Section>
  );
}

export function ProjectInspector({
  spec,
  changeSpec,
  duration,
  accentControl,
}: {
  spec: MotionSpec;
  changeSpec: Change<MotionSpec>;
  duration: number;
  accentControl: ReactNode;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.inspector.${key}`);
  const [hint] = useState(() => k("projectHint"));
  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="clip-inspector-project">
      <div>
        <h2 className="text-sm font-semibold">{k("project")}</h2>
        <p className="text-xs text-muted-foreground">{fill(k("duration"), { clock: formatClock(duration), seconds: duration.toFixed(1) })}</p>
      </div>
      <Section title={k("format")}>
        <div className="grid grid-cols-2 gap-1.5">
          {PLATFORM_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => changeSpec((d) => void (d.format = preset.format), k("format"))}
              className={cn(
                "flex flex-col items-start rounded-md border px-2 py-1.5 text-left",
                spec.format === preset.format ? "border-accent bg-accent/15" : "border-border hover:bg-muted",
              )}
              aria-pressed={spec.format === preset.format}
              data-testid={`clip-preset-${preset.id}`}
            >
              <span className="text-xs font-medium">{t(`nodes.editor.motion.video.presets.${preset.id}`)}</span>
              <span className="text-[10px] text-muted-foreground">{t(`nodes.editor.motion.formats.${preset.format}`)}</span>
            </button>
          ))}
        </div>
      </Section>
      <Section title={k("background")}>
        <div className="flex items-center gap-2">
          <Select
            label={k("theme")}
            value={spec.theme}
            options={[
              { value: "dark", label: t("nodes.editor.motion.toolbar.toDark") },
              { value: "light", label: t("nodes.editor.motion.toolbar.toLight") },
            ]}
            onChange={(v) => changeSpec((d) => void (d.theme = v as typeof spec.theme), t("nodes.editor.motion.history.theme"))}
            className="flex-1"
          />
          {accentControl}
        </div>
        <Toggle label={t("nodes.editor.motion.toolbar.loop")} checked={spec.loop} onChange={(on) => changeSpec((d) => void (d.loop = on), t("nodes.editor.motion.history.loop"))} />
      </Section>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}
