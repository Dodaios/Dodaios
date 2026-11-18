import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { EditorShell } from "./EditorShell";
import { LeaveGuardContext, createLeaveGuard, type LeaveGuard } from "./leaveGuard";
import { useNodeSpecEditor } from "./useNodeSpecEditor";

interface Spec {
  title: string;
}

type Reply = { status: number; body: Record<string, unknown> };

function installFetch(reply: (body: { spec: Spec; base_version: number }) => Reply) {
  const puts: Spec[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { spec: Spec; base_version: number };
      puts.push(body.spec);
      const answer = reply(body);
      return { ok: answer.status < 300, status: answer.status, json: async () => answer.body };
    }),
  );
  return puts;
}

const ok = (body: { spec: Spec; base_version: number }): Reply => ({
  status: 200,
  body: { version: body.base_version + 1, updated_at: 200 + body.base_version, spec: body.spec },
});

function Harness({ onDone, side = false, guard = null }: { onDone: () => void; side?: boolean; guard?: LeaveGuard | null }) {
  const editor = useNodeSpecEditor<Spec>("n1", { spec: { title: "Plan" }, version: 1, updated_at: 100 }, { saveDelayMs: 10_000 });
  return (
    <LeaveGuardContext.Provider value={guard}>
    <EditorShell
      editor={editor}
      title="Plan"
      onDone={onDone}
      toolbar={<button type="button">Bold</button>}
      side={side ? <p>Inspector body</p> : undefined}
    >
      <button type="button" data-testid="rename" onClick={() => editor.apply((d) => void (d.title = `${d.title}!`), { label: "Rename" })}>
        {editor.spec.title}
      </button>
      <input data-testid="field" defaultValue="" />
    </EditorShell>
    </LeaveGuardContext.Provider>
  );
}

/** Undo and redo live in the bar's "⋯": open it, and find the item. */
function menuItem(testId: string): HTMLButtonElement {
  if (!screen.queryByTestId(testId)) fireEvent.click(screen.getByTestId("node-editor-more"));
  return screen.getByTestId(testId) as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("EditorShell", () => {
  it("frames the editor with its bar at the bottom, the body and an optional inspector, and no Done", () => {
    installFetch(ok);
    render(<Harness onDone={() => {}} side />);
    expect(screen.getByRole("region", { name: /Plan/ })).toBeTruthy();
    const bar = screen.getByRole("toolbar");
    expect(bar.getAttribute("data-testid")).toBe("node-bar");
    expect(bar.contains(screen.getByText("Bold"))).toBe(true);
    expect(screen.getByText("Inspector body").closest("aside")).toBeTruthy();
    expect(screen.queryByTestId("node-editor-done")).toBeNull();
  });

  it("undoes and redoes from the bar's menu, naming the step", () => {
    installFetch(ok);
    render(<Harness onDone={() => {}} />);
    expect(menuItem("node-editor-undo").disabled).toBe(true);
    // The menu closes again on a press outside it.
    fireEvent.pointerDown(document.body);
    fireEvent.click(screen.getByTestId("rename"));
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
    const undo = menuItem("node-editor-undo");
    expect(undo.disabled).toBe(false);
    expect(undo.textContent).toContain("Rename");
    expect(screen.getByTestId("node-editor-save-state").textContent).toMatch(/Unsaved/);
    fireEvent.click(undo);
    expect(screen.getByTestId("rename").textContent).toBe("Plan");
    const redo = menuItem("node-editor-redo");
    expect(redo.disabled).toBe(false);
    fireEvent.click(redo);
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
  });

  it("takes the undo keys only inside the editor and not in a text field", () => {
    installFetch(ok);
    render(<Harness onDone={() => {}} />);
    fireEvent.click(screen.getByTestId("rename"));
    // In a text field: the field's own undo.
    fireEvent.keyDown(screen.getByTestId("field"), { key: "z", metaKey: true });
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
    // Outside the editor: nothing.
    fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
    // On a control of the editor: the spec's undo, then redo.
    fireEvent.keyDown(screen.getByTestId("rename"), { key: "z", metaKey: true });
    expect(screen.getByTestId("rename").textContent).toBe("Plan");
    fireEvent.keyDown(screen.getByTestId("rename"), { key: "y", ctrlKey: true });
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
  });

  it("saves before the node closes, and then lets it close", async () => {
    const puts = installFetch(ok);
    const guard = createLeaveGuard();
    const closed = vi.fn();
    render(<Harness onDone={() => {}} guard={guard} />);
    fireEvent.click(screen.getByTestId("rename"));
    act(() => guard.leave(closed));
    await waitFor(() => expect(closed).toHaveBeenCalledTimes(1));
    expect(puts).toEqual([{ title: "Plan!" }]);
  });

  it("does not drop unsaved work silently when the save fails as the node closes", async () => {
    installFetch(() => ({ status: 422, body: { detail: "A title is too long." } }));
    const guard = createLeaveGuard();
    const closed = vi.fn();
    render(<Harness onDone={() => {}} guard={guard} />);
    fireEvent.click(screen.getByTestId("rename"));
    act(() => guard.leave(closed));
    await screen.findByTestId("node-editor-unsaved");
    expect(closed).not.toHaveBeenCalled();
    expect(screen.getByTestId("node-editor-save-state").textContent).toContain("A title is too long.");
    fireEvent.click(screen.getByTestId("node-editor-leave-anyway"));
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it("shows a conflict and resolves it either way", async () => {
    let version = 1;
    installFetch((body) => {
      if (body.base_version !== version) return ok(body);
      version = 5;
      return { status: 409, body: { detail: "changed", version: 5, updated_at: 900, spec: { title: "Theirs" } } };
    });
    const guard = createLeaveGuard();
    render(<Harness onDone={() => {}} guard={guard} />);
    fireEvent.click(screen.getByTestId("rename"));
    act(() => guard.leave(() => {}));
    await screen.findByTestId("node-editor-conflict");
    expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("conflict");
    fireEvent.click(screen.getByTestId("node-editor-take-theirs"));
    expect(screen.getByTestId("rename").textContent).toBe("Theirs");
    expect(screen.queryByTestId("node-editor-conflict")).toBeNull();
    // Mine is one undo away.
    fireEvent.click(menuItem("node-editor-undo"));
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
  });

  it("keeps mine from the conflict bar by saving over theirs", async () => {
    const seen: number[] = [];
    installFetch((body) => {
      seen.push(body.base_version);
      if (body.base_version === 1) return { status: 409, body: { detail: "changed", version: 3, updated_at: 900, spec: { title: "Theirs" } } };
      return ok(body);
    });
    const guard = createLeaveGuard();
    render(<Harness onDone={() => {}} guard={guard} />);
    fireEvent.click(screen.getByTestId("rename"));
    act(() => guard.leave(() => {}));
    await screen.findByTestId("node-editor-conflict");
    fireEvent.click(screen.getByTestId("node-editor-keep-mine"));
    await waitFor(() => expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("saved"));
    expect(seen).toEqual([1, 3]);
    expect(screen.getByTestId("rename").textContent).toBe("Plan!");
  });
});
