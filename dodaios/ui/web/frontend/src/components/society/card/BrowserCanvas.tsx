/**
 * The live picture of an agent's browser, with the person's input while they
 * hold control and the agent's arrow while it drives. Shared by the agent
 * card's preview and the chat's browser stage, so both forward exactly the
 * same input and never two different interpretations of a click.
 */
import { useRef, type RefObject } from "react";
import { cn } from "@/lib/utils";
import { AgentCursor } from "./AgentCursor";
import { browserPoint } from "./browserInput";
import type { BrowserViewState } from "./useBrowserView";

export type BrowserControl = (op: string, args?: Record<string, unknown>) => void;

interface BrowserCanvasProps {
  canvas: RefObject<HTMLCanvasElement>;
  state: BrowserViewState;
  control: BrowserControl;
  /** The view is attached to a running browser. */
  live: boolean;
  ariaLabel: string;
  /** A name tag on the agent's arrow (who drives). */
  cursorLabel?: string;
  className?: string;
}

export function BrowserCanvas({ canvas, state, control, live, ariaLabel, cursorLabel, className }: BrowserCanvasProps) {
  const lastHoverAt = useRef(0);
  return (
    <>
      <canvas ref={canvas} width={1280} height={800} tabIndex={live && state.manual && !state.previewPaused ? 0 : -1}
        aria-label={ariaLabel}
        className={cn("block max-h-full max-w-full object-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring", className)}
        style={{ aspectRatio: "16/10", width: "100%", height: "100%", objectFit: "contain" }}
        onClick={(e) => {
          if (!live || !state.ready) return;
          e.currentTarget.focus();
          const point = browserPoint(e.currentTarget, e.clientX, e.clientY);
          if (point) control("click", { ...point, ...(state.extendedInput && e.detail === 2 ? { count: 2 } : {}) });
        }}
        onContextMenu={(e) => {
          if (!live || !state.ready) return;
          e.preventDefault();
          if (!state.extendedInput) return;
          e.currentTarget.focus();
          const point = browserPoint(e.currentTarget, e.clientX, e.clientY);
          if (point) control("click", { ...point, button: "right" });
        }}
        onAuxClick={(e) => {
          if (!live || !state.ready || e.button !== 1 || !state.extendedInput) return;
          e.preventDefault();
          e.currentTarget.focus();
          const point = browserPoint(e.currentTarget, e.clientX, e.clientY);
          if (point) control("click", { ...point, button: "middle" });
        }}
        onMouseMove={(e) => {
          if (!live || !state.ready || !state.manual || !state.extendedInput || !state.connected) return;
          const now = performance.now();
          if (now - lastHoverAt.current < 33) return;
          const point = browserPoint(e.currentTarget, e.clientX, e.clientY);
          // Older running backends already forward click arguments. This
          // keeps hover compatible while only the browser worker reloads.
          if (point) { lastHoverAt.current = now; control("click", { ...point, move_only: true }); }
        }}
        onWheel={(e) => {
          if (!live || !state.ready || document.activeElement !== e.currentTarget) return;
          const point = browserPoint(e.currentTarget, e.clientX, e.clientY);
          if (point) control("scroll", { ...point, dx: e.deltaX, dy: e.deltaY });
        }}
        onPaste={(e) => {
          if (!live || !state.ready || document.activeElement !== e.currentTarget) return;
          e.preventDefault();
          control("text", { text: e.clipboardData.getData("text/plain") });
        }}
        onKeyDown={(e) => {
          if (!live || !state.ready || (!state.manual && document.activeElement !== e.currentTarget)) return;
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") return;
          e.preventDefault();
          e.stopPropagation();
          if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) control("text", { text: e.key });
          else if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) {
            const modifiers = [e.ctrlKey ? "Control" : "", e.metaKey ? "Meta" : "",
              e.altKey ? "Alt" : "", e.shiftKey ? "Shift" : ""].filter(Boolean);
            control("key", { key: [...modifiers, e.key].join("+") });
          }
        }} />
      {(!state.fullWindow || state.pointer?.native_window === true) && (
        <AgentCursor pointer={state.ready && state.connected && !state.manual ? state.pointer : undefined}
          label={cursorLabel} />
      )}
    </>
  );
}
