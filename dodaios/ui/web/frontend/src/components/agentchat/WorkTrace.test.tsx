import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { groupTrace, groupActivityTrace, livePetState, splitConversationTurn, WorkTrace, traceDuration } from "./WorkTrace";
import { traceToolIdentity } from "./traceActivity";
import { failureReason } from "./traceEntries";
import type { TextBlock, ToolBlock, TurnBlock, TurnStatus } from "./reduce";

const tool = (id: string, over: Partial<ToolBlock> = {}): ToolBlock => ({
  kind: "tool", callId: id, name: "read_file", input: { path: `${id}.ts` }, output: `Contents of ${id}`,
  isError: false, durationMs: 800, approval: null, startedMs: 1000, ...over,
});
const thought: TurnBlock = { kind: "reasoning", id: "reason", text: "**Check** the input.", live: false, durationMs: 8000, startedMs: 1000 };
const reply = (id: string, text: string): TextBlock => ({ kind: "text", id, text });
const props = { startedMs: 1000, durationMs: 12000, status: "done" as TurnStatus };
/** Finished rows are drawn by the classic look; the rail writes a report. */
const rows = { ...props, look: "classic" as const };
afterEach(() => { cleanup(); vi.useRealTimers(); });

/** A finished, answered turn folds its work behind "Thought for …"; open every fold. */
const openWork = () => {
  for (const toggle of Array.from(document.querySelectorAll<HTMLElement>("[data-testid='conversation-work-fold'][data-open='false'] > button"))) fireEvent.click(toggle);
};

