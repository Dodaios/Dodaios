import type { SignalTicket, SocketLike, StreamDeps } from "./streamSession";

/** Test doubles for the panel stream: a scripted signalling socket, peer and data channel. */

export class FakeSocket implements SocketLike {
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  sent: Record<string, unknown>[] = [];
  closedWith: number | null = null;

  constructor(readonly url: string) {}

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  receive(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  serverClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(code?: number): void {
    this.readyState = 3;
    this.closedWith = code ?? 1000;
  }

  types(): string[] {
    return this.sent.map((m) => String(m.type));
  }
}

export class FakeChannel {
  readyState: RTCDataChannelState = "open";
  binaryType = "blob";
  sent: Uint8Array[] = [];
  send(data: Uint8Array): void {
    this.sent.push(data);
  }
}

export class FakePeer {
  config: RTCConfiguration;
  closed = false;
  remote: RTCSessionDescriptionInit | null = null;
  localDescription: { sdp: string } | null = null;
  candidates: RTCIceCandidateInit[] = [];
  connectionState: RTCPeerConnectionState = "new";
  onicecandidate: ((event: { candidate: { toJSON(): RTCIceCandidateInit } | null }) => void) | null = null;
  ontrack: ((event: { streams: MediaStream[]; track: MediaStreamTrack }) => void) | null = null;
  ondatachannel: ((event: { channel: FakeChannel }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;

  constructor(config: RTCConfiguration) {
    this.config = config;
  }

  async setRemoteDescription(description: RTCSessionDescriptionInit): Promise<void> {
    this.remote = description;
  }
  async createAnswer(): Promise<RTCSessionDescriptionInit> {
    return { type: "answer", sdp: "v=0\r\nanswer\r\n" };
  }
  async setLocalDescription(description: RTCSessionDescriptionInit): Promise<void> {
    this.localDescription = { sdp: description.sdp ?? "" };
  }
  async addIceCandidate(candidate: RTCIceCandidateInit): Promise<void> {
    this.candidates.push(candidate);
  }
  close(): void {
    this.closed = true;
  }

  /** The browser received the remote video track and the plugin's data channel. */
  connect(channel = new FakeChannel()): FakeChannel {
    this.ondatachannel?.({ channel });
    this.ontrack?.({ streams: [{ id: "stream" } as MediaStream], track: {} as MediaStreamTrack });
    return channel;
  }
}

export interface FakeWorld {
  deps: StreamDeps;
  sockets: FakeSocket[];
  peers: FakePeer[];
  timers: { callback: () => void; ms: number; cleared: boolean }[];
  ticket: SignalTicket | null;
  ticketCalls: number;
}

export function fakeWorld(ticket: SignalTicket | null = { ticket: "tk-1", path: "/api/verse/signal", protocol: "verse.signal/1" }): FakeWorld {
  const world: FakeWorld = {
    sockets: [],
    peers: [],
    timers: [],
    ticket,
    ticketCalls: 0,
    deps: undefined as unknown as StreamDeps,
  };
  world.deps = {
    fetchTicket: async () => {
      world.ticketCalls += 1;
      return world.ticket;
    },
    openSocket: (url) => {
      const socket = new FakeSocket(url);
      world.sockets.push(socket);
      return socket;
    },
    createPeer: (config) => {
      const peer = new FakePeer(config);
      world.peers.push(peer);
      return peer as unknown as RTCPeerConnection;
    },
    socketUrl: (path) => `ws://127.0.0.1:8765${path}?role=player`,
    setTimer: (callback, ms) => {
      const timer = { callback, ms, cleared: false };
      world.timers.push(timer);
      return timer;
    },
    clearTimer: (handle) => {
      (handle as { cleared: boolean }).cleared = true;
    },
  };
  return world;
}

/** Let pending promise callbacks run. */
export async function flush(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}
