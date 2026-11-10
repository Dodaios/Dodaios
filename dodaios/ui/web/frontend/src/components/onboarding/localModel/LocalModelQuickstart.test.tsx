import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import type { QuickstartPlan, RunQuickstartOptions } from "./localQuickstart";

const PLAN = {
  model: "qwen3.5",
  label: "Qwen 3.5 9B",
  size_gb: 6.6,
  reason: "",
  hardware: { summary: "This computer: 16 GB graphics memory, 32 GB RAM." },
} as unknown as QuickstartPlan;

let behaviour: (opts: RunQuickstartOptions) => Promise<QuickstartPlan | null>;

vi.mock("./localQuickstart", async (importOriginal) => {
  const real = await importOriginal<typeof import("./localQuickstart")>();
  return { ...real, runLocalQuickstart: (opts: RunQuickstartOptions) => behaviour(opts) };
});

const { LocalModelQuickstart } = await import("./LocalModelQuickstart");
const { QuickstartError } = await import("./localQuickstart");

beforeAll(async () => {
  await loadLocaleChunk("onboarding");
});

afterEach(cleanup);

describe("LocalModelQuickstart", () => {
  it("shows the download with a bar, then says the model is ready", async () => {
    let finish: () => void = () => {};
    behaviour = (opts) =>
      new Promise((resolve) => {
        opts.report({ phase: "downloading", plan: PLAN, percent: 42 });
        finish = () => {
          opts.report({ phase: "done", plan: PLAN, probeFailed: false });
          resolve(PLAN);
        };
      });
    const onReady = vi.fn();
    render(<LocalModelQuickstart onReady={onReady} />);
    fireEvent.click(await screen.findByTestId("local-model-quickstart-run"));
    const line = await screen.findByTestId("local-model-quickstart-line");
    expect(line.textContent).toContain("Qwen 3.5 9B");
    expect(line.textContent).toContain("6.6 GB");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("42");
    finish();
    await screen.findByTestId("local-model-ready");
    expect(onReady).toHaveBeenCalledWith(PLAN);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("says why it failed and offers to try again", async () => {
    behaviour = async () => {
      throw new QuickstartError("download", "connection reset");
    };
    render(<LocalModelQuickstart />);
    fireEvent.click(await screen.findByTestId("local-model-quickstart-run"));
    await waitFor(() =>
      expect(screen.getByTestId("local-model-quickstart").getAttribute("data-phase")).toBe("error"),
    );
    expect(screen.getByTestId("local-model-quickstart-line").textContent).toContain("connection reset");
    expect(screen.getByTestId("local-model-quickstart-run").textContent).toBe("Try again");
  });
});
