import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentBriefsGroup } from "./AgentBriefsGroup";

const DEFAULT_STATE = {
  wishes: "",
  is_custom: false,
  default: "A change ends shipped.",
  limits: "Keep the real limits.",
  char_count: 0,
  max_chars: 2000,
};

const WISHES = "I want to approve every PR myself\nAlways with tests";

const CUSTOM_STATE = { ...DEFAULT_STATE, wishes: WISHES, is_custom: true, char_count: WISHES.length };

afterEach(() => vi.restoreAllMocks());

function serve(byMethod: Record<string, unknown>) {
  const fetchMock = vi.fn(async (_url: string, opts?: RequestInit) => ({
    ok: true,
    json: async () => byMethod[opts?.method ?? "GET"] ?? DEFAULT_STATE,
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("AgentBriefsGroup", () => {
  it("explains the default and the limits that always stay", async () => {
    serve({ GET: DEFAULT_STATE });
    render(<AgentBriefsGroup />);

    expect(screen.getByText("Agent briefs")).toBeTruthy();
    expect(screen.getByText(/push and merge it themselves/)).toBeTruthy();
    expect(screen.getByText(/no payments/)).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("agent-briefs-badge").textContent).toBe("Default"));
  });

  it("loads the stored wishes and marks them as the person's own", async () => {
    serve({ GET: CUSTOM_STATE });
    render(<AgentBriefsGroup />);

    await waitFor(() => {
      const editor = screen.getByTestId("agent-briefs-editor") as HTMLTextAreaElement;
      expect(editor.value).toBe(WISHES);
    });
    expect(screen.getByTestId("agent-briefs-badge").textContent).toBe("Your wishes");
  });

  it("PUTs the whole list when Save is clicked", async () => {
    const fetchMock = serve({ GET: DEFAULT_STATE, PUT: { ...CUSTOM_STATE, ok: true } });
    render(<AgentBriefsGroup />);

    const editor = await waitFor(() => screen.getByTestId("agent-briefs-editor") as HTMLTextAreaElement);
    const save = screen.getByText("Save wishes").closest("button")!;
    await waitFor(() => {
      fireEvent.change(editor, { target: { value: WISHES } });
      expect(save.hasAttribute("disabled")).toBe(false);
    });
    fireEvent.click(save);

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, opts]) => opts?.method === "PUT");
      expect(put?.[0]).toBe("/api/settings/agent-briefs");
      expect(JSON.parse(put?.[1]?.body as string)).toEqual({ wishes: WISHES });
    });
  });

  it("goes back to the default with one click", async () => {
    const fetchMock = serve({ GET: CUSTOM_STATE, DELETE: { ...DEFAULT_STATE, ok: true, removed: true } });
    render(<AgentBriefsGroup />);

    const reset = await waitFor(() => {
      const button = screen.getByText("Back to default").closest("button")!;
      expect(button.hasAttribute("disabled")).toBe(false);
      return button;
    });
    fireEvent.click(reset);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, opts]) => opts?.method === "DELETE")).toBe(true);
      expect(screen.getByTestId("agent-briefs-badge").textContent).toBe("Default");
    });
  });
});
