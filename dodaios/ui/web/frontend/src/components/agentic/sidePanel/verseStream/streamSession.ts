import { isAllowedMessage } from "./panelInput";

/**
 * One Pixel Streaming 2 view of the running Verse in the IDE side panel (WP20.3).
 *
 * Speaks `verse.signal/1` with the backend (`dodaios/verse_host/signal.py`): a ticket from
 * `POST /api/verse/signal/ticket`, then `hello {protocol, ticket, w, h, dpr}` as the first frame,
 * then the plugin's own signalling messages (`config`, `listStreamers` / `streamerList`,
 * `subscribe`, `offer`, `answer`, `iceCandidate`). The socket being open is what tells the Verse
 * the panel is visible; `stop()` closes it at once, so the stream stops within a second of the
 * panel being hidden (A20.1). `verse.streamState` relays the Verse's `panel.stream_state`.
 *
 * Plain browser WebRTC; no STUN or TURN server is ever configured.
 */

export const SIGNAL_PROTOCOL = "verse.signal/1";
export const TICKET_PATH = "/api/verse/signal/ticket";
/** Time a visible panel waits for the first video frame before it shows the fallback card. */
export const START_TIMEOUT_MS = 15_000;

export type StreamPhase = "connecting" | "streaming" | "verse_open" | "unavailable" | "failed";

export interface PanelGeometry {
  w: number;
  h: number;
  dpr: number;
}

export interface SignalTicket {
  ticket: string;
  path: string;
  protocol: string;
}

export interface SocketLike {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export interface StreamDeps {
  /** A ticket, or null when the backend has no Verse host (feature off, not installed). */
  fetchTicket(): Promise<SignalTicket | null>;
  openSocket(url: string): SocketLike;
  createPeer(config: RTCConfiguration): RTCPeerConnection;
  /** Absolute ws:// URL for a backend path. */
  socketUrl(path: string): string;
  setTimer(callback: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
}

export interface StreamListener {
  onPhase(phase: StreamPhase, detail?: string): void;
  onStream(stream: MediaStream | null): void;
}

const WS_OPEN = 1;

export function browserDeps(): StreamDeps {
  return {
    async fetchTicket() {
      const res = await fetch(TICKET_PATH, { method: "POST", cache: "no-store", credentials: "same-origin" });
      if (res.status === 404 || res.status === 503) return null;
      if (!res.ok) throw new Error(`ticket ${res.status}`);
      return (await res.json()) as SignalTicket;
    },
    openSocket: (url) => new WebSocket(url) as unknown as SocketLike,
    createPeer: (config) => new RTCPeerConnection(config),
    socketUrl: (path) => `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}${path}?role=player`,
    setTimer: (callback, ms) => window.setTimeout(callback, ms),
    clearTimer: (handle) => window.clearTimeout(handle as number),
  };
}

export class VerseStreamSession {
  private socket: SocketLike | null = null;
  private peer: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private phase: StreamPhase | null = null;
  private stopped = false;
  private startTimer: unknown = null;
  private geometry: PanelGeometry;

  constructor(
    private readonly deps: StreamDeps,
    geometry: PanelGeometry,
    private readonly listener: StreamListener,
  ) {
    this.geometry = { ...geometry };
  }

  get currentPhase(): StreamPhase | null {
    return this.phase;
  }

  async start(): Promise<void> {
    this.setPhase("connecting");
    let ticket: SignalTicket | null;
    try {
      ticket = await this.deps.fetchTicket();
    } catch {
      if (!this.stopped) this.setPhase("failed", "ticket");
      return;
    }
    if (this.stopped) return;
    if (ticket === null || ticket.protocol !== SIGNAL_PROTOCOL) {
      this.setPhase("unavailable");
      return;
    }
    const socket = this.deps.openSocket(this.deps.socketUrl(ticket.path));
    this.socket = socket;
    socket.onopen = () => {
      this.send({ type: "hello", protocol: SIGNAL_PROTOCOL, ticket: ticket.ticket, ...this.geometry });
    };
    socket.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      let message: Record<string, unknown>;
      try {
        message = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        return;
      }
      void this.onMessage(message);
    };
    socket.onclose = (event) => {
      if (this.stopped || this.socket !== socket) return;
      this.closePeer();
      this.socket = null;
      if (event.code === 1013) this.setPhase("unavailable");
      else if (this.phase !== "verse_open") this.setPhase("failed", `closed_${event.code}`);
    };
    socket.onerror = () => {
      /* onclose follows and decides */
    };
    this.armStartTimer();
  }

  /** The panel changed size while visible. */
  resize(geometry: PanelGeometry): void {
    if (geometry.w === this.geometry.w && geometry.h === this.geometry.h && geometry.dpr === this.geometry.dpr) return;
    this.geometry = { ...geometry };
    this.send({ type: "panel.resize", ...this.geometry });
  }

