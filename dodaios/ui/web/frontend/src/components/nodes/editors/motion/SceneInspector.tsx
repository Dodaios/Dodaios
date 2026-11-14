/**
 * The inspector of the picked scene: its type, every field that type keeps,
 * its length and how it comes in.
 *
 * Fields follow the scene type's grammar exactly (`FIELDS` in the model), so
 * nothing is offered that the server would drop. Each field caps its text at
 * the length the server keeps, so what is typed is what is saved. Typing in a
 * field is one undo step per run (`coalesce`), and the fields take part in
 * the editor's undo (`data-spec-undo`): Cmd/Ctrl+Z inside a field undoes the
 * spec, the same history the timeline and the preview write into.
 *
 * A field the scene type cannot do without is marked when it is empty; the
 * save waits until it is filled (the editor's `prepare`).
 */
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, BarChart3, Copy, ImageUp, Plus, Trash2, Wand2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { InspectorField, NumberField, Select, ToolbarButton } from "../controls";
import {
  FIELDS,
  LIMITS,
  MAX_BULLETS,
  MAX_ITEMS,
  MAX_SECONDS,
  MAX_STEPS,
  MIN_SECONDS,
  SCENE_KINDS,
  TRANSITIONS,
  defaultSeconds,
  readNumber,
  sceneProblem,
  type Scene,
  type SceneField,
  type SceneKind,
  type TextField,
  type Transition,
} from "./motionModel";
import { PictureError, pictureToDataUri } from "./pictureData";
import { SCENE_ICONS, TRANSITION_ICONS, kindKey, transitionKey } from "./sceneKinds";

/** A change to the picked scene, as one undo step (or one run with `coalesce`). */
export type SceneChange = (change: (scene: Scene) => void, label: string, coalesce?: string) => void;

export interface SceneInspectorProps {
  scene: Scene;
  index: number;
  count: number;
  change: SceneChange;
  onConvert: (kind: SceneKind) => void;
  onDuplicate: () => void;
  onRemove: () => void;
  onMove: (to: number) => void;
  onEditChart: () => void;
  canDuplicate: boolean;
}

const FIELD_LABELS: Record<TextField, string> = {
  kicker: "nodes.editor.motion.fields.kicker",
  title: "nodes.editor.motion.fields.title",
  text: "nodes.editor.motion.fields.text",
  value: "nodes.editor.motion.fields.value",
  unit: "nodes.editor.motion.fields.unit",
  label: "nodes.editor.motion.fields.label",
  detail: "nodes.editor.motion.fields.detail",
  quote: "nodes.editor.motion.fields.quote",
  by: "nodes.editor.motion.fields.by",
  caption: "nodes.editor.motion.fields.caption",
};

/** Fields written over several lines: a statement, a quote. */
const LONG_FIELDS = new Set<TextField>(["text", "quote", "detail"]);

/** The label key of any field (the lists and the picture too), for messages. */
export function fieldLabelKey(field: SceneField): string {
  if (field in FIELD_LABELS) return FIELD_LABELS[field as TextField];
  return `nodes.editor.motion.fields.${field}`;
}

