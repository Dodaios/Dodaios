import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { typedNodeCard } from "../testCards";
import { GenericSpecEditor } from "./GenericSpecEditor";
import { barItem, leave, renderEditor } from "./testBar";

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
    const { guard } = renderEditor(
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
    expect((barItem("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: '{"markdown": "# B"}' } });
    expect((barItem("node-editor-undo") as HTMLButtonElement).disabled).toBe(false);
    // Closing the node saves first, then lets it close.
    const closed = vi.fn();
    leave(guard, closed);
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(puts).toEqual([{ markdown: "# B" }]);
    fireEvent.click(barItem("node-editor-undo"));
    expect(JSON.parse(field.value)).toEqual({ markdown: "# A" });
  });
});
