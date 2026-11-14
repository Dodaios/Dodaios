/**
 * The clip editor: a short film of scenes, edited on its timeline.
 *
 * Three parts in the common editor frame:
 *
 * * the PREVIEW, the real film drawn by the server from the unsaved spec. It
 *   stands on the picked scene, settled, and its texts can be written into
 *   right there; "Play" plays it from that scene (`ClipPreview`);
 * * the TIMELINE under it: every scene as a block as long as it runs, picked,
 *   dragged to reorder, its edge dragged to change its length, the
 *   transitions between them, the total length (`Timeline`);
 * * the INSPECTOR beside it: the picked scene's type and fields, its length
 *   and transition, chart and picture (`SceneInspector`).
 *
 * The toolbar holds what is the whole clip's: add a scene, play, the format,
 * the background, the accent colour and looping.
 *
 * Every change goes through `useNodeSpecEditor`, so undo and redo cover all
 * three parts alike and the work saves itself. A save waits while a scene
 * lacks what its type needs (the server would refuse it), and says which.
 */
import { useCallback, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Moon, Play, Plus, Repeat, Square, Sun } from "lucide-react";

import { fill, useT } from "@/i18n";
import { ChartEditor } from "../charts/ChartEditor";
import type { ChartJson } from "../charts/chartModel";
import { ColorPicker, KIT_COLORS, Popover, Select, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { EditorShell } from "../EditorShell";
import type { NodeEditorProps } from "../types";
import { useNodeSpecEditor } from "../useNodeSpecEditor";
import { ClipPreview, type FilmTime } from "./ClipPreview";
import {
  FORMATS,
  MAX_SCENES,
  convertScene,
  duplicateScene,
  insertScene,
  moveScene,
  newScene,
  pointerParts,
  readAtPointer,
  readMotionSpec,
  readNumber,
  removeScene,
  sceneProblem,
  sceneStarts,
  setAtPointer,
  setSeconds,
  type ClipFormat,
  type MotionSpec,
  type Scene,
  type SceneKind,
  type SceneSamples,
  type Transition,
} from "./motionModel";
import { SceneInspector, fieldLabelKey } from "./SceneInspector";
import { AddSceneItems, Timeline } from "./Timeline";

/** The film's named accents (`shell.NAMED_COLORS`) and the kit colour each stands for. */
const NAMED_ACCENTS: readonly [string, string][] = [
  ["blue", KIT_COLORS[0]],
  ["orange", KIT_COLORS[1]],
  ["green", KIT_COLORS[2]],
  ["amber", KIT_COLORS[3]],
  ["violet", KIT_COLORS[4]],
  ["pink", KIT_COLORS[5]],
];
const ACCENT_ALIASES: Record<string, string> = { yellow: "amber", purple: "violet" };

/**
 * The accent as the colour picker shows it. A named accent is kept as its
 * name in the spec: the film then takes that colour's dark or light shade
 * with its theme, which a fixed hex could not.
 */
export function accentToHex(accent: string): string {
  const name = ACCENT_ALIASES[accent] ?? accent;
  const named = NAMED_ACCENTS.find(([key]) => key === name);
  if (named) return named[1];
  return /^#[0-9a-f]{6}$/i.test(accent) ? accent.toUpperCase() : "";
}

/** The picker's colour as the spec keeps it: one of the kit's six is stored by name. */
export function hexToAccent(hex: string): string {
  if (!hex) return "";
  const named = NAMED_ACCENTS.find(([, value]) => value.toUpperCase() === hex.toUpperCase());
  return named ? named[0] : hex;
}

export default function MotionEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  // The spec in the editor's shape, read once; a revision from the server is
  // already normalized and has the same shape.
  const start = useMemo(() => ({ ...initial, spec: readMotionSpec(initial.spec) }), [initial]);
  const prepare = useCallback(
    (spec: MotionSpec) => {
      const index = spec.scenes.findIndex((scene) => sceneProblem(scene) !== null);
      if (index < 0) return spec;
      const field = sceneProblem(spec.scenes[index]);
      return {
        error: fill(t("nodes.editor.motion.needs"), {
          n: index + 1,
          field: field ? t(fieldLabelKey(field)) : "",
        }),
      };
    },
    [t],
  );
  const editor = useNodeSpecEditor<MotionSpec>(node.id ?? "", start, { prepare });
  const spec = editor.spec;
  const count = spec.scenes.length;

  const [picked, setPicked] = useState(0);
  const selected = Math.max(0, Math.min(count - 1, picked));
  const scene: Scene | undefined = spec.scenes[selected];
  const starts = useMemo(() => sceneStarts(spec), [spec]);
  const [playing, setPlaying] = useState(false);
  const [playToken, setPlayToken] = useState(0);
  const [playhead, setPlayhead] = useState<{ t: number; scene: number } | null>(null);
  const [chartOpen, setChartOpen] = useState(false);
  // A Play only ends once the page said it is playing: the first report after
  // the switch may still describe the standing film.
  const sawPlaying = useRef(false);
  // The preview draws the last spec the server can draw: while a scene lacks
  // what its type needs, the film stays as it was and the save state says why
  // (the server's own sentence is written for the assistant, not the person).
  const drawable = useRef(spec);
  if (spec.scenes.every((each) => sceneProblem(each) === null)) drawable.current = spec;

  const samples: SceneSamples = useMemo(
    () => ({
      title: t("nodes.editor.motion.samples.title"),
      text: t("nodes.editor.motion.samples.text"),
      point: (n) => fill(t("nodes.editor.motion.samples.point"), { n }),
      statLabel: t("nodes.editor.motion.samples.statLabel"),
      barLabel: (n) => fill(t("nodes.editor.motion.samples.barLabel"), { n }),
      quote: t("nodes.editor.motion.samples.quote"),
      by: t("nodes.editor.motion.samples.by"),
      step: (n) => fill(t("nodes.editor.motion.samples.step"), { n }),
      end: t("nodes.editor.motion.samples.end"),
    }),
    [t],
  );
  const label = (key: string) => t(`nodes.editor.motion.history.${key}`);

  /* ------------------------------------------------------------ actions */

  const stop = useCallback(() => {
    setPlaying(false);
    setPlayhead(null);
  }, []);

  const play = useCallback(
    (from: number) => {
      sawPlaying.current = false;
      setPicked(from);
      setPlaying(true);
      setPlayToken((n) => n + 1);
    },
    [],
  );

  const add = (kind: SceneKind) => {
    const at = count === 0 ? 0 : selected + 1;
    editor.apply((draft) => void insertScene(draft, at, newScene(kind, samples)), { label: label("add") });
    setPicked(at);
    stop();
  };
  const duplicate = (index: number) => {
    editor.apply((draft) => void duplicateScene(draft, index), { label: label("duplicate") });
    setPicked(index + 1);
  };
  const remove = (index: number) => {
    editor.apply((draft) => void removeScene(draft, index), { label: label("delete") });
    setPicked(Math.min(index, count - 2));
    stop();
  };
  const move = (from: number, to: number) => {
    editor.apply((draft) => void moveScene(draft, from, to), { label: label("move") });
    setPicked(Math.max(0, Math.min(count - 1, to)));
  };
  const changeScene = (index: number) => (change: (scene: Scene) => void, stepLabel: string, coalesce?: string) =>
    editor.apply(
      (draft) => {
        const target = draft.scenes[index];
        if (target) change(target);
      },
      { label: stepLabel, coalesce },
    );
  const onSeconds = (index: number, seconds: number, final: boolean) => {
    editor.apply((draft) => setSeconds(draft, index, seconds), { label: label("seconds"), coalesce: `length-${index}` });
    if (final) editor.breakCoalesce();
  };
  const onTransition = (index: number, transition: Transition) =>
    changeScene(index)((draft) => {
      draft.transition = transition;
    }, label("transition"));
  const convert = (kind: SceneKind) => {
    const current = spec.scenes[selected];
    if (!current || current.type === kind) return;
    const next = convertScene(current, kind, samples);
    editor.apply(
      (draft) => {
        draft.scenes[selected] = next;
      },
      { label: label("type") },
    );
    if (kind === "chart" && current.type !== "chart") setChartOpen(true);
  };

  /** A text written straight into the preview's page. */
  const onEdit = useCallback(
    (path: string, value: string | boolean, as: string): boolean => {
      const parts = pointerParts(path);
      if (!parts || parts[0] !== "scenes") return false;
      const index = Number(parts[1]);
      const before = readAtPointer(editor.spec, path);
      if (before === undefined) return false;
      let next: unknown = value;
      if (as === "number") {
        const number = readNumber(String(value));
        if (!Number.isFinite(number)) return false;
        next = Math.max(-1e12, Math.min(1e12, Math.round(number * 1e4) / 1e4));
      }
      if (Object.is(before, next)) return true;
      editor.apply((draft) => void setAtPointer(draft, path, next), { label: label("text") });
      if (Number.isInteger(index)) setPicked(index);
      return true;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor.spec, editor.apply],
  );

  const onTime = useCallback(
    (time: FilmTime) => {
      if (!playing) return;
      if (time.playing) {
        sawPlaying.current = true;
        setPlayhead({ t: time.t, scene: time.scene });
        return;
      }
      if (!sawPlaying.current) return;
      // The film ended or was paused in the page: stand on the scene it reached.
      setPicked(time.scene);
      stop();
    },
    [playing, stop],
  );

  const saveChart = (chart: ChartJson) => {
    setChartOpen(false);
    changeScene(selected)((draft) => {
      draft.chart = chart as unknown as Record<string, unknown>;
    }, label("chart"));
  };

  /** Space plays and stops while a scene block has focus. */
  const onBodyKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== " " || !(event.target as HTMLElement).closest?.('[role="option"]')) return;
    event.preventDefault();
    if (playing) stop();
    else play(selected);
  };

  /* ------------------------------------------------------------ toolbar */

  const toolbar = (
    <>
      <ToolbarGroup label={t("nodes.editor.motion.toolbar.scenes")}>
        <Popover
          label={t("nodes.editor.motion.add")}
          role="menu"
          trigger={
            <ToolbarButton
              label={t("nodes.editor.motion.add")}
              icon={<Plus aria-hidden />}
              showLabel
              disabled={count >= MAX_SCENES}
              data-testid="motion-add"
            />
          }
        >
          <AddSceneItems onAdd={add} />
        </Popover>
        {playing ? (
          <ToolbarButton label={t("nodes.editor.motion.toolbar.stop")} icon={<Square aria-hidden />} showLabel onClick={stop} data-testid="motion-stop" />
        ) : (
          <ToolbarButton
            label={t("nodes.editor.motion.toolbar.play")}
            icon={<Play aria-hidden />}
            showLabel
            shortcut={t("nodes.editor.motion.toolbar.space")}
            onClick={() => play(selected)}
            data-testid="motion-play"
          />
        )}
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.motion.toolbar.clip")}>
        <Select
          label={t("nodes.editor.motion.toolbar.format")}
          value={spec.format}
          options={FORMATS.map((format) => ({ value: format, label: t(`nodes.editor.motion.formats.${format}`) }))}
          onChange={(value) =>
            editor.apply(
              (draft) => {
                draft.format = value as ClipFormat;
              },
              { label: label("format") },
            )
          }
          className="w-36"
          testId="motion-format"
        />
        <ToolbarButton
          label={spec.theme === "dark" ? t("nodes.editor.motion.toolbar.toLight") : t("nodes.editor.motion.toolbar.toDark")}
          icon={spec.theme === "dark" ? <Moon aria-hidden /> : <Sun aria-hidden />}
          onClick={() =>
            editor.apply(
              (draft) => {
                draft.theme = draft.theme === "dark" ? "light" : "dark";
              },
              { label: label("theme") },
            )
          }
          data-testid="motion-theme"
        />
        <ColorPicker
          label={t("nodes.editor.motion.toolbar.accent")}
          value={accentToHex(spec.accent)}
          palette={NAMED_ACCENTS.map(([, hex]) => hex)}
          onChange={(hex) =>
            editor.apply(
              (draft) => {
                draft.accent = hexToAccent(hex);
              },
              { label: label("accent") },
            )
          }
        />
        <ToolbarButton
          label={t("nodes.editor.motion.toolbar.loop")}
          icon={<Repeat aria-hidden />}
          active={spec.loop}
          onClick={() =>
            editor.apply(
              (draft) => {
                draft.loop = !draft.loop;
              },
              { label: label("loop") },
            )
          }
          data-testid="motion-loop"
        />
      </ToolbarGroup>
    </>
  );

  const chart = scene?.type === "chart" ? (scene.chart as unknown as ChartJson | undefined) : undefined;

  return (
    <EditorShell
      editor={editor}
      title={node.title}
      onDone={onDone}
      toolbar={toolbar}
      bodyClassName="flex flex-col overflow-hidden"
      side={
        scene ? (
          <SceneInspector
            key={selected}
            scene={scene}
            index={selected}
            count={count}
            change={changeScene(selected)}
            onConvert={convert}
            onDuplicate={() => duplicate(selected)}
            onRemove={() => remove(selected)}
            onMove={(to) => move(selected, to)}
            onEditChart={() => setChartOpen(true)}
            canDuplicate={count < MAX_SCENES}
          />
        ) : null
      }
    >
      <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onBodyKeyDown}>
        <ClipPreview
          nodeId={node.id ?? ""}
          title={node.title}
          spec={drawable.current}
          selected={selected}
          starts={starts}
          playing={playing}
          playToken={playToken}
          onEdit={onEdit}
          onTime={onTime}
          className="min-h-[200px] flex-1"
        />
        <p className="shrink-0 px-3 py-1 text-xs text-muted-foreground">
          {playing ? t("nodes.editor.motion.preview.playing") : t("nodes.editor.motion.preview.hint")}
        </p>
        <Timeline
          spec={spec}
          selected={selected}
          onSelect={(index) => {
            setPicked(index);
            if (playing) stop();
          }}
          onMove={move}
          onSeconds={onSeconds}
          onTransition={onTransition}
          onAdd={add}
          onDuplicate={duplicate}
          onRemove={remove}
          playhead={playing ? playhead : null}
        />
      </div>
      <ChartEditor
        open={chartOpen}
        value={chart ?? null}
        heading={t("nodes.editor.motion.inspector.editChart")}
        onSave={(next) => saveChart(next)}
        onCancel={() => setChartOpen(false)}
      />
    </EditorShell>
  );
}
