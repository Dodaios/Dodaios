import { describe, expect, it } from "vitest";
import {
  insertMention, linksToMentions, mentionLabel, mentionSpans, mentionsToLinks, outsideMentions, splitThreadLinks,
  type ThreadMention,
} from "./threadMentions";

const LOGIN: ThreadMention = { sessionId: "3f9a2c11-aaaa-bbbb-cccc-000000000001", label: "Fix login redirect", provider: "claude-api" };

describe("thread mentions", () => {
  it("shortens a long title to a few words and keeps names apart", () => {
    expect(mentionLabel("Fix the login redirect after the OAuth callback fails")).toBe("Fix the login redirect");
    expect(mentionLabel("Fix [login]")).toBe("Fix login");
    expect(mentionLabel("Login", ["Login"])).toBe("Login 2");
    expect(mentionLabel("   ")).toBe("agent");
  });

  it("lands inside the sentence with a space on either side", () => {
    expect(insertMention("ask what changed", 4, "Login")).toEqual({ text: "ask @Login what changed", caret: 11 });
    expect(insertMention("ask", 3, "Login")).toEqual({ text: "ask @Login ", caret: 11 });
    expect(insertMention("", 0, "Login")).toEqual({ text: "@Login ", caret: 7 });
  });

  it("finds only whole names and never splits one on a drop", () => {
    const text = "wait for @Fix login redirect, not @Fix login redirects";
    const spans = mentionSpans(text, [LOGIN]);
    expect(spans).toHaveLength(1);
    expect(text.slice(spans[0].start, spans[0].end)).toBe("@Fix login redirect");
    expect(outsideMentions(spans[0].start + 3, spans)).toBe(spans[0].end);
    expect(outsideMentions(spans[0].start, spans)).toBe(spans[0].start);
  });

  it("sends names as thread links and takes them back as names", () => {
    const sent = mentionsToLinks("ask @Fix login redirect first", [LOGIN]);
    expect(sent).toBe(`ask [Fix login redirect](thread:${LOGIN.sessionId}) first`);
    const back = linksToMentions(sent, () => "claude-api");
    expect(back.text).toBe("ask @Fix login redirect first");
    expect(back.mentions).toEqual([LOGIN]);
    expect(splitThreadLinks(sent)).toEqual([
      { text: "ask " }, { label: "Fix login redirect", sessionId: LOGIN.sessionId }, { text: " first" },
    ]);
  });
});
