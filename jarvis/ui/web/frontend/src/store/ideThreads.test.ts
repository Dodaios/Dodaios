import { beforeEach, describe, expect, it } from "vitest";
import { useIdeThreadsStore } from "./ideThreads";

describe("ideThreads store", () => {
  beforeEach(() => {
    localStorage.clear();
    useIdeThreadsStore.setState({ layout: "grid", selection: { projectId: "", sessionId: null }, projectOf: {}, seen: {}, focusNonce: 0, beforeTeamDraft: null });
  });

  it("leaves the team start form for what was open before it", () => {
    const store = useIdeThreadsStore.getState();
    store.openThread("s1", "p1");
    store.newTeam("p1");
    store.newTeam("p1"); // a second click on the people icon keeps the way back
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: null, team: "new" });
    store.cancelTeamDraft();
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s1" });
    // Nothing to cancel once the form is gone.
    store.cancelTeamDraft();
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s1" });
  });

  it("opens a member's own thread with the team it leads back to, across a reload", () => {
    useIdeThreadsStore.getState().openMemberThread("s7", "p1", "t1");
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s7", fromTeam: "t1" });
    expect(JSON.parse(localStorage.getItem("jarvis.agenticIde.threadSelection.v1") ?? "null")).toEqual({ projectId: "p1", sessionId: "s7", fromTeam: "t1" });
    // An ordinary thread opened afterwards carries no way back.
    useIdeThreadsStore.getState().openThread("s8", "p1");
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s8" });
  });

  it("remembers the layout across a reload", () => {
    useIdeThreadsStore.getState().setLayout("threads");
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(localStorage.getItem("jarvis.agenticIde.layout.v1")).toBe('"threads"');
  });

  it("opens a draft, then adopts the session its first message created", () => {
    const store = useIdeThreadsStore.getState();
    store.newThread("p1");
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: null });
    expect(useIdeThreadsStore.getState().focusNonce).toBe(1);
    store.adoptThread("s1", "p1");
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s1" });
    expect(useIdeThreadsStore.getState().projectOf).toEqual({ s1: "p1" });
  });

  it("marks a thread seen only forward in time", () => {
    const store = useIdeThreadsStore.getState();
    store.markSeen("s1", 10);
    store.markSeen("s1", 5);
    expect(useIdeThreadsStore.getState().seen.s1).toBe(10);
  });

  it("forgets a deleted thread and leaves its project open on a draft", () => {
    const store = useIdeThreadsStore.getState();
    store.adoptThread("s1", "p1");
    store.markSeen("s1", 3);
    store.forgetThread("s1");
    const state = useIdeThreadsStore.getState();
    expect(state.projectOf).toEqual({});
    expect(state.seen).toEqual({});
    expect(state.selection).toEqual({ projectId: "p1", sessionId: null });
  });
});