export function SceneInspector({
  scene,
  index,
  count,
  change,
  onConvert,
  onDuplicate,
  onRemove,
  onMove,
  onEditChart,
  canDuplicate,
}: SceneInspectorProps) {
  const t = useT();
  const problem = sceneProblem(scene);
  const keeps = FIELDS[scene.type];
  const step = (key: string) => t(`nodes.editor.motion.history.${key}`);

  const textField = (field: TextField) => {
    const limit = field === "title" ? LIMITS.title : field === "text" ? LIMITS.text : LIMITS[field as keyof typeof LIMITS];
    const value = (scene[field] as string | undefined) ?? "";
    const required = problem === field;
    const props = {
      value,
      maxLength: limit,
      "aria-invalid": required || undefined,
      "data-testid": `motion-field-${field}`,
      onChange: (event: { target: { value: string } }) => {
        const next = event.target.value;
        change((draft) => {
          (draft as unknown as Record<string, unknown>)[field] = next;
        }, step("text"), `scene-${index}-${field}`);
      },
    };
    return (
      <InspectorField
        key={field}
        label={t(FIELD_LABELS[field])}
        hint={required ? t("nodes.editor.motion.inspector.required") : undefined}
      >
        {(id) =>
          LONG_FIELDS.has(field) ? (
            <Textarea id={id} rows={3} className={cn("min-h-[72px] text-sm", required && "border-warning")} {...props} />
          ) : (
            <Input id={id} className={cn("h-8 text-sm", required && "border-warning")} {...props} />
          )
        }
      </InspectorField>
    );
  };

  const Icon = SCENE_ICONS[scene.type];
  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="motion-inspector">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        <h2 className="text-sm font-semibold">{fill(t("nodes.editor.motion.inspector.heading"), { n: index + 1 })}</h2>
        <div className="ml-auto flex items-center">
          <ToolbarButton
            label={t("nodes.editor.motion.actions.moveEarlier")}
            icon={<ArrowUp aria-hidden />}
            disabled={index === 0}
            onClick={() => onMove(index - 1)}
          />
          <ToolbarButton
            label={t("nodes.editor.motion.actions.moveLater")}
            icon={<ArrowDown aria-hidden />}
            disabled={index >= count - 1}
            onClick={() => onMove(index + 1)}
          />
          <ToolbarButton
            label={t("nodes.editor.motion.actions.duplicate")}
            icon={<Copy aria-hidden />}
            disabled={!canDuplicate}
            onClick={onDuplicate}
            data-testid="motion-duplicate"
          />
          <ToolbarButton
            label={t("nodes.editor.motion.actions.delete")}
            icon={<Trash2 aria-hidden />}
            disabled={count <= 1}
            onClick={onRemove}
            data-testid="motion-delete"
          />
        </div>
      </div>

      <Select
        label={t("nodes.editor.motion.inspector.type")}
        showLabel
        value={scene.type}
        options={SCENE_KINDS.map((kind) => {
          const KindIcon = SCENE_ICONS[kind];
          return { value: kind, label: t(kindKey(kind)), icon: <KindIcon className="h-4 w-4" aria-hidden /> };
        })}
        onChange={(value) => onConvert(value as SceneKind)}
        testId="motion-scene-type"
      />

      {keeps.map((field) => {
        if (field === "bullets") return <PointsList key={field} scene={scene} index={index} change={change} invalid={problem === field} />;
        if (field === "items") return <BarsList key={field} scene={scene} index={index} change={change} invalid={problem === field} />;
        if (field === "steps") return <StepsList key={field} scene={scene} index={index} change={change} invalid={problem === field} />;
        if (field === "image") return <PictureField key={field} scene={scene} change={change} />;
        if (field === "chart")
          return (
            <InspectorField key={field} label={t("nodes.editor.motion.fields.chart")}>
              {(id) => (
                <Button id={id} variant="outline" size="sm" onClick={onEditChart} data-testid="motion-edit-chart">
                  <BarChart3 aria-hidden />
                  {t("nodes.editor.motion.inspector.editChart")}
                </Button>
              )}
            </InspectorField>
          );
        return textField(field as TextField);
      })}

      <div className="flex flex-col gap-3 border-t border-border pt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("nodes.editor.motion.inspector.timing")}
        </h3>
        <div className="flex items-end gap-2">
          <NumberField
            label={t("nodes.editor.motion.inspector.seconds")}
            showLabel
            value={scene.seconds}
            min={MIN_SECONDS}
            max={MAX_SECONDS}
            step={0.5}
            decimals={1}
            suffix="s"
            onChange={(value) => {
              if (value === null) return;
              change((draft) => {
                draft.seconds = Math.round(Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, value)) * 10) / 10;
              }, step("seconds"));
            }}
            className="w-28"
          />
          <ToolbarButton
            label={t("nodes.editor.motion.inspector.fit")}
            icon={<Wand2 aria-hidden />}
            showLabel
            disabled={scene.seconds === defaultSeconds(scene)}
            onClick={() =>
              change((draft) => {
                draft.seconds = defaultSeconds(draft);
              }, step("seconds"))
            }
            data-testid="motion-fit"
          />
        </div>
        <Select
          label={index === 0 ? t("nodes.editor.motion.inspector.transitionFirst") : t("nodes.editor.motion.inspector.transition")}
          showLabel
          value={scene.transition}
          disabled={index === 0}
          options={TRANSITIONS.map((transition) => {
            const TransitionIcon = TRANSITION_ICONS[transition];
            return { value: transition, label: t(transitionKey(transition)), icon: <TransitionIcon className="h-4 w-4" aria-hidden /> };
          })}
          onChange={(value) =>
            change((draft) => {
              draft.transition = value as Transition;
            }, step("transition"))
          }
          testId="motion-transition"
        />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- lists */

