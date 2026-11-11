import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

vi.mock("@/hooks/useCanvasAwake", () => ({ useCanvasAwake: () => false }));

import { ShaderPetPreview } from "./ShaderPetPreview";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("the shader backdrop disc is centered on the preview box", () => {
  vi.stubGlobal("fetch", () => new Promise(() => {}));
  render(<ShaderPetPreview url="/shader.frag" state="idle" reduced={false} backdrop={0.4} />);
  const disc = screen.getByTestId("shader-backdrop-disc");
  expect(disc.style.transform).toBe("translate(-50%, -50%) scale(0.939)");
  expect(disc.className).toContain("left-1/2");
  expect(disc.className).toContain("top-1/2");
});
