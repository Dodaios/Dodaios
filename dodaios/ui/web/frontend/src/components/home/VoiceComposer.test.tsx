import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceComposer } from "@/components/home/VoiceComposer";
import { EditContextMenu } from "@/components/EditContextMenu";
import { forgetHeldFiles } from "@/components/agentchat/useChatAttachments";
import { useHomeStore } from "@/store/home";
import { attachChatFilesIn } from "@/lib/agentChatApi";
import { fetchVoiceComposerSession, submitVoiceComposer } from "@/lib/voiceApi";

const call = { active: false, busy: false, connecting: false, toggleCall: vi.fn() };

vi.mock("@/components/agentic/useVoiceCall", () => ({ useVoiceCall: () => call }));
vi.mock("@/hooks/useVoiceReadiness", () => ({ useVoiceReadiness: () => ({ connected: true }) }));
vi.mock("@/hooks/useVoiceEngineDisplay", () => ({
  useVoiceEngineDisplay: () => ({ providerLabel: "OpenAI Realtime", model: "gpt-realtime" }),
}));
vi.mock("@/hooks/usePromptMode", () => ({
  usePromptMode: () => ({ enabled: null, busy: false, toggle: async () => {} }),
}));
vi.mock("@/lib/voiceApi", () => ({
  fetchVoiceComposerSession: vi.fn(),
  submitVoiceComposer: vi.fn(),
}));
vi.mock("@/lib/agentChatApi", async (load) => ({
  ...(await load<typeof import("@/lib/agentChatApi")>()),
  attachChatFilesIn: vi.fn(),
}));

afterEach(() => {
  cleanup();
  call.active = false;
  call.toggleCall.mockReset();
  vi.mocked(fetchVoiceComposerSession).mockReset();
  vi.mocked(submitVoiceComposer).mockReset();
  vi.mocked(attachChatFilesIn).mockReset();
  vi.unstubAllGlobals();
  forgetHeldFiles(useHomeStore);
});