function ListShell({
  label,
  invalid,
  children,
  canAdd,
  addLabel,
  onAdd,
  max,
}: {
  label: string;
  invalid: boolean;
  children: ReactNode;
  canAdd: boolean;
  addLabel: string;
  onAdd: () => void;
  max: number;
}) {
  const t = useT();
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1 text-xs text-muted-foreground">{label}</legend>
      {children}
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" disabled={!canAdd} onClick={onAdd}>
          <Plus aria-hidden />
          {addLabel}
        </Button>
        {!canAdd && <span className="text-xs text-muted-foreground">{fill(t("nodes.editor.motion.inspector.max"), { n: max })}</span>}
      </div>
      {invalid && <p className="text-xs text-warning">{t("nodes.editor.motion.inspector.required")}</p>}
    </fieldset>
  );
}

/** Move up, move down and remove for one row of a list. */
function RowActions({
  index,
  count,
  onMove,
  onRemove,
  noun,
}: {
  index: number;
  count: number;
  onMove: (to: number) => void;
  onRemove: () => void;
  noun: string;
}) {
  const t = useT();
  return (
    <div className="flex shrink-0 items-center">
      <ToolbarButton
        className="h-7 w-7"
        label={fill(t("nodes.editor.motion.inspector.moveUp"), { item: noun })}
        icon={<ArrowUp aria-hidden />}
        disabled={index === 0}
        onClick={() => onMove(index - 1)}
      />
      <ToolbarButton
        className="h-7 w-7"
        label={fill(t("nodes.editor.motion.inspector.moveDown"), { item: noun })}
        icon={<ArrowDown aria-hidden />}
        disabled={index >= count - 1}
        onClick={() => onMove(index + 1)}
      />
      <ToolbarButton
        className="h-7 w-7"
        label={fill(t("nodes.editor.motion.inspector.remove"), { item: noun })}
        icon={<X aria-hidden />}
        disabled={count <= 1}
        onClick={onRemove}
      />
    </div>
  );
}

function move<T>(list: T[], from: number, to: number): void {
  if (to < 0 || to >= list.length) return;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
}

interface ListProps {
  scene: Scene;
  index: number;
  change: SceneChange;
  invalid: boolean;
}

