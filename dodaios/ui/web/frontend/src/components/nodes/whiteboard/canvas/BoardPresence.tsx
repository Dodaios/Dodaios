/**
 * The agent's presence over a board it is drawing: the shared look (cursor
 * with its name tag, frame) from the live-build core, moved by the shared
 * player. The tag also says that the assistant is drawing, so the board shows
 * no badge of its own.
 *
 * The canvas has no DOM per element, so the player is given one invisible
 * marker per piece, laid out in scene units inside a layer that follows the
 * canvas's scroll and zoom. The markers never draw anything; they only give
 * the player boxes to measure. `LiveBuild` lands the pieces on the canvas on
 * the same timing, so the frame grows and the cursor glides as each piece
 * appears.
 *
 * The person's hands (a click, a key, the wheel, a touch) land the rest at
 * once. Reduced motion shows the drawing at once; only the presence moves.
 */
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { useCallback, useEffect, useRef, useState } from "react";

import { useThemeValue } from "@/hooks/useTheme";
import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { piecePath } from "../../live/adapters/whiteboard";
import { LivePresence, presenceTint } from "../../live/LivePresence";
import { presenceActive } from "../../live/liveChanges";
import { gesture } from "../../live/writing";
import { useAgentActivity } from "../../live/agentActivity";
import { PRESENCE_LINGER_MS, authorName, useNodeLive } from "../../live/liveStore";
import { LivePlayer, type PresenceElements, type RevealUnit } from "../../live/playback";
import type { BuildListener, GrowPiece, LiveBuild, PieceBox, PieceStroke } from "./liveBuild";

/** How long the hand takes to draw a piece of each kind, at natural speed (a long batch is compressed). */
const DRAW_MS: Record<PieceStroke["kind"], number> = { shape: 420, frame: 480, line: 380, text: 0 };

/** A text is typed: longer texts take longer, within bounds. */
function drawMs(stroke: PieceStroke): number {
  return stroke.kind === "text" ? Math.min(900, 220 + stroke.chars * 22) : DRAW_MS[stroke.kind];
}

/** A stroke's path on screen: the piece's box in scene units maps onto its marker's box. */
function screenPath(stroke: PieceStroke, box: PieceBox, marker: DOMRect): Array<{ x: number; y: number }> {
  const zoom = box.w > 0 ? marker.width / box.w : box.h > 0 ? marker.height / box.h : 1;
  return stroke.path.map(([x, y]) => ({ x: marker.left + (x - box.x) * zoom, y: marker.top + (y - box.y) * zoom }));
}

const SVG_NS = "http://www.w3.org/2000/svg";
/** The person's own hands on the board: the play finishes at once. */
const PERSON_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

