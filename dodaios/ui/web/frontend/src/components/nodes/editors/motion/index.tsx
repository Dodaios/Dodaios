/**
 * The clip editor: a video editor for a Clips node.
 *
 * Four parts in the common editor frame:
 *
 * * the BIN on the left: the clip's library (import, drag onto the
 *   timeline), text styles, the animated cards, captions (`MediaBin`);
 * * the PREVIEW, the real clip drawn by the server from the unsaved spec,
 *   standing on the playhead's exact frame or playing (`ClipPreview`), with
 *   the transport under it;
 * * the TIMELINE: every track as a row, the main track magnetic, split, trim,
 *   move, snap, zoom (`TrackTimeline`);
 * * the INSPECTOR on the right: the picked piece, or the clip's settings
 *   (`ClipInspector`, `SceneInspector` for a card).
 *
 * Every change goes through `useNodeSpecEditor`, so undo and redo cover all
 * of it, the work saves itself, and what the assistant changes meanwhile (it
 * edits the same spec with the `clip` tool) arrives as an undoable step.
 *
 * Keys (while focus is in the editor, not in a field): Space play/pause,
 * J/K/L back/stop/play, arrows a frame (Shift: a second), Home/End, S or
 * Ctrl+B split, Delete, Shift+Delete ripple delete, Ctrl+C/X/V/D, Ctrl+A,
 * Escape, +/- zoom, N snapping.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  ChevronFirst,
  ChevronLast,
  Clapperboard,
  Grid2x2,
  Magnet,
  Pause,
  PencilLine,
  Play,
  Scissors,
  StepBack,
  StepForward,
  Trash2,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ChartEditor } from "../charts/ChartEditor";
import type { ChartJson } from "../charts/chartModel";
import { ColorPicker, KIT_COLORS, Popover, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { EditorShell } from "../EditorShell";
import type { NodeEditorProps } from "../types";
import { useNodeSpecEditor } from "../useNodeSpecEditor";
import { fetchCaptions, fetchSilences, uploadMedia } from "./clipApi";
import { CaptionInspector, ItemInspector, ProjectInspector, VideoPieceInspector } from "./ClipInspector";
import {
  FRAME,
  addItem,
  captionKey,
  clipDuration,
  copySelection,
  deleteSelection,
  ensureIds,
  findItem,
  insertPiece,
  itemKey,
  moveCaption,
  moveItem,
  ms,
  parseKey,
  pasteBoard,
  pieceFromMedia,
  removeSilences,
  sceneAtTime,
  sceneIndex,
  sceneKey,
  sortCaptions,
  splitAt,
  trimItemEnd,
  trimItemStart,
  trimSceneEnd,
  trimSceneStart,
  allIds,
  freshId,
  type ClipBoard,
  type SelKey,
} from "./clipModel";
import { ClipPreview, type FilmTime } from "./ClipPreview";
import { ExportPanel, type ExportJob } from "./ExportPanel";
import { MediaBin, type BinTab, type Upload } from "./MediaBin";
import {
  MAX_SCENES,
  convertScene,
  formatClock,
  moveScene,
  newScene,
  pointerParts,
  readAtPointer,
  readMotionSpec,
  readNumber,
  sceneProblem,
  sceneStarts,
  setAtPointer,
  type CardKind,
  type MotionSpec,
  type Scene,
  type SceneKind,
  type SceneSamples,
  type TrackItem,
} from "./motionModel";
import { SceneInspector, fieldLabelKey } from "./SceneInspector";
import { HEAD, TrackTimeline, type RowKind } from "./TrackTimeline";

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

/** A clock with hundredths, for the transport: 0:03.40. */
function preciseClock(seconds: number): string {
  const whole = Math.floor(seconds + 1e-6);
  const hundredths = Math.floor((seconds - whole) * 100 + 1e-6);
  return `${formatClock(whole)}.${String(hundredths).padStart(2, "0")}`;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable || !!el.closest?.('[role="listbox"][data-combobox-panel]');
}