function PointsList({ scene, index, change, invalid }: ListProps) {
  const t = useT();
  const points = scene.bullets ?? [];
  const noun = (n: number) => fill(t("nodes.editor.motion.inspector.pointN"), { n: n + 1 });
  return (
    <ListShell
      label={t("nodes.editor.motion.fields.bullets")}
      invalid={invalid}
      canAdd={points.length < MAX_BULLETS}
      max={MAX_BULLETS}
      addLabel={t("nodes.editor.motion.inspector.addPoint")}
      onAdd={() =>
        change((draft) => {
          draft.bullets = [...(draft.bullets ?? []), ""];
        }, t("nodes.editor.motion.history.addRow"))
      }
    >
      {points.map((point, row) => (
        <div key={row} className="flex items-center gap-1">
          <Input
            aria-label={noun(row)}
            value={point}
            maxLength={LIMITS.bullet}
            className="h-8 text-sm"
            data-testid={`motion-point-${row}`}
            onChange={(event) => {
              const next = event.target.value;
              change((draft) => {
                if (draft.bullets) draft.bullets[row] = next;
              }, t("nodes.editor.motion.history.text"), `scene-${index}-bullet-${row}`);
            }}
          />
          <RowActions
            index={row}
            count={points.length}
            noun={noun(row)}
            onMove={(to) => change((draft) => move(draft.bullets ?? [], row, to), t("nodes.editor.motion.history.moveRow"))}
            onRemove={() => change((draft) => void draft.bullets?.splice(row, 1), t("nodes.editor.motion.history.removeRow"))}
          />
        </div>
      ))}
    </ListShell>
  );
}

function BarsList({ scene, index, change, invalid }: ListProps) {
  const t = useT();
  const items = scene.items ?? [];
  const noun = (n: number) => fill(t("nodes.editor.motion.inspector.barN"), { n: n + 1 });
  return (
    <ListShell
      label={t("nodes.editor.motion.fields.items")}
      invalid={invalid}
      canAdd={items.length < MAX_ITEMS}
      max={MAX_ITEMS}
      addLabel={t("nodes.editor.motion.inspector.addBar")}
      onAdd={() =>
        change((draft) => {
          draft.items = [...(draft.items ?? []), { label: fill(t("nodes.editor.motion.samples.barLabel"), { n: items.length + 1 }), value: 10 }];
        }, t("nodes.editor.motion.history.addRow"))
      }
    >
      {items.map((item, row) => (
        <div key={row} className="flex items-center gap-1">
          <Input
            aria-label={fill(t("nodes.editor.motion.inspector.barLabel"), { n: row + 1 })}
            value={item.label}
            maxLength={LIMITS.itemLabel}
            className="h-8 min-w-0 flex-1 text-sm"
            data-testid={`motion-bar-label-${row}`}
            onChange={(event) => {
              const next = event.target.value;
              change((draft) => {
                if (draft.items?.[row]) draft.items[row].label = next;
              }, t("nodes.editor.motion.history.text"), `scene-${index}-bar-${row}`);
            }}
          />
          <BarValue
            value={item.value}
            label={fill(t("nodes.editor.motion.inspector.barValue"), { n: row + 1 })}
            testId={`motion-bar-value-${row}`}
            onChange={(value) =>
              change((draft) => {
                if (draft.items?.[row]) draft.items[row].value = value;
              }, t("nodes.editor.motion.history.text"))
            }
          />
          <RowActions
            index={row}
            count={items.length}
            noun={noun(row)}
            onMove={(to) => change((draft) => move(draft.items ?? [], row, to), t("nodes.editor.motion.history.moveRow"))}
            onRemove={() => change((draft) => void draft.items?.splice(row, 1), t("nodes.editor.motion.history.removeRow"))}
          />
        </div>
      ))}
    </ListShell>
  );
}

/**
 * A bar's number, typed in the person's own notation ("1.240,5" or "1,240.5")
 * and taken when the field is left or on Enter; something that is not a
 * number puts the last value back.
 */
function BarValue({ value, label, testId, onChange }: { value: number; label: string; testId: string; onChange: (value: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const number = readNumber(draft);
    setDraft(null);
    if (Number.isFinite(number) && number !== value) onChange(Math.max(-1e12, Math.min(1e12, Math.round(number * 1e4) / 1e4)));
  };
  return (
    <Input
      aria-label={label}
      inputMode="decimal"
      value={draft ?? String(value)}
      className="h-8 w-20 shrink-0 text-right text-sm tabular-nums"
      data-testid={testId}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
        if (event.key === "Escape") setDraft(null);
      }}
    />
  );
}