describe("work trace", () => {
  it("summarizes integrations and mutations in first-use order with original logos", () => {
    const blocks = [tool("linear", {name:"mcp__codex_apps__linear_list_issues"}), tool("edit", {name:"apply_patch"}), tool("shell", {name:"exec_command"}), tool("again", {name:"linear/get_issue"})];
    const {container} = render(<WorkTrace {...rows} blocks={blocks} />);
    const summary = screen.getByRole("button", {name:"Used Linear Edited files Ran commands"});
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    expect(summary.querySelector("img, [data-logo]")).toBeTruthy();
    expect(container.querySelector("[data-trace-tool]")).toBeNull();
    fireEvent.click(summary);
    expect(container.querySelectorAll("[data-trace-tool]")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button",{name:/Linear · list issues/}));
    expect(screen.getByText("mcp__codex_apps__linear_list_issues")).toBeTruthy();
    expect(screen.getByText("Contents of linear")).toBeTruthy();
  });

  it("never folds failures, approvals, unfinished tools or replies into a successful summary", () => {
    const barriers: TurnBlock[] = [tool("fail",{isError:true}), tool("pending",{output:null}), tool("approval",{approval:{approvalId:"ap",summary:"Confirm",decision:null}}), {kind:"text",id:"reply",text:"Update"}];
    for (const barrier of barriers) {
      const groups = groupActivityTrace([tool("a",{name:"linear/get_issue"}),tool("b",{name:"exec_command"}),barrier,tool("c")]);
      expect(groups).toHaveLength(3);
      expect(groups[1].blocks).toEqual([barrier]);
    }
  });

  it("keeps live mixed activity open, then folds it at completion", () => {
    const blocks = [tool("a",{name:"linear/get_issue"}),tool("b",{name:"exec_command"})];
    const {rerender} = render(<WorkTrace {...rows} status="running" blocks={blocks} />);
    expect(screen.getByRole("button",{name:"Using Linear Running commands"}).getAttribute("aria-expanded")).toBe("true");
    rerender(<WorkTrace {...rows} blocks={blocks} />);
    expect(screen.getByRole("button",{name:"Used Linear Ran commands"}).getAttribute("aria-expanded")).toBe("false");
  });

  it("does not infer a plugin from arbitrary input text or substring names", () => {
    expect(traceToolIdentity(tool("shell",{name:"run_shell",input:{command:"echo linear"}})).integration).toBe(false);
    expect(traceToolIdentity(tool("math",{name:"nonlinear_solver"})).identity.logo).toBeUndefined();
    const unknown = traceToolIdentity(tool("other",{name:"mcp__custom_server__lookup"}));
    expect(unknown.integration).toBe(true);
    expect(unknown.service).toBe("Custom Server");
    expect(unknown.identity.logo).toBeUndefined();
  });

  it("preserves reasoning, call, next step and final answer order", () => {
    const blocks = [thought, tool("a"), { kind: "text" as const, id: "next", text: "Next, check the tests." }, tool("b"), { kind: "text" as const, id: "final", text: "Everything is ready." }];
    render(<WorkTrace {...props} blocks={blocks} />);
    openWork();
    const text = screen.getByTestId("work-trace").textContent!;
    expect(text.indexOf("Check the input")).toBeLessThan(text.indexOf("a.ts"));
    expect(text.indexOf("a.ts")).toBeLessThan(text.indexOf("Next, check"));
    expect(text.indexOf("Next, check")).toBeLessThan(text.indexOf("b.ts"));
    expect(text.indexOf("b.ts")).toBeLessThan(text.indexOf("Everything is ready"));
    expect(text.indexOf("Everything is ready")).toBeLessThan(text.indexOf("Done"));
  });

  it("groups fourteen successful reads and expands their full receipts", () => {
    const blocks = Array.from({length: 14}, (_, i) => tool(`file${i}`));
    render(<WorkTrace {...rows} blocks={blocks} />);
    const group = screen.getByRole("button", { name: "Read 14 files" });
    expect(group.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("file0.ts")).toBeNull();
    fireEvent.click(group);
    fireEvent.click(screen.getByRole("button", { name: /Read file file0.ts/ }));
    expect(screen.getByText('"path": "file0.ts"', { exact: false })).toBeTruthy();
    expect(screen.getByText("Contents of file0")).toBeTruthy();
    expect(screen.getByText("read_file")).toBeTruthy();
  });

  it("never groups across reasoning, errors, approvals, active calls or mutations", () => {
    const blocks: TurnBlock[] = [tool("a"), thought, tool("b"), tool("err", {isError:true}), tool("c"), tool("approve", {approval:{approvalId:"ap",summary:"Confirm",decision:null}}), tool("d"), tool("running", {output:null}), tool("e"), tool("write1", {name:"write_file"}), tool("write2", {name:"write_file"})];
    expect(groupTrace(blocks)).toHaveLength(blocks.length);
  });

  it("automatically collapses completed groups even after live interaction", () => {
    const blocks = [tool("a"), tool("b")];
    const { rerender } = render(<WorkTrace {...rows} status="running" blocks={blocks} />);
    const group = screen.getByRole("button", { name: "Read 2 files" });
    fireEvent.click(group); fireEvent.click(group);
    expect(group.getAttribute("aria-expanded")).toBe("true");
    rerender(<WorkTrace {...rows} blocks={blocks} />);
    expect(screen.getByRole("button", { name: "Read 2 files" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps errors and pending approval visible beside folded success", () => {
    render(<WorkTrace {...props} blocks={[tool("a"),tool("b"),tool("err",{isError:true,output:"Permission denied"}),tool("approval",{output:null,approval:{approvalId:"ap",summary:"Delete generated files?",decision:null}})]} onDecide={() => undefined} />);
    // Nothing folds: the approval stays actionable in place.
    expect(screen.getByText("Delete generated files?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    // One quiet line for the stretch; the failure opens with it.
    fireEvent.click(screen.getByRole("button", { name: /^Read files/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Read err\.ts.*Failed/ }));
    expect(screen.getAllByText("Failed: Permission denied").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
  });

  it.each(["allow", "allow_always", "deny"] as const)("submits %s exactly once and reports failures", async decision => {
    const calls: string[] = [];
    let reject!: (error: Error) => void;
    const onDecide = (id: string, value: string) => { calls.push(`${id}:${value}`); return new Promise<void>((_, fail) => { reject = fail; }); };
    render(<WorkTrace {...props} status="running" blocks={[tool("ap",{output:null,approval:{approvalId:"approval-id",summary:"Confirm this action",decision:null}})]} onDecide={onDecide} />);
    const name = {allow:"Approve",allow_always:"Always allow",deny:"Deny"}[decision];
    const button = screen.getByRole("button", {name});
    fireEvent.click(button); fireEvent.click(button);
    expect(calls).toEqual([`approval-id:${decision}`]);
    await act(async () => reject(new Error("Could not save decision")));
    expect(screen.getByRole("alert").textContent).toBe("Could not save decision");
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  });

  it("shows a denied action without a running indicator", () => {
    const {container} = render(<WorkTrace {...props} status="running" blocks={[tool("a",{output:null,approval:{approvalId:"ap",summary:"Delete?",decision:"deny"}})]} />);
    expect(screen.getByRole("button", { name: /^Read a\.ts.*Declined/ })).toBeTruthy();
    expect(container.querySelector('[data-trace-tool][data-state="running"]')).toBeNull();
    expect(screen.queryByRole("button", {name:"Approve"})).toBeNull();
  });

  it("renders edit input, a diff and output on demand", () => {
    render(<WorkTrace {...props} blocks={[tool("edit",{name:"Edit",input:{file_path:"app.ts",old_string:"oldValue",new_string:"newValue"},output:"File updated"})]} />);
    // The edit is one line with its size; the diff is one tap away.
    const edit = screen.getByRole("button", { name: /^Edited app\.ts \+1 −1/ });
    fireEvent.click(edit);
    expect(screen.getByLabelText("Changes").textContent).toContain("− oldValue");
    expect(screen.getByLabelText("Changes").textContent).toContain("+ newValue");
    expect(screen.getByText("File updated")).toBeTruthy();
  });

  it.each(["cancelled", "error"] as const)("does not leave tools spinning after %s", status => {
    const {container, rerender} = render(<WorkTrace {...rows} status={status} blocks={[tool("a",{output:null})]} />);
    expect(container.querySelector('[data-state="interrupted"]')).toBeTruthy();
    expect(container.querySelector('[data-trace-tool][data-state="running"]')).toBeNull();
    rerender(<WorkTrace {...props} status={status} blocks={[tool("a",{output:null})]} />);
    expect(screen.getByRole("button", { name: /^Read a\.ts.*Stopped/ })).toBeTruthy();
  });

  it("updates the live clock and releases timers at completion", () => {
    vi.useFakeTimers(); vi.setSystemTime(1000);
    const {rerender} = render(<WorkTrace {...props} durationMs={null} status="running" blocks={[]} />);
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status").textContent).toContain("3.0s");
    rerender(<WorkTrace {...props} blocks={[]} />);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not interpret tool output as HTML", () => {
    const {container} = render(<WorkTrace {...props} blocks={[tool("a",{name:"run_shell",input:{command:"<b>echo</b>"},output:'<img src=x onerror=alert(1)>'})]} />);
    // Neither the command line nor its printed output turns into markup.
    expect(container.querySelector('img, b')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^<b>echo<\/b>/ }));
    expect(container.querySelector('img, b')).toBeNull();
    expect(container.querySelector("[data-trace-output]")?.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("formats durations without a 60-second remainder", () => {
    expect(traceDuration(119999)).toBe("1m 59s");
    expect(traceDuration(-1)).toBe("0.0s");
  });

  it.each([1, 49, 99])("preserves a measured %i ms call instead of displaying zero", ms => {
    expect(traceDuration(ms)).toBe(`${ms}ms`);
  });

  it.each(["RunCommand", "RunShellCommand", "run_shell"])("shows the short duration beside a readable %s label", name => {
    const { rerender } = render(<WorkTrace {...rows} blocks={[tool("shell", { name, input: { command: "read skill instructions" }, durationMs: 49 })]} />);
    expect(screen.getByRole("button", { name: /Run command.*49ms/ })).toBeTruthy();
    expect(screen.queryByText("0.0s")).toBeNull();
    rerender(<WorkTrace {...props} blocks={[tool("shell", { name, input: { command: "read skill instructions" }, durationMs: 49 })]} />);
    // Codex keeps the line clean; the measured time is in the call's details.
    fireEvent.click(screen.getByRole("button", { name: /^read skill instructions/ }));
    expect(screen.getByText("Took 49ms")).toBeTruthy();
  });

  it("keeps the last reply visible and treats earlier text as foldable work", () => {
    const blocks = [tool("a"), reply("plan", "I will inspect the files."), tool("b"), reply("done", "Everything is ready.")];
    expect(splitConversationTurn(blocks)).toEqual({
      work: [tool("a"), reply("plan", "I will inspect the files."), tool("b")],
      answer: [reply("done", "Everything is ready.")],
      after: [],
    });
  });

  it("keeps failures after the last reply in view", () => {
    const failed = tool("err", { isError: true, output: "Upload failed" });
    expect(splitConversationTurn([tool("a"), reply("done", "Ready."), failed]).after).toEqual([failed]);
  });

  /** Open every stretch of calls the opened fold shows. */
  const openStretches = (container: HTMLElement) => {
    for (const line of Array.from(container.querySelectorAll<HTMLElement>("[data-trace-entry='activity'] > button[aria-expanded='false']"))) fireEvent.click(line);
  };

  it("folds a failed tool with the work once the turn has answered, and says so quietly", () => {
    // The complaint this guards (maintainer, 2026-11-10): failed steps stood
    // between the question and the answer as red rows of raw tool output,
    // with a red warning under the answer.
    const failed = tool("err", { isError: true, output: "Upload failed" });
    const { container } = render(<WorkTrace {...props} conversation blocks={[tool("a"), failed, reply("done", "I prepared a draft.")]} />);
    expect(screen.queryByText(/Upload failed/)).toBeNull();
    expect(container.querySelector('[data-trace-tool="err"]')).toBeNull();
    expect(screen.queryByTestId("tool-failure-warning")).toBeNull();
    expect(container.querySelector(".text-destructive")).toBeNull();
    // The fold names it in its own ink, and assistive technology still hears it.
    const fold = screen.getByTestId("conversation-work-fold").querySelector("button")!;
    expect(screen.getByTestId("trace-failed-count").textContent).toBe("1 step did not work");
    expect(screen.getByRole("status").textContent).toContain("A tool action failed");
    expect(screen.getAllByRole("status").at(-1)?.textContent).toContain("Done");
    // One tap shows the step and why it did not work; still nothing in red ink.
    fireEvent.click(fold);
    openStretches(container);
    expect(screen.getAllByText("Failed: Upload failed").length).toBeGreaterThan(0);
    expect(container.querySelector(".text-destructive")).toBeNull();
    expect(container.querySelector(".trace-flag")).toBeTruthy();
  });

  it("keeps a failed question poll in the folded work after a conversation completes", () => {
    const failedPoll = tool("poll", {
      name: "society_ask_user",
      input: { wait_for: "closed-question" },
      isError: true,
      output: "The question is closed.",
    });
    const { container } = render(<WorkTrace {...props} conversation blocks={[tool("a"), failedPoll, reply("done", "I could not get an answer.")]} />);
    expect(screen.getByTestId("trace-failed-count").textContent).toBe("1 step did not work");
    openWork();
    openStretches(container);
    expect(screen.getAllByText(/The question is closed\./).length).toBeGreaterThan(0);
  });

  it("says a failed step in plain words and keeps the tool's own words otherwise", () => {
    const t = (key: string) => ({
      "trace_report.reason.signed_out": "the sign-in has expired; reconnect it under Plugins",
      "trace_report.reason.rate_limited": "the service asked to slow down",
      "trace_report.reason.unavailable": "the service had a problem on its side",
      "trace_report.reason.timed_out": "it took too long to answer",
      "trace_report.reason.forbidden": "the account is not allowed to do this",
    } as Record<string, string>)[key] ?? key;
    expect(failureReason("Tool failed: x: HTTP 401; reconnect in Plugins or check account permissions", t)).toBe("the sign-in has expired; reconnect it under Plugins");
    expect(failureReason("HTTP 429 Too Many Requests", t)).toBe("the service asked to slow down");
    expect(failureReason("upstream said: status code 503", t)).toBe("the service had a problem on its side");
    expect(failureReason("Request timed out after 30s", t)).toBe("it took too long to answer");
    // A bare exit code gives way to the shell's own last clause.
    expect(failureReason("Exit code 126\n/usr/bin/bash: line 3: /c/Program Files/WindowsApps/PythonSoftwareFoundation.PythonManager_26.4.240.0_x64__qbz5n2kfra8p0/python: Permission denied", t))
      .toBe("Permission denied (exit code 126)");
    // Anything else is the tool's first line, and a status code deep in a long output is not a reason.
    expect(failureReason("Upload failed", t)).toBe("Upload failed");
    expect(failureReason("3 tests failed\nGET /login returned HTTP 401 as expected", t)).toBe("3 tests failed");
  });

  it("closes a failed turn with a note on a normal surface, never red ink", () => {
    const { container } = render(<WorkTrace {...props} status="error" error="The model stopped answering." blocks={[tool("a")]} />);
    const note = screen.getByRole("alert");
    expect(note.className).toContain("trace-note");
    expect(note.textContent).toBe("The model stopped answering.");
    expect(container.querySelector(".text-destructive")).toBeNull();
  });

  it("rests without a state line in a messenger conversation, and keeps it for a turn that needs one", () => {
    const answer = (text: string, _id: string, live: boolean) => <p data-testid="own-reply" data-live={String(live)}>{text}</p>;
    const { rerender } = render(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[tool("a"), reply("done", "All set.")]} receipt={<span>219 tokens</span>} />);
    // The caller draws the reply itself.
    expect(screen.getByTestId("own-reply").textContent).toBe("All set.");
    expect(screen.getByTestId("own-reply").getAttribute("data-live")).toBe("false");
    // Time and usage wait under the turn; "Done" is only there to be read out.
    const status = screen.getByRole("status");
    expect(status.className).toContain("trace-meta");
    expect(status.textContent).toContain("12s");
    expect(status.textContent).toContain("219 tokens");
    expect(within(status).getByText("Done").className).toBe("sr-only");
    // A reply being written says the turn is alive by growing.
    rerender(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[reply("mid", "Looking.")]} />);
    expect(screen.getByTestId("own-reply").getAttribute("data-live")).toBe("true");
    // A turn without an answer keeps its line in view.
    rerender(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[tool("a")]} />);
    expect(screen.getByRole("status").className).not.toContain("trace-meta");
  });

  it("shows a working messenger turn as three dots in a bubble, not as a state line", () => {
    const answer = (text: string) => <p data-testid="own-reply">{text}</p>;
    const thinking: TurnBlock = { kind: "reasoning", id: "now", text: "", live: true, durationMs: null, startedMs: 1000 };
    // Nothing has arrived yet: the dots stand alone, the words are only read out.
    const { rerender } = render(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[]} receipt={<span>4.8k tokens</span>} />);
    const dots = screen.getByTestId("typing-indicator");
    expect(dots.querySelectorAll("span")).toHaveLength(3);
    expect(dots.getAttribute("aria-hidden")).toBe("true");
    const status = screen.getByRole("status");
    expect(status.className).toContain("trace-meta");
    expect(within(status).getByText(/^Working/).closest(".sr-only")).toBeTruthy();
    expect(status.textContent).toContain("4.8k tokens");
    // A running step keeps the dots under it.
    rerender(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[tool("a", { output: null })]} />);
    expect(screen.getByTestId("typing-indicator")).toBeTruthy();
    // While the reply is written the growing bubble is the sign; the dots are gone.
    rerender(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[tool("a"), reply("mid", "Looking.")]} />);
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    // It thinks again after that message: it types again, below the message.
    rerender(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[tool("a"), reply("mid", "Looking."), thinking]} />);
    const again = screen.getByTestId("typing-indicator");
    expect(screen.getByTestId("own-reply").compareDocumentPosition(again) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // A turn that waits for the person is not typing: its line says what it waits for.
    rerender(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[tool("ask", { output: null, approval: { approvalId: "ap", summary: "Confirm", decision: null } })]} />);
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    expect(screen.getByRole("status").className).not.toContain("trace-meta");
    // Finished: no dots.
    rerender(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[tool("a"), reply("done", "All set.")]} />);
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    // Every other trace keeps its state line and draws no dots.
    rerender(<WorkTrace {...props} status="running" durationMs={null} blocks={[tool("a", { output: null })]} />);
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    expect(screen.getByRole("status").className).not.toContain("trace-meta");
  });

  it("draws no reasoning in a messenger conversation, live or finished", () => {
    const answer = (text: string) => <p data-testid="own-reply">{text}</p>;
    const thinking: TurnBlock = { kind: "reasoning", id: "now", text: "Weigh the options.", live: true, durationMs: null, startedMs: 1000 };
    // Running: no scratchpad, no finished thought; the state line carries the wait.
    const { rerender } = render(<WorkTrace {...props} status="running" durationMs={null} messenger renderAnswer={answer} blocks={[thought, tool("a"), thinking]} />);
    const trace = screen.getByTestId("work-trace");
    expect(screen.queryByTestId("reasoning-body")).toBeNull();
    expect(trace.textContent).not.toMatch(/Check|Weigh the options|Thinking|Thought/);
    expect(screen.getByRole("status").textContent).toContain("Working");
    // Finished: the fold holds the steps and says "Worked for", not "Thought for".
    rerender(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[thought, tool("a"), reply("done", "All set.")]} />);
    const fold = screen.getByTestId("conversation-work-fold");
    expect(within(fold).getByRole("button", { name: "Worked for 12s" })).toBeTruthy();
    openWork();
    expect(trace.querySelectorAll("[data-trace-entry='reasoning']")).toHaveLength(0);
    expect(trace.textContent).not.toMatch(/Check|Thought/);
    expect(trace.querySelector("[data-trace-entry='call']")).toBeTruthy();
    // Only thoughts stood before the answer: nothing is left to fold.
    rerender(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[thought, reply("done", "All set.")]} />);
    expect(screen.queryByTestId("conversation-work-fold")).toBeNull();
    expect(screen.getByTestId("own-reply").textContent).toBe("All set.");
    // Every other trace keeps its thoughts.
    rerender(<WorkTrace {...props} blocks={[thought, tool("a"), reply("done", "All set.")]} />);
    expect(within(screen.getByTestId("conversation-work-fold")).getByRole("button", { name: "Thought for 12s" })).toBeTruthy();
    openWork();
    expect(screen.getByTestId("work-trace").textContent).toContain("Check");
  });

  it("keeps what the assistant said before its steps as messages in a messenger conversation", () => {
    const answer = (text: string) => <p data-testid="own-reply">{text}</p>;
    const blocks = [reply("first", "I'll check the weather."), tool("a"), reply("mid", "Still on it."), tool("b"), reply("done", "Hot and humid.")];
    const { rerender } = render(<WorkTrace {...props} messenger renderAnswer={answer} blocks={blocks} />);
    const trace = screen.getByTestId("work-trace");
    // Fold closed: all three messages read, in the order they were sent.
    const fold = screen.getByTestId("conversation-work-fold");
    expect(fold.getAttribute("data-open")).toBe("false");
    expect(screen.getAllByTestId("own-reply").map((node) => node.textContent)).toEqual(["I'll check the weather.", "Still on it.", "Hot and humid."]);
    // The steps fold between what was said and the answer.
    const [first, mid, last] = screen.getAllByTestId("own-reply");
    expect(first.compareDocumentPosition(fold) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(mid.compareDocumentPosition(fold) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fold.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Opened, the fold holds the steps and does not say the messages again.
    openWork();
    expect(fold.querySelector("[data-trace-entry='activity']")).toBeTruthy();
    expect(fold.querySelector("[data-trace-entry='narration']")).toBeNull();
    expect(trace.textContent!.split("I'll check the weather.")).toHaveLength(2);
    // Only a thought stood between two messages: both stay, nothing folds.
    rerender(<WorkTrace {...props} messenger renderAnswer={answer} blocks={[reply("first", "One moment."), thought, reply("done", "Here it is.")]} />);
    expect(screen.queryByTestId("conversation-work-fold")).toBeNull();
    expect(screen.getAllByTestId("own-reply").map((node) => node.textContent)).toEqual(["One moment.", "Here it is."]);
    // Every other trace still folds its narration with the work.
    rerender(<WorkTrace {...props} blocks={blocks} />);
    expect(screen.getByTestId("work-trace").textContent).not.toContain("I'll check the weather.");
    openWork();
    expect(screen.getByTestId("work-trace").textContent).toContain("I'll check the weather.");
  });

  it("treats a tool-only turn as work", () => {
    expect(splitConversationTurn([tool("a")])).toEqual({ work: [tool("a")], answer: [], after: [] });
  });
});

