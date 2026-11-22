import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomCliDialog, runsThroughShell } from "./CustomCliDialog";

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => key,
  useLocaleChunk: () => true,
}));

vi.mock("@/lib/workspaceClisApi", () => ({
  fetchCustomClis: vi.fn(),
  createCustomCli: vi.fn(),
  updateCustomCli: vi.fn(),
  deleteCustomCli: vi.fn(),
  uploadCustomCliLogo: vi.fn(),
  removeCustomCliLogo: vi.fn(),
}));

import * as api from "@/lib/workspaceClisApi";

/** No jest-dom in this repo — assertions read the elements directly. */
function field(testId: string): HTMLInputElement {
  return screen.getByTestId(testId) as HTMLInputElement;
}

function text(testId: string): string {
  return screen.getByTestId(testId).textContent ?? "";
}

const STORED: api.CustomCli = {
  id: "helix",
  display_name: "Helix",
  command: "helix",
  description: "A user-added terminal CLI.",
  file_reference: "quoted",
  headless_command: "",
  headless_resume: "",
  logo_url: "",
  runs_through_shell: false,
  binary: "helix",
};

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  // jsdom ships no object-URL implementation, and the logo preview asks for
  // one the moment a file is picked.
  Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:preview"),
    revokeObjectURL: vi.fn(),
  });
});

describe("recognising shell source", () => {
  // Mirrors custom_clis.needs_shell — the two must agree, because the backend's
  // answer decides how the pane starts and this one decides what the user was
  // told would happen.
  it.each([
    ["agy", false],
    ["npx -y some-cli", false],
    ["agy | tee log.txt", true],
    ["agy && echo done", true],
    ["FOO=1 agy", true],
    ["agy --model $MODEL", true],
  ])("%s", (command, expected) => {
    expect(runsThroughShell(command)).toBe(expected);
  });
});

describe("CustomCliDialog", () => {
  it("cannot be saved without both a name and a command", () => {
    render(
      <CustomCliDialog open onOpenChange={() => {}} onSaved={() => {}} />,
    );
    const save = screen.getByTestId("custom-cli-save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(field("custom-cli-name"), {
      target: { value: "Antigravity" },
    });
    expect(save.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy" },
    });
    expect(save.disabled).toBe(false);
  });

  it("warns while typing that a shell will wrap the command", () => {
    render(
      <CustomCliDialog open onOpenChange={() => {}} onSaved={() => {}} />,
    );
    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy" },
    });
    expect(screen.getByText("custom_cli.command_hint")).toBeTruthy();

    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy | tee log.txt" },
    });
    expect(screen.getByText("custom_cli.command_shell_hint")).toBeTruthy();
  });

  it("creates the entry and reports it", async () => {
    vi.mocked(api.createCustomCli).mockResolvedValue(STORED);
    const onSaved = vi.fn();
    render(
      <CustomCliDialog open onOpenChange={() => {}} onSaved={onSaved} />,
    );

    fireEvent.change(screen.getByTestId("custom-cli-name"), {
      target: { value: "Antigravity" },
    });
    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy" },
    });
    fireEvent.click(screen.getByTestId("custom-cli-save"));

    await waitFor(() => expect(api.createCustomCli).toHaveBeenCalled());
    expect(api.createCustomCli).toHaveBeenCalledWith({
      display_name: "Antigravity",
      command: "agy",
      description: "",
      file_reference: "quoted",
      headless_command: "",
      headless_resume: "",
    });
    expect(onSaved).toHaveBeenCalledWith(STORED);
  });

  it("sends the headless command so the CLI can run in threads", async () => {
    vi.mocked(api.createCustomCli).mockResolvedValue(STORED);
    render(<CustomCliDialog open onOpenChange={() => {}} editing={null} onSaved={() => {}} />);
    fireEvent.change(screen.getByTestId("custom-cli-name"), { target: { value: "Helix" } });
    fireEvent.change(screen.getByTestId("custom-cli-command"), { target: { value: "helix" } });
    fireEvent.change(screen.getByTestId("custom-cli-headless"), {
      target: { value: "helix -p {prompt}" },
    });
    fireEvent.click(screen.getByTestId("custom-cli-save"));
    await waitFor(() => expect(api.createCustomCli).toHaveBeenCalled());
    expect(vi.mocked(api.createCustomCli).mock.calls.at(-1)?.[0]).toMatchObject({
      headless_command: "helix -p {prompt}",
    });
  });

  it("shows the server's own complaint instead of a status code", async () => {
    vi.mocked(api.createCustomCli).mockRejectedValue(
      new Error("Give the command that starts this CLI."),
    );
    render(
      <CustomCliDialog open onOpenChange={() => {}} onSaved={() => {}} />,
    );
    fireEvent.change(screen.getByTestId("custom-cli-name"), {
      target: { value: "Antigravity" },
    });
    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy" },
    });
    fireEvent.click(screen.getByTestId("custom-cli-save"));

    await waitFor(() =>
      expect(text("custom-cli-error")).toContain(
        "Give the command that starts this CLI.",
      ),
    );
  });

  it("uploads a picked logo after the entry exists", async () => {
    // The id the file is named after is assigned on creation, so a logo cannot
    // be stored before the entry it belongs to.
    vi.mocked(api.createCustomCli).mockResolvedValue(STORED);
    vi.mocked(api.uploadCustomCliLogo).mockResolvedValue({
      ...STORED,
      logo_url: "/api/workspace-clis/helix/logo",
    });
    render(
      <CustomCliDialog open onOpenChange={() => {}} onSaved={() => {}} />,
    );

    fireEvent.change(screen.getByTestId("custom-cli-name"), {
      target: { value: "Antigravity" },
    });
    fireEvent.change(screen.getByTestId("custom-cli-command"), {
      target: { value: "agy" },
    });
    const file = new File(["<svg />"], "mark.svg", { type: "image/svg+xml" });
    fireEvent.change(screen.getByTestId("custom-cli-logo-input"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("custom-cli-save"));

    await waitFor(() => expect(api.uploadCustomCliLogo).toHaveBeenCalled());
    expect(api.uploadCustomCliLogo).toHaveBeenCalledWith("helix", file);
  });

  it("fills its fields from the entry being edited", () => {
    render(
      <CustomCliDialog
        open
        onOpenChange={() => {}}
        editing={{ ...STORED, file_reference: "at" }}
        onSaved={() => {}}
      />,
    );
    expect(field("custom-cli-name").value).toBe("Helix");
    expect(field("custom-cli-command").value).toBe("helix");
    expect(screen.getByTestId("custom-cli-at-reference").getAttribute("aria-checked")).toBe("true");
  });
});
