/**
 * The live build inside a node editor: an agent's edits played back with its
 * presence, for every editor built on `EditorShell`.
 *
 * The push (`liveStore`) tells the open editor that the node changed; the
 * editor takes the new spec as it always does (`useNodeSpecEditor`) and
 * reports it as `remote`. This layer then:
 *
 * 1. finds what the batch changed in the editor's body: the DOM changes it
 *    watched between the push and the editor drawing the new spec;
 * 2. asks the type's reveal adapter (`adapters/<type>.ts`) for the steps;
 * 3. hands them to the player (`playback.ts`), which hides the units and
 *    fades them back in reading order, moving the frame and the cursor.
 *
 * Only an agent's revision plays. A person's save, from this window or
 * another, is taken as before and shows no presence. Opened while an agent is
 * building, the node's blocks fade in once.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

import { useThemeValue } from "@/hooks/useTheme";
import { fill, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import type { NodeSpecEditor } from "../editors/useNodeSpecEditor";
import { revealAdapter } from "./adapters";
import { LivePresence, presenceTint } from "./LivePresence";
import { PRESENCE_LINGER_MS, changesBetween, presenceActive, useNodeLive } from "./liveStore";
import {
  LIVE_TIMING,
  LivePlayer,
  changedElements,
  prefersReducedMotion,
  unitsFor,
  type PresenceElements,
} from "./playback";
import type { RevealStep } from "./reveal";

type Capture = { state: "off" | "armed" | "playing"; records: MutationRecord[]; until: number };

/** The person's own hands in the node: the playback finishes and the view stays theirs. */
const PERSON_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

