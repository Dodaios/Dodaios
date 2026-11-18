import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { NODE_TYPES } from "../nodeModel";
import { NodeSkeleton } from "./NodeSkeleton";

afterEach(cleanup);

it("draws a quiet outline for every node type", () => {
  for (const type of NODE_TYPES) {
    render(<NodeSkeleton type={type} />);
    const skeleton = screen.getByTestId("node-skeleton");
    expect(skeleton.getAttribute("data-type")).toBe(type);
    expect(skeleton.className).toContain("live-skeleton");
    cleanup();
  }
});
