import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { typedNodeCard } from "../testCards";
import { GenericSpecEditor } from "./GenericSpecEditor";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GenericSpecEditor", () => {
  it("edits the spec as JSON, applies only valid text, and undoes it", async () => {
    const puts: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body)) as { spec: unknown };
        puts.push(body.spec);
        return { ok: true, status: 200, json: async () => ({ version: 2, updated_at: 2, spec: body.spec }) };
      }),
    );
    const onDone = vi.fn();
    render(
      <GenericSpecEditor
        node={typedNodeCard("g1", { title: "Plan" })}
        initial={{ spec: { markdown: "# A" }, version: 1, updated_at: 1 }}
        onDone={onDone}
      />,
    );
    const field = screen.getByLabelText("The node's content as JSON") as HTMLTextAreaElement;
    expect(JSON.parse(field.value)).toEqual({ markdown: "# A" });
    fireEvent.change(field, { target: { value: '{"markdown": "# B"' } });
    expect(screen.getByRole("status").textContent).toContain("not valid JSON");
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: '{"markdown": "# B"}' } });
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByTestId("node-editor-done"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(puts).toEqual([{ markdown: "# B" }]);
    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(JSON.parse(field.value)).toEqual({ markdown: "# A" });
  });
});
