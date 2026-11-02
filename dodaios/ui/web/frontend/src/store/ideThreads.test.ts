import { beforeEach, describe, expect, it } from "vitest";
import { MAX_THREAD_COLUMNS, threadColumns, useIdeThreadsStore } from "./ideThreads";

describe("ideThreads store", () => {
  beforeEach(() => {
    localStorage.clear();
    useIdeThreadsStore.setState({ layout: "grid", selection: { projectId: "", sessionId: null }, projectOf: {}, seen: {}, focusNonce: 0, beforeTeamDraft: null, split: [], mainAt: 0 });
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

  describe("side-by-side columns", () => {
    const ids = () => {
      const { split, mainAt } = useIdeThreadsStore.getState();
      return threadColumns(split, mainAt).map((column) => column?.sessionId ?? "main");
    };

    it("opens a dropped thread left or right of a column and keeps it across a reload", () => {
      const store = useIdeThreadsStore.getState();
      store.openThread("s1", "p1");
      store.placeColumn({ sessionId: "s2", projectId: "p1" }, 1);
      store.placeColumn({ sessionId: "s3", projectId: "p1" }, 0);
      expect(ids()).toEqual(["s3", "main", "s2"]);
      expect(JSON.parse(localStorage.getItem("jarvis.agenticIde.threadSplit.v1") ?? "null")).toEqual({
        split: [{ sessionId: "s3", projectId: "p1" }, { sessionId: "s2", projectId: "p1" }], mainAt: 1,
      });
    });

    it("moves a thread that already has a column and ignores the main column's own thread", () => {
      const store = useIdeThreadsStore.getState();
      store.openThread("s1", "p1");
      store.placeColumn({ sessionId: "s2", projectId: "p1" }, 1);
      store.placeColumn({ sessionId: "s3", projectId: "p1" }, 2);
      store.placeColumn({ sessionId: "s3", projectId: "p1" }, 0);
      expect(ids()).toEqual(["s3", "main", "s2"]);
      store.placeColumn({ sessionId: "s1", projectId: "p1" }, 0);
      expect(ids()).toEqual(["s3", "main", "s2"]);
    });

    it("never opens more columns than fit; a full row replaces the column dropped on", () => {
      const store = useIdeThreadsStore.getState();
      store.openThread("s0", "p1");
      for (let index = 1; index < MAX_THREAD_COLUMNS + 2; index += 1) store.placeColumn({ sessionId: `s${index}`, projectId: "p1" }, index);
      expect(ids()).toHaveLength(MAX_THREAD_COLUMNS);
      store.placeColumn({ sessionId: "x", projectId: "p1" }, 1, true);
      expect(ids()).toEqual(["main", "x", "s2", "s3"]);
      // Dropped on the main column, it opens there.
      store.placeColumn({ sessionId: "y", projectId: "p1" }, 0, true);
      expect(useIdeThreadsStore.getState().selection.sessionId).toBe("y");
    });

    it("closes columns; a thread picked for the main column or archived leaves its side column", () => {
      const store = useIdeThreadsStore.getState();
      store.openThread("s1", "p1");
      store.placeColumn({ sessionId: "s2", projectId: "p1" }, 1);
      store.placeColumn({ sessionId: "s3", projectId: "p1" }, 2);
      store.placeColumn({ sessionId: "s4", projectId: "p1" }, 3);
      store.openThread("s2", "p1");
      expect(ids()).toEqual(["main", "s3", "s4"]);
      store.archiveThread("s4");
      expect(ids()).toEqual(["main", "s3"]);
      store.closeColumn("s3");
      expect(ids()).toEqual(["main"]);
    });

    it("closing the main column hands it to the thread next to it", () => {
      const store = useIdeThreadsStore.getState();
      store.openThread("s1", "p1");
      store.placeColumn({ sessionId: "s2", projectId: "p1" }, 0);
      store.placeColumn({ sessionId: "s3", projectId: "p2" }, 2);
      store.closeMainColumn();
      expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p2", sessionId: "s3" });
      expect(ids()).toEqual(["s2", "main"]);
      store.closeMainColumn();
      expect(useIdeThreadsStore.getState().selection.sessionId).toBe("s2");
      expect(ids()).toEqual(["main"]);
      store.closeMainColumn(); // nothing beside it: stays
      expect(useIdeThreadsStore.getState().selection.sessionId).toBe("s2");
    });
  });
});
