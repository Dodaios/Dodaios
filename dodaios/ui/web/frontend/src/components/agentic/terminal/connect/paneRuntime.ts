import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import type { TerminalAppearance } from "../../terminalThemes";
import type { PaneSocket, PromptDelivery } from "../../paneSocket";
import type {
  AgenticTerminalProps,
  PaneStatus,
  PreservedTerminalViewport,
} from "../paneShared";

type Ref<T> = MutableRefObject<T>;
type Callback = (() => void) | null;

/**
 * What the connect effect reads from, and writes back into, its component.
 *
 * Everything here is either a prop captured when the effect ran, a stable ref,
 * or a state setter, so handing it to the segments below changes nothing about
 * what each closure sees.
 */
export interface PanePorts {
  name: string;
  workspaceId: string | undefined;
  displayName: string;
  sizeLead: boolean;
  /** The host element xterm opens into; the effect only runs once it exists. */
  container: HTMLDivElement;
  onStatusRef: Ref<AgenticTerminalProps["onStatus"]>;
  onAttachErrorRef: Ref<AgenticTerminalProps["onAttachError"]>;
  fontSizeRef: Ref<number>;
  appearanceRef: Ref<TerminalAppearance>;
  activeRef: Ref<boolean>;
  focusedRef: Ref<boolean>;
  layoutBusyRef: Ref<boolean>;
  termRef: Ref<Terminal | null>;
  fitRef: Ref<FitAddon | null>;
  resizeRef: Ref<Callback>;
  claimResizeRef: Ref<Callback>;
  returnResizeRef: Ref<Callback>;
  repaintOnReturnRef: Ref<Callback>;
  takeOwnershipRef: Ref<Callback>;
  leadTokenRef: Ref<object>;
  heldLeadRef: Ref<boolean>;
  visibilityRef: Ref<{
    show: (afterFlush?: () => void) => void;
    park: () => void;
  } | null>;
  statusRef: Ref<PaneStatus>;
  setVisibleStatus: Dispatch<SetStateAction<PaneStatus>>;
  setStatusDetail: Dispatch<SetStateAction<string>>;
  setPainted: Dispatch<SetStateAction<boolean>>;
  setTailReady: Dispatch<SetStateAction<boolean>>;
  setTerminalEpoch: Dispatch<SetStateAction<number>>;
  setReceipt: Dispatch<SetStateAction<PromptDelivery | null>>;
  flashDelivered: (ms: number) => void;
  replayCurtainRef: Ref<boolean>;
  preservedViewportRef: Ref<PreservedTerminalViewport | null>;
  replayGenerationRef: Ref<number>;
  replayRevealFrameRef: Ref<number | undefined>;
  settleRebuildRef: Ref<
    ((generation: number, reveal: () => void) => void) | null
  >;
  armCurtainWatchdog: () => void;
}

/**
 * The connect effect's mutable locals that more than one segment touches.
 *
 * They used to be `let`s in one closure; the segments now live in separate
 * files, so they live on this one object instead. It is created fresh by every
 * run of the effect, exactly as the closure was.
 */
export interface PaneState {
  /** Set while the Verse window is showing this xterm. */
  presentedHost: HTMLElement | null;
  /** Did the grid come from the tile, or is it still the constructed default? */
  mountMeasured: boolean;
  /** Did the handshake go out without a size? Output waits for the report. */
  awaitingSizeReport: boolean;
  socket: PaneSocket | null;
  disposed: boolean;
  troubleShown: "retrying" | "unreachable" | null;
  troubleText: string;
  /** Writes handed to xterm that have not finished parsing. */
  parsing: number;
  resumeResize: Callback;
  settleReveal: Callback;
  settlingFor: number;
  /** The size the terminal process has actually been told. */
  sentSize: { cols: number; rows: number } | null;
  owned: boolean;
  displaced: boolean;
  resizeTimer: number | undefined;
  dragRefitTimer: number | undefined;
  io: IntersectionObserver | null;
}