  /** The panel was hidden: close everything now. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.clearStartTimer();
    this.closePeer();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.onmessage = null;
      try {
        socket.close(1000, "panel hidden");
      } catch {
        /* already closed */
      }
    }
  }

  /** Send one encoded input message over the data channel; false when dropped. */
  sendInput(message: Uint8Array | null): boolean {
    if (!message || !isAllowedMessage(message)) return false;
    const channel = this.channel;
    if (!channel || channel.readyState !== "open" || this.phase !== "streaming") return false;
    channel.send(message as Uint8Array<ArrayBuffer>);
    return true;
  }

  private setPhase(phase: StreamPhase, detail?: string): void {
    if (this.phase === phase) return;
    this.phase = phase;
    if (phase !== "connecting") this.clearStartTimer();
    this.listener.onPhase(phase, detail);
  }

  private armStartTimer(): void {
    this.clearStartTimer();
    this.startTimer = this.deps.setTimer(() => {
      this.startTimer = null;
      if (!this.stopped && this.phase === "connecting") this.setPhase("failed", "timeout");
    }, START_TIMEOUT_MS);
  }

  private clearStartTimer(): void {
    if (this.startTimer !== null) {
      this.deps.clearTimer(this.startTimer);
      this.startTimer = null;
    }
  }

  private send(message: Record<string, unknown>): void {
    const socket = this.socket;
    if (socket && socket.readyState === WS_OPEN) socket.send(JSON.stringify(message));
  }

  private async onMessage(message: Record<string, unknown>): Promise<void> {
    if (this.stopped) return;
    switch (message.type) {
      case "config":
        this.send({ type: "listStreamers" });
        return;
      case "streamerList": {
        const ids = Array.isArray(message.ids) ? (message.ids as unknown[]) : [];
        if (typeof ids[0] === "string") this.send({ type: "subscribe", streamerId: ids[0] });
        return;
      }
      case "verse.streamState":
        this.onStreamState(String(message.state ?? ""), typeof message.error === "string" ? message.error : undefined);
        return;
      case "offer":
        await this.onOffer(String(message.sdp ?? ""));
        return;
      case "iceCandidate":
        await this.onRemoteCandidate(message.candidate);
        return;
      default:
        return;
    }
  }

  private onStreamState(state: string, error?: string): void {
    if (state === "stopped" && error === "full_view_open") {
      // The full Verse window won: keep the last frame, stop decoding (A20.4).
      this.setPhase("verse_open");
      this.closePeer();
      return;
    }
    if (state === "failed") {
      this.closePeer();
      this.setPhase("failed", error);
      return;
    }
    if ((state === "starting" || state === "streaming") && !this.peer) {
      if (this.phase === "verse_open" || this.phase === "failed") {
        this.setPhase("connecting");
        this.armStartTimer();
      }
      this.send({ type: "subscribe", streamerId: "" });
    }
  }

  private ensurePeer(): RTCPeerConnection {
    if (this.peer) return this.peer;
    const peer = this.deps.createPeer({ iceServers: [], bundlePolicy: "max-bundle" });
    this.peer = peer;
    peer.onicecandidate = (event) => {
      if (event.candidate) this.send({ type: "iceCandidate", candidate: event.candidate.toJSON() });
    };
    peer.ontrack = (event) => {
      const stream = event.streams[0] ?? new MediaStream([event.track]);
      this.listener.onStream(stream);
      this.setPhase("streaming");
    };
    peer.ondatachannel = (event) => {
      this.channel = event.channel;
      this.channel.binaryType = "arraybuffer";
    };
    peer.onconnectionstatechange = () => {
      if (this.peer !== peer || this.stopped) return;
      if (peer.connectionState === "failed") {
        this.closePeer();
        this.setPhase("failed", "ice");
      }
    };
    return peer;
  }

  private async onOffer(sdp: string): Promise<void> {
    if (!sdp) return;
    const peer = this.ensurePeer();
    try {
      await peer.setRemoteDescription({ type: "offer", sdp });
      const answer = await peer.createAnswer();
      await peer.setLocalDescription(answer);
      if (this.stopped || this.peer !== peer) return;
      this.send({ type: "answer", sdp: peer.localDescription?.sdp ?? answer.sdp ?? "" });
    } catch {
      this.closePeer();
      this.setPhase("failed", "sdp");
    }
  }

  private async onRemoteCandidate(candidate: unknown): Promise<void> {
    const peer = this.peer;
    if (!peer || !candidate || typeof candidate !== "object") return;
    try {
      await peer.addIceCandidate(candidate as RTCIceCandidateInit);
    } catch {
      /* a candidate the browser cannot use is skipped */
    }
  }

  private closePeer(): void {
    const peer = this.peer;
    this.peer = null;
    this.channel = null;
    if (peer) {
      peer.ontrack = null;
      peer.onicecandidate = null;
      peer.ondatachannel = null;
      peer.onconnectionstatechange = null;
      try {
        peer.close();
      } catch {
        /* already closed */
      }
    }
  }
}