describe("VoiceComposer", () => {
  it("offers Start while no call runs and says what to do", () => {
    render(<VoiceComposer hint="Press Start to talk" />);
    expect((screen.getByTestId("voice-input") as HTMLInputElement).placeholder).toBe("Press Start to talk");
    fireEvent.click(screen.getByTestId("voice-call-start"));
    expect(call.toggleCall).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("voice-call-stop")).toBeNull();
  });

  it("turns the control into Stop while a call is open", async () => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    render(<VoiceComposer hint="Speaking…" />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    fireEvent.click(screen.getByTestId("voice-call-stop"));
    expect(call.toggleCall).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("voice-call-start")).toBeNull();
  });

  it("shows the way back to typing only when the host has one", () => {
    render(<VoiceComposer hint="" />);
    expect(screen.queryByTestId("voice-mode-exit")).toBeNull();
    cleanup();
    const onExit = vi.fn();
    render(<VoiceComposer hint="" onExit={onExit} />);
    fireEvent.click(screen.getByTestId("voice-mode-exit"));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("names the voice engine under the card", () => {
    render(<VoiceComposer hint="" />);
    expect(screen.getByTestId("voice-engine").textContent).toContain("OpenAI Realtime");
  });

  it("keeps the active call open when the keyboard is clicked and submits Enter to that call", async () => {
    call.active = true;
    const onExit = vi.fn();
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(submitVoiceComposer).mockResolvedValue(undefined);
    render(<VoiceComposer hint="Listening" onExit={onExit} />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    fireEvent.click(screen.getByTestId("voice-mode-exit"));
    expect(document.activeElement).toBe(screen.getByTestId("voice-input"));
    expect(onExit).not.toHaveBeenCalled();
    expect(call.toggleCall).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("voice-input"), { target: { value: "Hello during the call" } });
    fireEvent.keyDown(screen.getByTestId("voice-input"), { key: "Enter" });
    await waitFor(() => expect(submitVoiceComposer).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitVoiceComposer).mock.calls[0].slice(0, 3)).toEqual([
      "live-call", "Hello during the call", [],
    ]);
    expect(screen.getByTestId("voice-call-stop")).toBeTruthy();
    expect(call.toggleCall).not.toHaveBeenCalled();
  });

  it.each([false, true])("sends text and multiple pasted attachments once after preview focus (shift=%s)", async (shiftKey) => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(submitVoiceComposer).mockImplementation(() => new Promise(() => {}));
    const receipts = ["one.png", "two.png"].map((name) => ({
      name, reference: name, kind: "image" as const,
      detail: "Test image", described_by: "vision" as const, note: "",
    }));
    vi.mocked(attachChatFilesIn).mockResolvedValue({ attachments: receipts, cwd: "C:/chat" });
    render(<VoiceComposer hint="Listening" />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    const input = screen.getByTestId("voice-input");
    fireEvent.change(input, { target: { value: "Compare these" } });
    const images = receipts.map(({ name }) => new File(["image"], name, { type: "image/png" }));
    fireEvent.paste(input, { clipboardData: {
      files: images,
      items: images.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"], getData: () => "",
    } });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-two.png")).toBeTruthy());
    fireEvent.click(screen.getByTestId("chat-attachment-one.png"));
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input, { key: "Enter", shiftKey });
    fireEvent.keyDown(input, { key: "Enter", shiftKey });
    await waitFor(() => expect(submitVoiceComposer).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitVoiceComposer).mock.calls[0].slice(0, 3))
      .toEqual(["live-call", "Compare these", receipts]);
    expect(call.toggleCall).not.toHaveBeenCalled();
    expect(screen.getByTestId("voice-call-stop")).toBeTruthy();
  });

  it("leaves attachment removal on its own control without sending", async () => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(attachChatFilesIn).mockResolvedValue({ attachments: [{
      name: "one.png", reference: "one.png", kind: "image", detail: "", described_by: "vision", note: "",
    }], cwd: "C:/chat" });
    render(<VoiceComposer hint="Listening" />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    const picker = screen.getByTestId("voice-composer").querySelector('input[type="file"]')!;
    fireEvent.change(picker, { target: { files: [new File(["image"], "one.png")] } });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-remove-one.png")).toBeTruthy());
    const remove = screen.getByTestId("chat-attachment-remove-one.png");
    remove.focus();
    fireEvent.keyDown(remove, { key: "Enter" });
    expect(submitVoiceComposer).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(remove);
    fireEvent.click(remove);
    expect(screen.queryByTestId("chat-attachment-one.png")).toBeNull();
    expect(document.activeElement).not.toBe(screen.getByTestId("voice-input"));
    expect(call.toggleCall).not.toHaveBeenCalled();
  });

  it("looks up the active call when Enter arrives before the status poll", async () => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession)
      .mockImplementationOnce(() => new Promise<string | null>(() => {}))
      .mockResolvedValueOnce("live-call");
    vi.mocked(submitVoiceComposer).mockResolvedValue(undefined);
    render(<VoiceComposer hint="Listening" />);
    fireEvent.change(screen.getByTestId("voice-input"), { target: { value: "Early question" } });
    fireEvent.keyDown(screen.getByTestId("voice-input"), { key: "Enter" });
    await waitFor(() => expect(submitVoiceComposer).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitVoiceComposer).mock.calls[0].slice(0, 2))
      .toEqual(["live-call", "Early question"]);
    expect(call.toggleCall).not.toHaveBeenCalled();
  });

  it("shows a picked attachment inside the original bar and submits its receipt", async () => {
    call.active = true;
    const onExit = vi.fn();
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(submitVoiceComposer).mockResolvedValue(undefined);
    const receipt = {
      name: "note.txt", reference: '".jarvis/drops/note.txt"', kind: "text" as const,
      detail: "The actual document text", described_by: "extraction" as const, note: "",
    };
    vi.mocked(attachChatFilesIn).mockResolvedValue({ attachments: [receipt], cwd: "C:/chat" });
    render(<VoiceComposer hint="Listening" onExit={onExit} />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    const bar = screen.getByTestId("voice-composer");
    const picker = bar.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(picker, { target: { files: [new File(["The actual document text"], "note.txt")] } });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-note.txt")).toBeTruthy());
    expect(bar.contains(screen.getByTestId("chat-attachment-note.txt"))).toBe(true);
    expect(vi.mocked(attachChatFilesIn).mock.calls[0][0].voiceSessionId).toBe("live-call");
    fireEvent.click(screen.getByTestId("chat-attachment-note.txt"));
    expect(document.activeElement).toBe(screen.getByTestId("voice-input"));
    fireEvent.change(screen.getByTestId("voice-input"), { target: { value: "Summarize it" } });
    fireEvent.keyDown(screen.getByTestId("voice-input"), { key: "Enter" });
    await waitFor(() => expect(submitVoiceComposer).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitVoiceComposer).mock.calls[0][2]).toEqual([receipt]);
    expect(onExit).not.toHaveBeenCalled();
    expect(call.toggleCall).not.toHaveBeenCalled();
    expect(screen.getAllByTestId("voice-composer")).toHaveLength(1);
    expect(document.querySelectorAll('[data-tour="voice-bar"]')).toHaveLength(1);
    expect(screen.queryByTestId("agent-composer")).toBeNull();
  });

  it("accepts a clipboard screenshot and dropped documents across the input surface", async () => {
    call.active = true;
    const onExit = vi.fn();
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(attachChatFilesIn)
      .mockResolvedValueOnce({ attachments: [{
        name: "shot.png", reference: '".jarvis/drops/shot.png"', kind: "image",
        detail: "Screenshot", described_by: "vision", note: "",
      }], cwd: "C:/chat" })
      .mockResolvedValueOnce({ attachments: [
        {
          name: "readme.txt", reference: '".jarvis/drops/readme.txt"', kind: "text",
          detail: "Document", described_by: "extraction", note: "",
        },
        {
          name: "diagram.svg", reference: '".jarvis/drops/diagram.svg"', kind: "text",
          detail: "Diagram", described_by: "extraction", note: "",
        },
      ], cwd: "C:/chat" });
    render(<VoiceComposer hint="Listening" onExit={onExit} />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    const screenshot = new File([new Uint8Array([1])], "shot.png", { type: "image/png" });
    const document = new File(["Document"], "readme.txt", { type: "text/plain" });
    const diagram = new File(["<svg />"], "diagram.svg", { type: "image/svg+xml" });
    const transfer = (...items: File[]) => ({
      files: items, items: items.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"], getData: () => "", dropEffect: "none",
    });
    fireEvent.paste(screen.getByTestId("voice-input"), { clipboardData: transfer(screenshot) });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy());
    const input = screen.getByTestId("voice-input");
    for (const clientX of [1, 150, 299]) {
      fireEvent.dragEnter(input, { clientX, dataTransfer: transfer(document, diagram) });
      expect(input.getAttribute("data-testid")).toBe("voice-input");
    }
    fireEvent.drop(input, { clientX: 299, dataTransfer: transfer(document, diagram) });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-readme.txt")).toBeTruthy());
    expect(screen.getByTestId("chat-attachment-diagram.svg")).toBeTruthy();
    expect(vi.mocked(attachChatFilesIn).mock.calls).toHaveLength(2);
    expect(vi.mocked(attachChatFilesIn).mock.calls.every(([target]) =>
      target.voiceSessionId === "live-call")).toBe(true);
    fireEvent.keyDown(screen.getByTestId("voice-input"), { key: "Enter" });
    await waitFor(() => expect(submitVoiceComposer).toHaveBeenCalledTimes(1));
    expect(vi.mocked(submitVoiceComposer).mock.calls[0][1]).toBe("");
    expect(vi.mocked(submitVoiceComposer).mock.calls[0][2].map((item) => item.name))
      .toEqual(["shot.png", "readme.txt", "diagram.svg"]);
    expect(onExit).not.toHaveBeenCalled();
    expect(call.toggleCall).not.toHaveBeenCalled();
    expect(screen.queryByTestId("composer-drop-overlay")).toBeNull();
    expect(screen.getByTestId("voice-call-stop")).toBeTruthy();
  });

  it("keeps the keyboard, paperclip and call controls outside the file drop surface", async () => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    render(<VoiceComposer hint="Listening" onExit={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));
    const file = new File(["Document"], "readme.txt", { type: "text/plain" });
    const dataTransfer = {
      files: [file], items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"], getData: () => "", dropEffect: "none",
    };

    fireEvent.drop(screen.getByTestId("voice-mode-exit"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("voice-attach"), { dataTransfer });
    fireEvent.drop(screen.getByTestId("voice-call-stop"), { dataTransfer });

    expect(attachChatFilesIn).not.toHaveBeenCalled();
    expect(call.toggleCall).not.toHaveBeenCalled();
  });

  it("routes right-click Paste of Explorer files into the existing attachment pipeline", async () => {
    call.active = true;
    vi.mocked(fetchVoiceComposerSession).mockResolvedValue("live-call");
    vi.mocked(attachChatFilesIn).mockResolvedValue({ attachments: [{
      name: "photo.png", reference: '".jarvis/drops/photo.png"', kind: "image",
      detail: "Photo", described_by: "vision", note: "",
    }], cwd: "C:/chat" });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      json: async () => String(url).endsWith("/api/clipboard/files")
        ? { paths: ["C:/pictures/photo.png"] }
        : { text: "" },
    })));
    render(<><VoiceComposer hint="Listening" onExit={() => {}} /><EditContextMenu /></>);
    await waitFor(() => expect(screen.getByTestId("voice-attach").hasAttribute("disabled")).toBe(false));

    fireEvent.contextMenu(screen.getByTestId("voice-input"), { clientX: 40, clientY: 20 });
    fireEvent.click(screen.getByRole("menuitem", { name: /Paste/i }));

    await waitFor(() => expect(screen.getByTestId("chat-attachment-photo.png")).toBeTruthy());
    expect(document.activeElement).toBe(screen.getByTestId("voice-input"));
    expect(vi.mocked(attachChatFilesIn).mock.calls[0][0]).toMatchObject({
      paths: ["C:/pictures/photo.png"], files: [], voiceSessionId: "live-call",
    });
  });
});