export default function MotionEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const nodeId = node.id ?? "";
  // The spec in the editor's shape, read once, with an id on every piece so a
  // pick can name it; a revision from the server has the same shape.
  const start = useMemo(() => {
    const spec = readMotionSpec(initial.spec);
    ensureIds(spec);
    return { ...initial, spec };
  }, [initial]);
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
  const editor = useNodeSpecEditor<MotionSpec>(nodeId, start, { prepare });
  const spec = editor.spec;
  const duration = clipDuration(spec);
  const starts = useMemo(() => sceneStarts(spec), [spec]);
  const v = (key: string) => t(`nodes.editor.motion.video.${key}`);
  const label = (key: string) => t(`nodes.editor.motion.video.history.${key}`);

  /* ------------------------------------------------------------ state */

  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [playToken, setPlayToken] = useState(0);
  const [selection, setSelection] = useState<Set<SelKey>>(new Set());
  const [pps, setPps] = useState(48);
  const [snapping, setSnapping] = useState(true);
  const [guides, setGuides] = useState(false);
  const [editText, setEditText] = useState(false);
  const [tab, setTab] = useState<BinTab>("media");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [captionsBusy, setCaptionsBusy] = useState(false);
  const [captionsError, setCaptionsError] = useState("");
  const [silenceBusy, setSilenceBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [chartOpen, setChartOpen] = useState(false);
  const board = useRef<ClipBoard | null>(null);
  const sawPlaying = useRef(false);
  const timelineBox = useRef<HTMLDivElement>(null);
  // The preview draws the last spec the server can draw.
  const drawable = useRef(spec);
  if (spec.scenes.every((each) => sceneProblem(each) === null)) drawable.current = spec;

  // Picks that no longer exist (an undo, the assistant's edit) fall away.
  useEffect(() => {
    setSelection((now) => {
      const kept = new Set(
        [...now].filter((key) => {
          const { kind, id } = parseKey(key);
          if (kind === "scene") return sceneIndex(spec, id) >= 0;
          if (kind === "item") return findItem(spec, id) !== null;
          return Number(id) < (spec.captions?.items.length ?? 0);
        }),
      );
      return kept.size === now.size ? now : kept;
    });
  }, [spec]);

  // The timeline shows the whole clip, also as it grows or shrinks, until
  // the person zooms by hand; "Fit" brings that back.
  const zoomedByHand = useRef(false);
  const fit = useCallback(() => {
    zoomedByHand.current = false;
    const width = (timelineBox.current?.clientWidth ?? 900) - HEAD - 24;
    setPps(Math.max(2, Math.min(400, width / Math.max(4, clipDuration(editor.spec) * 1.05))));
  }, [editor.spec]);
  useEffect(() => {
    if (!zoomedByHand.current) fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration]);
  // A clip that got shorter keeps its playhead inside it.
  useEffect(() => {
    if (!playing && playhead > duration) setPlayhead(duration);
  }, [duration, playhead, playing]);

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

  /* ------------------------------------------------------------ transport */

  const seek = useCallback(
    (time: number) => {
      setPlaying(false);
      setPlayhead(ms(Math.max(0, Math.min(clipDuration(editor.spec), time))));
    },
    [editor.spec],
  );
  /** Move the playhead by `delta` seconds from where it is now (key repeat stays exact). */
  const step = useCallback(
    (delta: number) => {
      setPlaying(false);
      const end = clipDuration(editor.spec);
      setPlayhead((now) => ms(Math.max(0, Math.min(end, now + delta))));
    },
    [editor.spec],
  );
  const play = useCallback(() => {
    sawPlaying.current = false;
    if (playhead >= duration - 0.05) setPlayhead(0);
    setEditText(false);
    setPlaying(true);
    setPlayToken((n) => n + 1);
  }, [playhead, duration]);
  const stop = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => (playing ? stop() : play()), [playing, play, stop]);

  const onTime = useCallback(
    (time: FilmTime) => {
      if (!playing) return;
      if (time.playing) {
        sawPlaying.current = true;
        setPlayhead(time.t);
        return;
      }
      if (!sawPlaying.current) return;
      setPlayhead(time.t);
      setPlaying(false);
    },
    [playing],
  );

  /* ------------------------------------------------------------ changes */

  const apply = editor.apply;
  const select = (keys: SelKey[], mode: "replace" | "toggle" = "replace") =>
    setSelection((now) => {
      if (mode === "replace") return new Set(keys);
      const next = new Set(now);
      for (const key of keys) {
        if (next.has(key)) next.delete(key);
        else next.add(key);
      }
      return next;
    });

  const split = () => {
    let made: SelKey[] = [];
    apply((draft) => void (made = splitAt(draft, selection, playhead)), { label: label("split") });
    if (made.length) select(made);
  };
  const remove = (ripple: boolean) => {
    if (!selection.size) return;
    apply((draft) => deleteSelection(draft, selection, ripple), { label: label(ripple ? "ripple" : "delete") });
    select([]);
  };
  const copy = () => {
    if (selection.size) board.current = copySelection(spec, selection);
  };
  const paste = () => {
    const clip = board.current;
    if (!clip) return;
    let keys: SelKey[] = [];
    apply((draft) => void (keys = pasteBoard(draft, clip, playhead)), { label: label("paste") });
    select(keys);
  };
  const duplicate = () => {
    if (!selection.size) return;
    const clip = copySelection(spec, selection);
    let keys: SelKey[] = [];
    // A copy goes right after the original: the end of the latest picked thing.
    let end = 0;
    for (const key of selection) {
      const { kind, id } = parseKey(key);
      if (kind === "item") {
        const found = findItem(spec, id);
        if (found) end = Math.max(end, found.item.start + found.item.seconds);
      } else if (kind === "caption") end = Math.max(end, spec.captions?.items[Number(id)]?.end ?? 0);
      else {
        const index = sceneIndex(spec, id);
        if (index >= 0) end = Math.max(end, starts[index] + spec.scenes[index].seconds - 0.01);
      }
    }
    apply((draft) => void (keys = pasteBoard(draft, clip, end)), { label: label("duplicate") });
    select(keys);
  };
  const selectAll = () => {
    const keys: SelKey[] = [];
    for (const scene of spec.scenes) if (scene.id) keys.push(sceneKey(scene.id));
    for (const track of spec.tracks ?? []) for (const item of track.items) keys.push(itemKey(item.id));
    (spec.captions?.items ?? []).forEach((_, n) => keys.push(captionKey(n)));
    select(keys);
  };
  const zoom = (factor: number) => {
    zoomedByHand.current = true;
    setPps((now) => Math.max(2, Math.min(400, now * factor)));
  };

  /** Put a library file onto the timeline. */
  const placeMedia = (mediaId: string, at: number, row: RowKind, trackId?: string) => {
    const entry = spec.media?.[mediaId];
    if (!entry) return;
    let key: SelKey | null = null;
    apply(
      (draft) => {
        ensureIds(draft);
        const taken = allIds(draft);
        if (entry.kind === "audio" || row === "audio") {
          const remaining = clipDuration(draft) - at;
          const music = entry.kind === "audio";
          const length = music && remaining > 1 ? Math.min(entry.seconds, remaining) : entry.seconds || 5;
          const item: Omit<TrackItem, "id"> = { start: at, seconds: ms(length), media: mediaId };
          if (music) Object.assign(item, { volume: 0.3, duck: true, fade_in: 0.5, fade_out: 1.5 });
          key = itemKey(addItem(draft, "audio", item, row === "audio" ? trackId : undefined));
        } else if (row === "main" || row === "captions") {
          const piece = pieceFromMedia(freshId(taken, "v"), mediaId, entry);
          const index = row === "main" ? Math.min(draft.scenes.length, sceneAtTime(draft, at) + (at > 0 ? 1 : 0)) : draft.scenes.length;
          if (insertPiece(draft, index, piece)) key = sceneKey(piece.id!);
        } else {
          const seconds = entry.kind === "video" ? entry.seconds : 4;
          key = itemKey(addItem(draft, "overlay", { start: at, seconds: ms(seconds), media: mediaId, x: 50, y: 50, w: 40, anim: "pop", out: "fade" }, row === "overlay" ? trackId : undefined));
        }
      },
      { label: label("place") },
    );
    if (key) select([key]);
  };

  /** "+" on a library file: video and pictures after the piece under the playhead, sound at the playhead. */
  const addMedia = (mediaId: string) => {
    const entry = spec.media?.[mediaId];
    if (!entry) return;
    if (entry.kind === "audio") placeMedia(mediaId, playhead, "audio");
    else placeMedia(mediaId, playhead, "main");
  };

  const importFiles = async (files: File[]) => {
    setTab("media");
    for (const file of files) {
      setUploads((now) => [...now, { name: file.name, share: 0 }]);
      try {
        const done = await uploadMedia(nodeId, file, (share) => setUploads((now) => now.map((u) => (u.name === file.name ? { ...u, share } : u))));
        setUploads((now) => now.filter((u) => u.name !== file.name));
        apply(
          (draft) => {
            draft.media = { ...(draft.media ?? {}), [done.id]: done.entry };
            ensureIds(draft);
            // A new clip's first videos go straight onto the main track, in order.
            const main = draft.scenes;
            const fresh = main.length === 1 && main[0].type === "title" && !main[0].title && !main[0].text;
            const onlyMedia = main.every((scene) => scene.type === "video");
            if (done.entry.kind !== "audio" && (fresh || (onlyMedia && main.length < MAX_SCENES && files.length > 1))) {
              insertPiece(draft, draft.scenes.length, pieceFromMedia(freshId(allIds(draft), "v"), done.id, done.entry));
            }
          },
          { label: label("import") },
        );
      } catch (err) {
        const reason = err instanceof Error && err.message ? err.message : v("bin.uploadFailed");
        setUploads((now) => now.map((u) => (u.name === file.name ? { ...u, error: reason } : u)));
        window.setTimeout(() => setUploads((now) => now.filter((u) => u.name !== file.name)), 8000);
      }
    }
  };

  const addText = (style: string) => {
    const big = style === "title";
    let key: SelKey = "";
    apply(
      (draft) => {
        const id = addItem(draft, "text", {
          start: playhead,
          seconds: big ? 2.5 : 3,
          text: t(`nodes.editor.motion.video.samples.${style}`),
          style,
          x: 50,
          y: style === "caption" || style === "label" ? 78 : big ? 40 : 50,
          bg: style === "label" ? "pill" : "shadow",
          anim: big ? "pop" : "rise",
          out: "fade",
        });
        key = itemKey(id);
      },
      { label: label("text") },
    );
    select([key]);
  };

  const addCard = (kind: CardKind) => {
    const scene = newScene(kind, samples);
    let key: SelKey = "";
    apply(
      (draft) => {
        ensureIds(draft);
        scene.id = freshId(allIds(draft), "s");
        const index = Math.min(draft.scenes.length, sceneAtTime(draft, playhead) + 1);
        draft.scenes.splice(index, 0, scene);
        key = sceneKey(scene.id);
      },
      { label: label("card") },
    );
    select([key]);
  };

  const makeCaptions = async () => {
    setCaptionsBusy(true);
    setCaptionsError("");
    try {
      // The spoken language is heard, not taken from the app's own language.
      const items = await fetchCaptions(nodeId, spec);
      if (!items.length) {
        setCaptionsError(v("bin.noSpeech"));
        return;
      }
      apply(
        (draft) => {
          draft.captions = {
            style: draft.captions?.style ?? "karaoke",
            position: draft.captions?.position ?? "bottom",
            size: draft.captions?.size ?? "m",
            items,
          };
        },
        { label: label("captions") },
      );
    } catch (err) {
      setCaptionsError(err instanceof Error && err.message ? err.message : v("bin.captionsFailed"));
    } finally {
      setCaptionsBusy(false);
    }
  };

  const cutSilences = async (scene: Scene) => {
    if (!scene.media || !scene.id) return;
    setSilenceBusy(true);
    setNotice("");
    try {
      const from = scene.in ?? 0;
      const silences = await fetchSilences(nodeId, scene.media, from, from + scene.seconds * (scene.speed ?? 1));
      let removed = 0;
      if (silences.length) apply((draft) => void (removed = removeSilences(draft, scene.id!, silences)), { label: label("silences") });
      setNotice(removed ? fill(v("inspector.silencesRemoved"), { n: removed }) : v("inspector.noSilences"));
    } catch (err) {
      setNotice(err instanceof Error && err.message ? err.message : v("inspector.silencesFailed"));
    } finally {
      setSilenceBusy(false);
    }
  };

  /** A text written straight into the preview's page (text mode). */
  const onEdit = useCallback(
    (path: string, value: string | boolean, as: string): boolean => {
      const parts = pointerParts(path);
      if (!parts || parts[0] !== "scenes") return false;
      const before = readAtPointer(editor.spec, path);
      if (before === undefined) return false;
      let next: unknown = value;
      if (as === "number") {
        const number = readNumber(String(value));
        if (!Number.isFinite(number)) return false;
        next = Math.max(-1e12, Math.min(1e12, Math.round(number * 1e4) / 1e4));
      }
      if (Object.is(before, next)) return true;
      editor.apply((draft) => void setAtPointer(draft, path, next), { label: t("nodes.editor.motion.history.text") });
      return true;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor.spec, editor.apply],
  );

  /* ------------------------------------------------------------ keys */

  const onKeyDown = (event: Pick<ReactKeyboardEvent<HTMLElement>, "target" | "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey" | "preventDefault" | "stopPropagation">) => {
    if (isTyping(event.target)) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key;
    const handled = () => {
      event.preventDefault();
      event.stopPropagation();
    };
    if (key === " ") {
      handled();
      toggle();
    } else if (!mod && (key === "k" || key === "K")) {
      handled();
      stop();
    } else if (!mod && (key === "l" || key === "L")) {
      handled();
      play();
    } else if (!mod && (key === "j" || key === "J")) {
      handled();
      step(-1);
    } else if (key === "ArrowLeft" || key === "ArrowRight") {
      if (event.altKey) return;
      handled();
      step((key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 1 : FRAME));
    } else if (key === "Home") {
      handled();
      seek(0);
    } else if (key === "End") {
      handled();
      seek(duration);
    } else if ((!mod && (key === "s" || key === "S")) || (mod && (key === "b" || key === "B"))) {
      handled();
      split();
    } else if (key === "Delete" || key === "Backspace") {
      handled();
      remove(event.shiftKey);
    } else if (mod && (key === "c" || key === "C")) {
      handled();
      copy();
    } else if (mod && (key === "x" || key === "X")) {
      handled();
      copy();
      remove(false);
    } else if (mod && (key === "v" || key === "V")) {
      handled();
      paste();
    } else if (mod && (key === "d" || key === "D")) {
      handled();
      duplicate();
    } else if (mod && (key === "a" || key === "A")) {
      handled();
      selectAll();
    } else if (key === "Escape") {
      if (selection.size) {
        handled();
        select([]);
      }
    } else if (!mod && (key === "+" || key === "=")) {
      handled();
      zoom(1.25);
    } else if (!mod && key === "-") {
      handled();
      zoom(0.8);
    } else if (!mod && (key === "n" || key === "N")) {
      handled();
      setSnapping((on) => !on);
    }
  };

  // A key pressed while focus rests on the page itself (a field was left, a
  // button lost focus) still reaches the editor, as long as it is on screen.
  const keys = useRef(onKeyDown);
  keys.current = onKeyDown;
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onWindowKey = (event: KeyboardEvent) => {
      if (event.target !== document.body || event.defaultPrevented) return;
      keys.current(event as unknown as Parameters<typeof onKeyDown>[0]);
    };
    window.addEventListener("keydown", onWindowKey);
    return () => window.removeEventListener("keydown", onWindowKey);
  }, []);
  /** A key pressed inside the preview's page, passed on by it (`dodaios-film-key`). */
  const onPreviewKey = useCallback((key: string, shift: boolean, ctrl: boolean, alt: boolean) => {
    root.current?.focus({ preventScroll: true });
    keys.current({
      target: root.current,
      key,
      shiftKey: shift,
      ctrlKey: ctrl,
      metaKey: false,
      altKey: alt,
      preventDefault: () => undefined,
      stopPropagation: () => undefined,
    } as unknown as Parameters<typeof onKeyDown>[0]);
  }, []);

  /* ------------------------------------------------------------ inspector */

  const picked = selection.size === 1 ? parseKey([...selection][0]) : null;
  let side: React.ReactNode;
  if (selection.size > 1) {
    side = (
      <div className="flex flex-col gap-3" data-testid="clip-inspector-many">
        <h2 className="text-sm font-semibold">{fill(v("inspector.many"), { n: selection.size })}</h2>
        <p className="text-xs text-muted-foreground">{v("inspector.manyHint")}</p>
        <div className="flex gap-2">
          <button type="button" className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted" onClick={() => remove(false)}>
            {v("toolbar.delete")}
          </button>
          <button type="button" className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted" onClick={() => remove(true)}>
            {v("toolbar.ripple")}
          </button>
        </div>
      </div>
    );
  } else if (picked?.kind === "scene") {
    const index = sceneIndex(spec, picked.id);
    const scene = spec.scenes[index];
    const changeScene = (change: (draft: Scene) => void, stepLabel: string, coalesce?: string) =>
      apply(
        (draft) => {
          const target = draft.scenes[index];
          if (target) change(target);
        },
        { label: stepLabel, coalesce },
      );
    if (scene && scene.type === "video") {
      side = (
        <VideoPieceInspector
          key={scene.id}
          scene={scene}
          index={index}
          entry={scene.media ? spec.media?.[scene.media] : undefined}
          spec={spec}
          local={playhead - starts[index]}
          change={changeScene}
          onRemoveSilences={() => void cutSilences(scene)}
          busy={silenceBusy}
          onSplit={split}
          onRemove={() => remove(false)}
        />
      );
    } else if (scene) {
      side = (
        <SceneInspector
          key={scene.id}
          scene={scene}
          index={index}
          count={spec.scenes.length}
          change={changeScene}
          onConvert={(kind: SceneKind) => {
            if (kind === "video" || scene.type === kind) return;
            const next = convertScene(scene, kind, samples);
            next.id = scene.id;
            apply((draft) => void (draft.scenes[index] = next), { label: t("nodes.editor.motion.history.type") });
            if (kind === "chart") setChartOpen(true);
          }}
          onDuplicate={duplicate}
          onRemove={() => remove(false)}
          onMove={(to) => apply((draft) => void moveScene(draft, index, to), { label: t("nodes.editor.motion.history.move") })}
          onEditChart={() => setChartOpen(true)}
          canDuplicate={spec.scenes.length < MAX_SCENES}
        />
      );
    }
  } else if (picked?.kind === "item") {
    const found = findItem(spec, picked.id);
    if (found) {
      const changeItem = (change: (draft: TrackItem) => void, stepLabel: string, coalesce?: string) =>
        apply(
          (draft) => {
            const target = findItem(draft, picked.id);
            if (target) change(target.item);
          },
          { label: stepLabel, coalesce },
        );
      side = (
        <ItemInspector
          key={found.item.id}
          item={found.item}
          track={found.track}
          entry={found.item.media ? spec.media?.[found.item.media] : undefined}
          local={playhead - found.item.start}
          change={changeItem}
          onStart={(at) => apply((draft) => moveItem(draft, picked.id, at), { label: label("move") })}
          onSplit={split}
          onRemove={() => remove(false)}
        />
      );
    }
  } else if (picked?.kind === "caption") {
    side = (
      <CaptionInspector
        spec={spec}
        index={Number(picked.id)}
        changeSpec={(change, stepLabel, coalesce) => apply(change, { label: stepLabel, coalesce })}
        onRemove={() => remove(false)}
      />
    );
  }
  const accentControl = (
    <ColorPicker
      label={t("nodes.editor.motion.toolbar.accent")}
      value={accentToHex(spec.accent)}
      palette={NAMED_ACCENTS.map(([, hex]) => hex)}
      onChange={(hex) => apply((draft) => void (draft.accent = hexToAccent(hex)), { label: t("nodes.editor.motion.history.accent") })}
    />
  );
  if (!side)
    side = (
      <ProjectInspector spec={spec} duration={duration} changeSpec={(change, stepLabel) => apply(change, { label: stepLabel })} accentControl={accentControl} />
    );

  /* ------------------------------------------------------------ toolbar */

  const toolbar = (
    <>
      <ToolbarGroup label={v("toolbar.clip")}>
        <span className="flex items-center gap-1.5 px-1 text-sm font-medium">
          <Clapperboard className="h-4 w-4 text-muted-foreground" aria-hidden />
          {fill(v("toolbar.length"), { clock: formatClock(duration) })}
        </span>
      </ToolbarGroup>
      <ToolbarSeparator />
      <Popover
        label={v("export.title")}
        trigger={
          <ToolbarButton
            label={exportJob?.status.state === "running" ? fill(v("export.progress"), { n: Math.round(exportJob.status.progress * 100) }) : v("export.title")}
            icon={<Maximize2 aria-hidden />}
            showLabel
            data-testid="clip-export"
          />
        }
      >
        <ExportPanel nodeId={nodeId} spec={spec} job={exportJob} onJob={setExportJob} />
      </Popover>
    </>
  );

  const scene = spec.scenes[sceneAtTime(spec, playhead)];
  const chart = scene?.type === "chart" ? (scene.chart as unknown as ChartJson | undefined) : undefined;
  const pickedScene = picked?.kind === "scene" ? spec.scenes[sceneIndex(spec, picked.id)] : undefined;

  return (
    <EditorShell editor={editor} title={node.title} onDone={onDone} toolbar={toolbar} bodyClassName="flex overflow-hidden" side={side}>
      <div ref={root} className="flex min-h-0 min-w-0 flex-1 outline-none" onKeyDown={onKeyDown} tabIndex={-1} data-testid="clip-editor">
        <MediaBin
          nodeId={nodeId}
          spec={spec}
          tab={tab}
          onTab={setTab}
          uploads={uploads}
          onFiles={(files) => void importFiles(files)}
          onAddMedia={addMedia}
          onAddText={addText}
          onAddCard={addCard}
          onCaptions={() => void makeCaptions()}
          captionsBusy={captionsBusy}
          captionsError={captionsError}
          changeSpec={(change, stepLabel, coalesce) => apply(change, { label: stepLabel, coalesce })}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <ClipPreview
            nodeId={nodeId}
            title={node.title}
            spec={drawable.current}
            at={playhead}
            scene={sceneAtTime(spec, playhead)}
            playing={playing}
            playToken={playToken}
            editText={editText}
            guides={guides}
            onEdit={onEdit}
            onTime={onTime}
            onPick={(id) => {
              // The editor keeps the keys: the preview's page only passes them on.
              root.current?.focus({ preventScroll: true });
              if (!id) return;
              select([itemKey(id)]);
            }}
            onKey={onPreviewKey}
            onMoveLayer={(id, x, y) =>
              apply(
                (draft) => {
                  const found = findItem(draft, id);
                  if (found) {
                    found.item.x = Math.round(x * 100) / 100;
                    found.item.y = Math.round(y * 100) / 100;
                  }
                },
                { label: label("place") },
              )
            }
            className="min-h-[180px] flex-1"
          />
          {/* The transport. */}
          <div className="flex shrink-0 items-center gap-1 border-t border-border px-2 py-1" role="toolbar" aria-label={v("toolbar.transport")}>
            <ToolbarButton label={v("toolbar.start")} icon={<ChevronFirst aria-hidden />} onClick={() => seek(0)} shortcut="Home" />
            <ToolbarButton label={v("toolbar.frameBack")} icon={<StepBack aria-hidden />} onClick={() => step(-FRAME)} shortcut="←" />
            <ToolbarButton
              label={playing ? v("toolbar.pause") : v("toolbar.play")}
              icon={playing ? <Pause aria-hidden /> : <Play aria-hidden />}
              onClick={toggle}
              shortcut={t("nodes.editor.motion.toolbar.space")}
              data-testid={playing ? "motion-stop" : "motion-play"}
            />
            <ToolbarButton label={v("toolbar.frameForward")} icon={<StepForward aria-hidden />} onClick={() => step(FRAME)} shortcut="→" />
            <ToolbarButton label={v("toolbar.end")} icon={<ChevronLast aria-hidden />} onClick={() => seek(duration)} shortcut="End" />
            <span className="ml-2 font-mono text-xs tabular-nums text-muted-foreground" data-testid="clip-clock">
              {preciseClock(playhead)} / {preciseClock(duration)}
            </span>
            <div className="flex-1" />
            {notice && <span className="mr-2 max-w-[22rem] truncate text-xs text-muted-foreground" role="status">{notice}</span>}
            <ToolbarButton label={v("toolbar.editText")} icon={<PencilLine aria-hidden />} active={editText} onClick={() => setEditText((on) => !on)} data-testid="clip-edit-text" />
            <ToolbarButton label={v("toolbar.guides")} icon={<Grid2x2 aria-hidden />} active={guides} onClick={() => setGuides((on) => !on)} data-testid="clip-guides" />
          </div>
          {/* The timeline's own tools. */}
          <div className="flex shrink-0 items-center gap-1 border-t border-border px-2 py-1" role="toolbar" aria-label={v("toolbar.timeline")}>
            <ToolbarButton label={v("toolbar.split")} icon={<Scissors aria-hidden />} onClick={split} shortcut="S" data-testid="clip-split" />
            <ToolbarButton label={v("toolbar.delete")} icon={<Trash2 aria-hidden />} onClick={() => remove(false)} disabled={!selection.size} shortcut="Del" data-testid="clip-delete" />
            <ToolbarButton
              label={v("toolbar.ripple")}
              icon={<Trash2 className="text-warning" aria-hidden />}
              onClick={() => remove(true)}
              disabled={!selection.size}
              shortcut="Shift+Del"
              data-testid="clip-ripple"
            />
            <ToolbarSeparator />
            <ToolbarButton label={v("toolbar.snap")} icon={<Magnet aria-hidden />} active={snapping} onClick={() => setSnapping((on) => !on)} shortcut="N" data-testid="clip-snap" />
            <div className="flex-1" />
            <span className="mr-2 hidden text-[11px] text-muted-foreground 2xl:inline">{v("toolbar.keys")}</span>
            <ToolbarButton label={v("toolbar.zoomOut")} icon={<ZoomOut aria-hidden />} onClick={() => zoom(0.8)} shortcut="-" />
            <ToolbarButton label={v("toolbar.fit")} icon={<Maximize2 aria-hidden />} onClick={fit} data-testid="clip-fit" />
            <ToolbarButton label={v("toolbar.zoomIn")} icon={<ZoomIn aria-hidden />} onClick={() => zoom(1.25)} shortcut="+" />
          </div>
          <div ref={timelineBox} className={cn("flex h-[38%] min-h-[190px] shrink-0 flex-col")}>
            <TrackTimeline
              nodeId={nodeId}
              spec={spec}
              playhead={playhead}
              playing={playing}
              selection={selection}
              pps={pps}
              snapping={snapping}
              onSelect={select}
              onSeek={seek}
              onZoom={(next) => {
                zoomedByHand.current = true;
                setPps(Math.max(2, Math.min(400, next)));
              }}
              onMoveScene={(from, to) => apply((draft) => void moveScene(draft, from, to), { label: label("move") })}
              onTrimScene={(index, edge, value) =>
                apply((draft) => (edge === "start" ? trimSceneStart(draft, index, value) : trimSceneEnd(draft, index, value)), { label: label("trim") })
              }
              onMoveItem={(id, at, trackId) => apply((draft) => moveItem(draft, id, at, trackId || undefined), { label: label("move") })}
              onTrimItem={(id, edge, at) => apply((draft) => (edge === "start" ? trimItemStart(draft, id, at) : trimItemEnd(draft, id, at)), { label: label("trim") })}
              onMoveCaption={(index, at) =>
                apply(
                  (draft) => {
                    moveCaption(draft, index, at);
                    sortCaptions(draft);
                  },
                  { label: label("move") },
                )
              }
              onTrimCaption={(index, edge, at) =>
                apply(
                  (draft) => {
                    const line = draft.captions?.items[index];
                    if (!line) return;
                    if (edge === "start") line.start = ms(Math.min(at, line.end - 0.2));
                    else line.end = ms(Math.max(at, line.start + 0.2));
                    delete line.words;
                  },
                  { label: label("trim") },
                )
              }
              onTransition={(index, transition) =>
                apply(
                  (draft) => {
                    if (draft.scenes[index]) draft.scenes[index].transition = transition;
                  },
                  { label: t("nodes.editor.motion.history.transition") },
                )
              }
              onDropMedia={placeMedia}
              onTrackFlag={(trackId, flag) =>
                apply(
                  (draft) => {
                    const track = draft.tracks?.find((each) => each.id === trackId);
                    if (!track) return;
                    if (track[flag]) delete track[flag];
                    else track[flag] = true;
                  },
                  { label: label("track") },
                )
              }
            />
          </div>
        </div>
      </div>
      <ChartEditor
        open={chartOpen}
        value={(pickedScene?.type === "chart" ? (pickedScene.chart as unknown as ChartJson) : chart) ?? null}
        heading={t("nodes.editor.motion.inspector.editChart")}
        onSave={(next) => {
          setChartOpen(false);
          const index = pickedScene ? sceneIndex(spec, pickedScene.id ?? "") : sceneAtTime(spec, playhead);
          apply(
            (draft) => {
              const target = draft.scenes[index];
              if (target) target.chart = next as unknown as Record<string, unknown>;
            },
            { label: t("nodes.editor.motion.history.chart") },
          );
        }}
        onCancel={() => setChartOpen(false)}
      />
    </EditorShell>
  );
}