export function BoardPresence({
  nodeId,
  build,
  api,
}: {
  nodeId: string;
  build: LiveBuild;
  api: () => ExcalidrawImperativeAPI | null;
}) {
  const t = useT();
  const theme = useThemeValue();
  const assistantName = useEventStore((s) => s.assistantName);
  const live = useNodeLive((s) => s.nodes[nodeId] ?? null);
  const activity = useAgentActivity(live?.sessionId ?? "");
  const authors = useNodeLive((s) =>
    Object.values(s.nodes)
      .filter((n) => n.building && n.author !== null)
      .map((n) => n.author!.id)
      .sort()
      .join("\n"),
  );

  /* Presence lingers a moment after the build ended, then fades. */
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (!live || live.building || live.settledAt === 0) return;
    const left = live.settledAt + PRESENCE_LINGER_MS - Date.now();
    if (left <= 0) return;
    const timer = window.setTimeout(() => setClock(Date.now()), left + 20);
    return () => window.clearTimeout(timer);
  }, [live]);
  const storeActive = presenceActive(live, Math.max(clock, live?.settledAt ?? 0));

  /* A play with no push behind it (the board opened on fresh work) shows presence too. */
  const [replaying, setReplaying] = useState(false);
  const visible = storeActive || replaying;

  const host = useRef<HTMLDivElement>(null);
  const markers = useRef<SVGSVGElement>(null);
  const layer = useRef<SVGGElement>(null);
  const view = useRef<PresenceElements | null>(null);
  const player = useRef<LivePlayer | null>(null);
  const unscroll = useRef<(() => void) | null>(null);
  const lingerTimer = useRef(0);

  const onReady = useCallback((elements: PresenceElements | null) => {
    view.current = elements;
  }, []);

  /** The markers' layer follows the canvas: scene units to pixels. */
  const place = useCallback(() => {
    const state = api()?.getAppState();
    if (!state || !layer.current) return;
    const zoom = state.zoom.value;
    layer.current.setAttribute("transform", `translate(${state.scrollX * zoom} ${state.scrollY * zoom}) scale(${zoom})`);
  }, [api]);

  const destroyPlayer = useCallback(() => {
    player.current?.destroy();
    player.current = null;
    unscroll.current?.();
    unscroll.current = null;
    layer.current?.replaceChildren();
  }, []);

  useEffect(() => {
    if (!visible) destroyPlayer();
  }, [visible, destroyPlayer]);
  useEffect(() => () => destroyPlayer(), [destroyPlayer]);

  /* The build tells the presence where each piece will land. */
  useEffect(() => {
    const listener: BuildListener = {
      begin: (boxes: PieceBox[], strokes: PieceStroke[], grow: GrowPiece) => {
        const hostEl = host.current;
        const group = layer.current;
        const boardEl = hostEl?.parentElement;
        if (!hostEl || !boardEl || !group || !view.current) return false;
        window.clearTimeout(lingerTimer.current);
        setReplaying(true);
        if (!player.current) {
          player.current = new LivePlayer(hostEl, view.current);
          // The edge chip on a board: pan to the piece being drawn (a canvas has no scrolling to follow).
          player.current.onJump = (marker) => {
            const id = (marker.getAttribute("data-live-path") ?? "").replace(/^\/elements\//, "");
            const editor = api();
            const target = editor?.getSceneElements().find((element) => element.id === id);
            if (editor && target) editor.scrollToContent([target] as never, { animate: true, duration: 320 });
          };
        }
        if (!unscroll.current) unscroll.current = api()?.onScrollChange(place) ?? null;
        group.replaceChildren();
        place();
        // Each piece is drawn by the agent's hand: the cursor drags a box out from its
        // corner, pulls an arrow along its points, types a text; the piece grows under
        // it and lands when the hand lets go (`grow`).
        const units: RevealUnit[] = boxes.map((box, index) => {
          const rect = document.createElementNS(SVG_NS, "rect");
          rect.setAttribute("x", String(box.x));
          rect.setAttribute("y", String(box.y));
          rect.setAttribute("width", String(Math.max(1, box.w)));
          rect.setAttribute("height", String(Math.max(1, box.h)));
          rect.setAttribute("fill", "none");
          rect.setAttribute("data-live-path", piecePath([box.id]));
          group.appendChild(rect);
          const stroke = strokes[index];
          return {
            elements: [rect],
            visible: true,
            motion: gesture({
              element: rect,
              durationMs: drawMs(stroke),
              steps: stroke.kind === "text" ? Math.max(4, Math.min(20, stroke.chars)) : 16,
              path: (marker) => screenPath(stroke, box, marker),
              progress: (share) => grow(index, share),
            }),
          };
        });
        player.current.play(units);
        return true;
      },
      finished: () => player.current?.finish(),
      done: () => {
        window.clearTimeout(lingerTimer.current);
        lingerTimer.current = window.setTimeout(() => setReplaying(false), PRESENCE_LINGER_MS);
      },
    };
    build.attach(listener);
    return () => {
      build.attach(null);
      window.clearTimeout(lingerTimer.current);
    };
  }, [build, api, place]);

  /* The person's hands: land everything at once. */
  useEffect(() => {
    const root = host.current?.parentElement;
    if (!root) return;
    const stop = () => {
      player.current?.interrupt();
      build.finish();
    };
    for (const name of PERSON_EVENTS) root.addEventListener(name, stop, { capture: true, passive: true });
    return () => {
      for (const name of PERSON_EVENTS) root.removeEventListener(name, stop, { capture: true });
    };
  }, [build]);

  const name = authorName(live?.author, assistantName);
  const drawing = t("nodes.whiteboard.live.drawing").replace("{assistant}", () => name);
  const status = live?.step || (activity ? `${name} · ${activity}` : drawing);
  const tint = live?.author ? presenceTint(live.author.id, authors ? authors.split("\n") : [], theme === "dark") : null;
  return (
    <>
      <LivePresence
        ref={host}
        name={name}
        status={status}
        visible={visible}
        building={Boolean(live?.building) || replaying}
        tint={tint}
        onReady={onReady}
        onJump={() => player.current?.resume()}
        jumpLabel={t("nodes.live.jump").replace("{agent}", () => name)}
      />
      <svg
        ref={markers}
        aria-hidden="true"
        data-testid="board-markers"
        className="pointer-events-none absolute left-0 top-0"
        width="1"
        height="1"
        style={{ overflow: "visible", visibility: "hidden" }}
      >
        <g ref={layer} />
      </svg>
    </>
  );
}