describe("rail look", () => {
  it("reads as prose: quiet lines, no thread, no bullets", () => {
    const { container } = render(<WorkTrace {...props} status="running" blocks={[thought, tool("a", { name: "exec_command", input: { command: "npm test" } })]} />);
    expect(screen.getByTestId("work-trace").getAttribute("data-look")).toBe("rail");
    expect(container.querySelector(".trace-dot, .trace-node-live")).toBeNull();
    const call = container.querySelector("[data-trace-entry='call']")!;
    expect(call.textContent).toContain("npm test");
    expect(call.querySelector("svg")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Working");
  });

  it("keeps a live reply between the stretches it separates", () => {
    const { container } = render(<WorkTrace {...props} status="running" blocks={[tool("a", { name: "exec_command" }), reply("mid", "Halfway there."), tool("b", { name: "exec_command", output: null })]} />);
    const text = screen.getByTestId("work-trace").textContent!;
    const calls = container.querySelectorAll("[data-trace-entry='call']");
    expect(calls).toHaveLength(2);
    expect(text.indexOf("Halfway there.")).toBeGreaterThan(text.indexOf(calls[0].textContent!));
  });

  it("shimmers the call that is running and the live state line", () => {
    const { container } = render(<WorkTrace {...props} status="running" durationMs={null} blocks={[tool("a", { name: "exec_command", input: { command: "npm test" }, output: null })]} />);
    const running = container.querySelector('[data-trace-entry="call"][data-status="running"]')!;
    expect(running.querySelector(".trace-shimmer")?.textContent).toBe("npm test");
    expect(screen.getByRole("status").querySelector(".trace-shimmer")?.textContent).toBe("Working");
  });

  it("puts the pet on a live Jarvis trace and the plain node everywhere else", () => {
    const blocks = [tool("a", { name: "exec_command", output: null })];
    const { container, rerender } = render(<WorkTrace {...props} status="running" durationMs={null} blocks={blocks} companion />);
    expect(container.querySelector("[data-trace-pet]")?.getAttribute("data-trace-pet")).toBe("working");
    rerender(<WorkTrace {...props} status="running" durationMs={null} blocks={blocks} />);
    expect(container.querySelector("[data-trace-pet]")).toBeNull();
    rerender(<WorkTrace {...props} blocks={[tool("a", { name: "exec_command" })]} companion />);
    expect(container.querySelector("[data-trace-pet]")).toBeNull();
  });

  it("plays the pet's working row while Jarvis thinks or works, talking while it answers", () => {
    expect(livePetState([])).toBe("working");
    expect(livePetState([{ ...thought, live: true } as TurnBlock])).toBe("working");
    expect(livePetState([tool("s", { name: "grep", output: null })])).toBe("working");
    expect(livePetState([tool("x", { name: "exec_command" })])).toBe("working");
    expect(livePetState([reply("empty", "  ")])).toBe("working");
    expect(livePetState([reply("r", "Here it is")])).toBe("talking");
  });

  it("drops the shimmer once the turn is finished", () => {
    const { container } = render(<WorkTrace {...props} blocks={[tool("a", { name: "exec_command" })]} />);
    expect(container.querySelector(".trace-shimmer")).toBeNull();
    expect(container.querySelector(".trace-node-live")).toBeNull();
  });

  it("keeps the classic rows for the Agentic IDE", () => {
    const { container } = render(<WorkTrace {...props} look="classic" blocks={[thought, tool("a")]} />);
    expect(screen.getByTestId("work-trace").hasAttribute("data-look")).toBe(false);
    expect(container.querySelector(".trace-rail")).toBeNull();
    expect(screen.getByRole("status").className).toMatch(/border-t/);
  });

  it("shows a plugin call by its own logo once the folded work opens", () => {
    const blocks = [tool("linear", { name: "mcp__codex_apps__linear_list_issues" }), reply("done", "Three issues are open.")];
    render(<WorkTrace {...props} conversation blocks={blocks} />);
    openWork();
    const line = screen.getByRole("button", { name: /^Linear/ });
    expect(line.querySelector("img, [data-logo]")).toBeTruthy();
    expect(screen.getByText("Three issues are open.")).toBeTruthy();
  });
});