export function LiveBuildLayer({
  // The layer reads only the editor's id and remote revisions; the spec's type does not matter.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  editor,
  body,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  editor: NodeSpecEditor<any>;
  body: RefObject<HTMLElement | null>;
}) {
  const t = useT();
  const theme = useThemeValue();
  const nodeId = editor.nodeId;
  const live = useNodeLive((s) => s.nodes[nodeId] ?? null);
  const authors = useNodeLive((s) =>
    Object.values(s.nodes)
      .filter((n) => n.building && n.author !== null)
      .map((n) => n.author!.id)
      .sort()
      .join("\n"),
  );
  const assistantName = useEventStore((s) => s.assistantName);

  /* Presence lingers a moment after the build ended, then fades. */
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (!live || live.building || live.settledAt === 0) return;
    const left = live.settledAt + PRESENCE_LINGER_MS - Date.now();
    if (left <= 0) return;
    const timer = window.setTimeout(() => setClock(Date.now()), left + 20);
    return () => window.clearTimeout(timer);
  }, [live]);
  const active = presenceActive(live, Math.max(clock, live?.settledAt ?? 0));

  /* The player lives while the presence shows. */
  const host = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<PresenceElements | null>(null);
  const player = useRef<LivePlayer | null>(null);
  const ensurePlayer = useCallback((): LivePlayer | null => {
    if (player.current) return player.current;
    if (!host.current || !body.current || !view) return null;
    player.current = new LivePlayer(host.current, view);
    return player.current;
  }, [body, view]);
  useEffect(() => {
    if (!active) {
      player.current?.destroy();
      player.current = null;
    }
  }, [active]);
  useEffect(
    () => () => {
      player.current?.destroy();
      player.current = null;
    },
    [],
  );

  /* What changes in the body, from the push until the editor drew the new spec. */
  const capture = useRef<Capture>({ state: "off", records: [], until: 0 });
  const observer = useRef<MutationObserver | null>(null);
  useEffect(() => {
    const root = body.current;
    if (!root || typeof MutationObserver === "undefined") return;
    const watch = new MutationObserver((records) => {
      const now = capture.current;
      if (now.state === "armed") {
        now.records.push(...records);
      } else if (now.state === "playing" && performance.now() < now.until) {
        // An editor that draws after React (a text editor) joins the batch here,
        // before the browser paints, so nothing flashes at full strength.
        const late = changedElements(records, root);
        if (late.length > 0) player.current?.add(late.map((el) => ({ elements: [el] })));
      }
    });
    watch.observe(root, { childList: true, characterData: true, subtree: true });
    observer.current = watch;
    return () => {
      watch.disconnect();
      observer.current = null;
    };
  }, [body]);

  /* The push for this node arms the capture: the editor fetches and draws next. */
  useEffect(
    () =>
      useNodeLive.subscribe((state, previous) => {
        const now = state.nodes[nodeId];
        const before = previous.nodes[nodeId];
        if (!now || now.changes.length === 0 || now === before) return;
        const last = now.changes[now.changes.length - 1];
        if (before && before.changes[before.changes.length - 1] === last) return;
        if (last.author.kind !== "assistant") return;
        observer.current?.takeRecords();
        capture.current = { state: "armed", records: [], until: 0 };
      }),
    [nodeId],
  );

  /* The person's hands: finish at once, and let the view be. */
  useEffect(() => {
    const root = body.current;
    if (!root) return;
    const stop = () => {
      capture.current = { state: "off", records: [], until: 0 };
      player.current?.interrupt();
    };
    for (const name of PERSON_EVENTS) root.addEventListener(name, stop, { capture: true, passive: true });
    return () => {
      for (const name of PERSON_EVENTS) root.removeEventListener(name, stop, { capture: true });
    };
  }, [body]);

  /** Play an adapter's steps; a type adapter whose targets are not drawn yet is asked once more. */
  const playSteps = useCallback(
    (steps: (root: HTMLElement) => RevealStep[], changed: Element[], retry: boolean) => {
      const root = body.current;
      const playing = ensurePlayer();
      if (!root || !playing) return;
      const units = unitsFor(steps(root), root, changed);
      playing.play(units);
      if (units.length === 0 && retry) {
        window.setTimeout(() => {
          if (player.current !== playing) return;
          const again = unitsFor(steps(root), root, []);
          if (again.length > 0) playing.add(again);
        }, LIVE_TIMING.settleWaitMs);
      }
    },
    [body, ensurePlayer],
  );

  /* A revision the editor took by itself: play it back when an agent wrote it. */
  const remote = editor.remote ?? null;
  useLayoutEffect(() => {
    if (remote === null) return;
    const node = useNodeLive.getState().nodes[nodeId];
    const range = changesBetween(node, remote.fromVersion, remote.version);
    const root = body.current;
    if (!node || !range.agent || !root) {
      capture.current = { state: "off", records: [], until: 0 };
      return;
    }
    const records = [...capture.current.records, ...(observer.current?.takeRecords() ?? [])];
    capture.current = { state: "playing", records: [], until: performance.now() + LIVE_TIMING.captureMs };
    const changed = changedElements(records, root);
    const adapter = revealAdapter(node.nodeType);
    playSteps(
      (at) => adapter.steps({ type: node.nodeType, previous: remote.previous, next: remote.next, ops: range.ops, initial: false, root: at }),
      changed,
      true,
    );
    // Only `seq` says that a new revision arrived.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote?.seq]);

  /* Opened while an agent builds (the node window opening by itself on its
   * create): what is there fades in once, top to bottom. An editor that was
   * open before the agent started plays only the agent's edits. */
  const openedMidBuild = useRef<boolean | null>(null);
  if (openedMidBuild.current === null) openedMidBuild.current = presenceActive(useNodeLive.getState().nodes[nodeId]);
  const openedPlayed = useRef(false);
  useEffect(() => {
    if (!openedMidBuild.current || openedPlayed.current || !active || !view || !live || remote !== null) return;
    const root = body.current;
    if (!root) return;
    const reduced = prefersReducedMotion();
    // Hidden until its blocks are known, so the page does not show and then fade.
    const hold = !reduced && typeof root.animate === "function"
      ? root.animate([{ opacity: 0 }, { opacity: 0 }], { duration: 600_000, fill: "forwards" })
      : null;
    const timer = window.setTimeout(() => {
      openedPlayed.current = true;
      hold?.cancel();
      const adapter = revealAdapter(live.nodeType);
      playSteps(
        (at) => adapter.steps({ type: live.nodeType, previous: null, next: editor.spec, ops: null, initial: true, root: at }),
        [],
        false,
      );
    }, LIVE_TIMING.settleWaitMs);
    return () => {
      window.clearTimeout(timer);
      hold?.cancel();
    };
    // Once, when the presence first shows over this editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, view]);

  if (!live || live.author === null) return null;
  const name = live.author.name || assistantName || "Dodaios";
  const status = live.step || fill(t("nodes.live.working"), { name });
  const tint = presenceTint(live.author.id, authors ? authors.split("\n") : [], theme === "dark");
  return (
    <LivePresence
      ref={host}
      name={name}
      status={status}
      visible={active}
      building={live.building}
      tint={tint}
      onReady={setView}
    />
  );
}