function StepsList({ scene, index, change, invalid }: ListProps) {
  const t = useT();
  const steps = scene.steps ?? [];
  const noun = (n: number) => fill(t("nodes.editor.motion.inspector.stepN"), { n: n + 1 });
  return (
    <ListShell
      label={t("nodes.editor.motion.fields.steps")}
      invalid={invalid}
      canAdd={steps.length < MAX_STEPS}
      max={MAX_STEPS}
      addLabel={t("nodes.editor.motion.inspector.addStep")}
      onAdd={() =>
        change((draft) => {
          draft.steps = [...(draft.steps ?? []), { title: fill(t("nodes.editor.motion.samples.step"), { n: steps.length + 1 }), text: "" }];
        }, t("nodes.editor.motion.history.addRow"))
      }
    >
      {steps.map((item, row) => (
        <div key={row} className="flex flex-col gap-1 rounded-md border border-border p-1.5">
          <div className="flex items-center gap-1">
            <span className="w-4 shrink-0 text-center text-xs tabular-nums text-muted-foreground">{row + 1}</span>
            <Input
              aria-label={fill(t("nodes.editor.motion.inspector.stepTitle"), { n: row + 1 })}
              value={item.title}
              maxLength={LIMITS.stepTitle}
              className="h-8 text-sm"
              data-testid={`motion-step-title-${row}`}
              onChange={(event) => {
                const next = event.target.value;
                change((draft) => {
                  if (draft.steps?.[row]) draft.steps[row].title = next;
                }, t("nodes.editor.motion.history.text"), `scene-${index}-step-${row}-title`);
              }}
            />
            <RowActions
              index={row}
              count={steps.length}
              noun={noun(row)}
              onMove={(to) => change((draft) => move(draft.steps ?? [], row, to), t("nodes.editor.motion.history.moveRow"))}
              onRemove={() => change((draft) => void draft.steps?.splice(row, 1), t("nodes.editor.motion.history.removeRow"))}
            />
          </div>
          <Input
            aria-label={fill(t("nodes.editor.motion.inspector.stepText"), { n: row + 1 })}
            placeholder={t("nodes.editor.motion.inspector.stepTextPlaceholder")}
            value={item.text}
            maxLength={LIMITS.stepText}
            className="h-8 text-sm"
            onChange={(event) => {
              const next = event.target.value;
              change((draft) => {
                if (draft.steps?.[row]) draft.steps[row].text = next;
              }, t("nodes.editor.motion.history.text"), `scene-${index}-step-${row}-text`);
            }}
          />
        </div>
      ))}
    </ListShell>
  );
}

/* -------------------------------------------------------------- picture */

function PictureField({ scene, change }: { scene: Scene; change: SceneChange }) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);

  const take = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const uri = await pictureToDataUri(file);
      change((draft) => {
        draft.image = uri;
      }, t("nodes.editor.motion.history.picture"));
    } catch (failure) {
      const reason = failure instanceof PictureError ? failure.reason : "read";
      setError(t(`nodes.editor.motion.picture.${reason}`));
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    void take(event.dataTransfer.files?.[0]);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-muted-foreground">{t("nodes.editor.motion.fields.image")}</span>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "relative overflow-hidden rounded-md border border-dashed border-border-strong bg-muted/30",
          over && "border-accent bg-accent/10",
        )}
      >
        {scene.image && <img src={scene.image} alt="" className="block max-h-40 w-full object-cover" />}
        <div className="flex items-center gap-2 p-2">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()} data-testid="motion-picture">
            <ImageUp aria-hidden />
            {t("nodes.editor.motion.picture.choose")}
          </Button>
          <span className="text-xs text-muted-foreground">{t("nodes.editor.motion.picture.drop")}</span>
        </div>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif,image/avif"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          void take(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      {error && (
        <p role="alert" className="text-xs text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
