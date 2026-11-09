import { describe, expect, it } from "vitest";
import { encodeKey, encodeMouseMove } from "./panelInput";
import { START_TIMEOUT_MS, VerseStreamSession, type StreamPhase } from "./streamSession";
import { fakeWorld, flush, FakeChannel } from "./testFakes";

function harness(ticket?: Parameters<typeof fakeWorld>[0]) {
  const world = ticket === undefined ? fakeWorld() : fakeWorld(ticket);
  const phases: StreamPhase[] = [];
  const streams: (MediaStream | null)[] = [];
  const session = new VerseStreamSession(world.deps, { w: 480, h: 320, dpr: 1.5 }, {
    onPhase: (phase) => phases.push(phase),
    onStream: (stream) => streams.push(stream),
  });
  return { world, phases, streams, session };
}

async function streaming() {
  const h = harness();
  await h.session.start();
  const socket = h.world.sockets[0];
  socket.open();
  socket.receive({ type: "config", peerConnectionOptions: { iceServers: [] } });
  socket.receive({ type: "verse.streamState", state: "stopped" });
  socket.receive({ type: "streamerList", ids: ["Verse"] });
  socket.receive({ type: "offer", sdp: "v=0\r\noffer\r\n" });
  await flush();
  const channel = h.world.peers[0].connect(new FakeChannel());
  return { ...h, socket, channel };
}

describe("VerseStreamSession", () => {
  it("follows verse.signal/1: hello first, then the plugin's signalling", async () => {
    const { world, phases, streams, socket } = await streaming();
    expect(socket.url).toBe("ws://127.0.0.1:8765/api/verse/signal?role=player");
    expect(socket.sent[0]).toEqual({ type: "hello", protocol: "verse.signal/1", ticket: "tk-1", w: 480, h: 320, dpr: 1.5 });
    expect(socket.types()).toEqual(["hello", "listStreamers", "subscribe", "answer"]);
    expect(socket.sent[2]).toEqual({ type: "subscribe", streamerId: "Verse" });
    expect(socket.sent[3]).toEqual({ type: "answer", sdp: "v=0\r\nanswer\r\n" });
    expect(world.peers[0].config.iceServers).toEqual([]);
    expect(world.peers[0].remote).toEqual({ type: "offer", sdp: "v=0\r\noffer\r\n" });
    expect(phases).toEqual(["connecting", "streaming"]);
    expect(streams).toHaveLength(1);
  });

  it("forwards local ICE candidates and applies remote ones", async () => {
    const { world, socket } = await streaming();
    const peer = world.peers[0];
    peer.onicecandidate?.({ candidate: { toJSON: () => ({ candidate: "candidate:1 1 udp 1 x.local 5 typ host", sdpMid: "0" }) } });
    expect(socket.sent.at(-1)).toEqual({ type: "iceCandidate", candidate: { candidate: "candidate:1 1 udp 1 x.local 5 typ host", sdpMid: "0" } });
    socket.receive({ type: "iceCandidate", candidate: { candidate: "candidate:2 1 udp 1 127.0.0.1 6 typ host", sdpMid: "0" } });
    await flush();
    expect(peer.candidates).toHaveLength(1);
  });

  it("sends only allowed input over the data channel", async () => {
    const { session, channel } = await streaming();
    expect(session.sendInput(encodeKey(true, "KeyW"))).toBe(true);
    expect(session.sendInput(encodeKey(true, "Space"))).toBe(false);
    expect(session.sendInput(encodeKey(true, "KeyR"))).toBe(false);
    expect(session.sendInput(new Uint8Array([51, 0, 0]))).toBe(false); // console command
    expect(session.sendInput(encodeMouseMove({ x: 0.5, y: 0.5 }, { dx: 3, dy: -2 }, { width: 480, height: 320 }))).toBe(true);
    expect(channel.sent).toHaveLength(2);
    expect(channel.binaryType).toBe("arraybuffer");
  });

  it("stops at once: the socket closes inside stop()", async () => {
    const { session, socket, world } = await streaming();
    const before = performance.now();
    session.stop();
    expect(socket.closedWith).toBe(1000);
    expect(world.peers[0].closed).toBe(true);
    expect(performance.now() - before).toBeLessThan(1000);
    expect(session.sendInput(encodeKey(true, "KeyW"))).toBe(false);
  });

  it("keeps the last frame when the full view opens and resubscribes when it closes", async () => {
    const { session, socket, world, phases } = await streaming();
    socket.receive({ type: "verse.streamState", state: "stopped", error: "full_view_open" });
    expect(session.currentPhase).toBe("verse_open");
    expect(world.peers[0].closed).toBe(true);
    expect(session.sendInput(encodeKey(true, "KeyW"))).toBe(false);
    socket.receive({ type: "verse.streamState", state: "starting" });
    expect(session.currentPhase).toBe("connecting");
    expect(socket.sent.at(-1)).toEqual({ type: "subscribe", streamerId: "" });
    socket.receive({ type: "offer", sdp: "v=0\r\noffer2\r\n" });
    await flush();
    world.peers[1].connect();
    expect(phases).toEqual(["connecting", "streaming", "verse_open", "connecting", "streaming"]);
  });

  it("sends a resize only when the size changes", async () => {
    const { session, socket } = await streaming();
    session.resize({ w: 480, h: 320, dpr: 1.5 });
    session.resize({ w: 560, h: 360, dpr: 1.5 });
    session.resize({ w: 560, h: 360, dpr: 1.5 });
    expect(socket.sent.filter((m) => m.type === "panel.resize")).toEqual([{ type: "panel.resize", w: 560, h: 360, dpr: 1.5 }]);
  });

  it("is unavailable without a Verse host", async () => {
    const { session, phases, world } = harness(null);
    await session.start();
    expect(phases).toEqual(["connecting", "unavailable"]);
    expect(world.sockets).toHaveLength(0);
  });

  it("is unavailable when the socket closes 1013 and failed on other closes", async () => {
    const a = harness();
    await a.session.start();
    a.world.sockets[0].open();
    a.world.sockets[0].serverClose(1013);
    expect(a.phases.at(-1)).toBe("unavailable");

    const b = harness();
    await b.session.start();
    b.world.sockets[0].open();
    b.world.sockets[0].serverClose(4401);
    expect(b.phases.at(-1)).toBe("failed");
  });

  it("fails after the start timeout and on a failed stream state", async () => {
    const a = harness();
    await a.session.start();
    const timer = a.world.timers.find((t) => t.ms === START_TIMEOUT_MS && !t.cleared);
    expect(timer).toBeDefined();
    timer?.callback();
    expect(a.phases.at(-1)).toBe("failed");

    const { socket, session } = await streaming();
    socket.receive({ type: "verse.streamState", state: "failed", error: "encoder_unavailable" });
    expect(session.currentPhase).toBe("failed");
  });

  it("ignores everything after stop", async () => {
    const h = harness();
    const pending = h.session.start();
    h.session.stop();
    await pending;
    expect(h.world.sockets).toHaveLength(0);
    expect(h.phases).toEqual(["connecting"]);
  });
});
