import { act, cleanup, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, fill: (s: string) => s }));
vi.mock("@/hooks/useTheme", () => ({ useThemeValue: () => "dark" }));

import type { NodeSpecEditor, RemoteRevision } from "../editors/useNodeSpecEditor";
import { LiveBuildLayer } from "./LiveBuildLayer";
import { parseNodeChange } from "./liveChanges";
import { useNodeLive } from "./liveStore";

const REF = "20261118T100000__node__abc123def456::tasks/node/artifacts/files/notes.html";

function change(over: Record<string, unknown>) {
  const parsed = parseNodeChange({
    node_id: "abc123def456", ref: REF, slug: REF.split("::")[0], node_type: "docs", title: "Notes",
    version: 1, previous_version: 0, updated_at: 1, action: "create", rewrite: false, ops: [],
    author_kind: "assistant", author_name: "Ada", author_id: "agent:ada", session_id: "chat-1", step: "",
    ...over,
  });
  act(() => useNodeLive.getState().receive(parsed!));
}

function Harness({ lines, remote }: { lines: string[]; remote: RemoteRevision<unknown> | null }) {
  const body = useRef<HTMLDivElement>(null);
  const editor = { nodeId: "abc123def456", spec: {}, remote } as unknown as NodeSpecEditor<unknown>;
  return (
    <div>
      <div ref={body} data-testid="body">
        {lines.map((line) => <p key={line}>{line}</p>)}
      </div>
      <LiveBuildLayer editor={editor} body={body} />
    </div>
  );
}

const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);

beforeEach(() => {
  (Element.prototype as unknown as { animate: typeof animate }).animate = animate;
  animate.mockClear();
});

afterEach(() => {
  cleanup();
  delete (Element.prototype as unknown as { animate?: unknown }).animate;
  useNodeLive.setState({ nodes: {}, refs: {}, autoOpened: {}, suppressed: {} });
});

it("shows the agent's presence with its name while it builds", () => {
  change({});
  render(<Harness lines={["One"]} remote={null} />);
  const presence = screen.getByTestId("live-presence");
  expect(presence.getAttribute("data-visible")).toBe("true");
  expect(screen.getByTestId("live-presence-name").textContent).toBe("Ada");
});

it("shows no presence for the person's own saves", () => {
  change({ action: "save", author_kind: "person", author_name: "", author_id: "person", rewrite: true });
  render(<Harness lines={["One"]} remote={null} />);
  expect(screen.queryByTestId("live-presence")).toBeNull();
});

it("plays what an agent's revision added, and leaves the rest as it was", () => {
  change({});
  const { rerender } = render(<Harness lines={["One"]} remote={null} />);
  animate.mockClear();
  // The push arrives first; the editor takes the revision and draws it next.
  change({ action: "update", version: 2, previous_version: 1, ops: [{ op: "append", path: "/blocks", value: "Two" }] });
  rerender(<Harness lines={["One", "Two"]} remote={{ seq: 1, previous: {}, next: {}, fromVersion: 1, version: 2 }} />);
  const added = screen.getByText("Two");
  const animated = (animate.mock.contexts as unknown[]).filter((el) => el === added);
  // Held hidden, then faded in: the new line only.
  expect(animated.length).toBeGreaterThan(0);
  expect((animate.mock.contexts as unknown[]).includes(screen.getByText("One"))).toBe(false);
});
