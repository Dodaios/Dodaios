import { describe, expect, it } from "vitest";

import type { TimelineRow } from "./api";
import { escapeHtml, formatText, renderRow, renderRows } from "./rows";

const t = (key: string, fills: Record<string, string | number> = {}) =>
  Object.entries(fills).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), `[${key}]`);

const NOW = Date.UTC(2026, 10, 10, 12, 0, 0);

describe("rows", () => {
  it("escapes model text and keeps paragraphs", () => {
    expect(escapeHtml('<b>"x"</b> & y')).toBe("&lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; y");
    expect(formatText("one\ntwo\n\nthree")).toBe("<p>one<br>two</p><p>three</p>");
  });

  it("renders the person's and the assistant's rows as bubbles", () => {
    const user: TimelineRow = { id: "u-1", kind: "user", text: "Hi <there>", ts_ms: NOW };
    const html = renderRow(user, t, NOW);
    expect(html).toContain('class="row row-user"');
    expect(html).toContain("Hi &lt;there&gt;");
    expect(renderRow({ id: "a-2", kind: "assistant", text: "Hello.", ts_ms: NOW }, t, NOW)).toContain("row-assistant");
  });

  it("renders an open approval with both buttons and a settled one without", () => {
    const open: TimelineRow = {
      id: "ap-1", kind: "approval", approval_id: "ap1", name: "run", text: "rm -rf build", ts_ms: NOW, decision: null,
    };
    const html = renderRow(open, t, NOW);
    expect(html).toContain('data-approve="ap1" data-decision="allow"');
    expect(html).toContain('data-decision="deny"');
    expect(html).toContain("is-open");
    const settled = renderRow({ ...open, decision: "deny" }, t, NOW);
    expect(settled).not.toContain("data-approve");
    expect(settled).toContain("[decided_deny]");
    expect(settled).toContain("is-settled");
  });

  it("renders questions, notices and errors", () => {
    expect(renderRow({ id: "q", kind: "question", text: "Which?", ts_ms: NOW, answered: false }, t, NOW)).toContain("[question_hint]");
    expect(renderRow({ id: "q", kind: "question", text: "Which?", ts_ms: NOW, answered: true }, t, NOW)).not.toContain("[question_hint]");
    expect(renderRow({ id: "n", kind: "notice", text: "Done.", ts_ms: NOW }, t, NOW)).toContain("row-notice");
    expect(renderRow({ id: "e", kind: "error", text: "Boom", ts_ms: NOW }, t, NOW)).toContain("is-error");
  });

  it("shows an empty line when there are no rows", () => {
    expect(renderRows([], t, NOW)).toContain("[empty]");
  });
});
