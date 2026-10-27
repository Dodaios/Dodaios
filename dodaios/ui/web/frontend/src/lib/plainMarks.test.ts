import { describe, expect, it } from "vitest";
import { previewOf } from "@/components/agentchat/inspector/inspectorRows";
import { previewText } from "@/components/society/roster/rosterPreview";
import { stripInlineMarks } from "./plainMarks";

describe("stripInlineMarks", () => {
  it("keeps the underscores of file names and identifiers", () => {
    expect(stripInlineMarks("Wrote qa_note.txt")).toBe("Wrote qa_note.txt");
    expect(stripInlineMarks("call tool_search then my_long_name")).toBe("call tool_search then my_long_name");
    expect(stripInlineMarks("2*3*4")).toBe("2*3*4");
    expect(stripInlineMarks("Edited __init__.py, then ran __main__")).toBe("Edited __init__.py, then ran __main__");
  });

  it("takes off emphasis, code ticks and strike marks", () => {
    expect(stripInlineMarks("**Done** with `qa_note.txt`, _really_ ~~not~~ *yet*")).toBe("Done with qa_note.txt, really not yet");
    expect(stripInlineMarks("__very bold__ and **qa_note.txt**")).toBe("very bold and qa_note.txt");
  });
});

describe("plain previews keep file names whole", () => {
  it("in the roster preview and the chat header", () => {
    expect(previewText("I saved `qa_note.txt` in the **workspace**.")).toBe("I saved qa_note.txt in the workspace.");
    expect(previewText("- wrote qa_note.txt\n> quoted")).toBe("wrote qa_note.txt quoted");
  });

  it("in the work trace rows", () => {
    expect(previewOf("## Result\nCreated qa_note.txt")).toBe("Result");
    expect(previewOf("Created *qa_note.txt*")).toBe("Created qa_note.txt");
  });
});
