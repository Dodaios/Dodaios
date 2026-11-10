import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalModesGroup } from "./ApprovalModesGroup";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockApi() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  let modes = { app_mode: "bypass", agent_mode: "bypass" };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, method, body });
    if (url === "/api/settings/approval-modes" && method === "PUT") modes = { ...modes, ...body };
    if (url === "/api/society/approval-mode") {
      return new Response(JSON.stringify({ mode: body.mode, changed: ["a", "b"], skipped: [{ agent_id: "c" }] }));
    }
    return new Response(JSON.stringify(modes));
  });
  return calls;
}

describe("the permission modes settings", () => {
  it("shows both modes and saves a new app mode", async () => {
    const calls = mockApi();
    render(<ApprovalModesGroup />);
    await waitFor(() => expect(screen.getByTestId("approvals-app-mode")).toBeTruthy());
    const app = screen.getByRole("radiogroup", { name: "App actions" });
    await act(async () => { fireEvent.click(app.querySelector("[role=radio]:nth-child(2)") as HTMLElement); });
    expect(calls.at(-1)).toEqual({ url: "/api/settings/approval-modes", method: "PUT", body: { app_mode: "ask" } });
  });

  it("applies the agent mode to every agent and says how many kept theirs", async () => {
    const calls = mockApi();
    render(<ApprovalModesGroup />);
    await waitFor(() => expect(screen.getByTestId("approvals-apply-all")).toBeTruthy());
    const agents = screen.getByRole("radiogroup", { name: "New agents" });
    await act(async () => { fireEvent.click(agents.querySelector("[role=radio]:nth-child(3)") as HTMLElement); });
    await act(async () => { fireEvent.click(screen.getByTestId("approvals-apply-all")); });
    expect(calls.at(-1)).toEqual({ url: "/api/society/approval-mode", method: "PUT", body: { mode: "always_ask" } });
    expect(screen.getByText("Applied to 2 agents.")).toBeTruthy();
    expect(screen.getByText(/1 agents kept their mode/)).toBeTruthy();
  });
});
