import { describe, expect, it } from "vitest";

import { fileRefLabel, fileRefName, fileRefSuffixes, fileRefsInMarkdown } from "./fileRefs";

describe("file reference labels", () => {
  it("names a file by its name and a folder by its own name", () => {
    expect(fileRefName("dodaios/core/config.py")).toBe("config.py");
    expect(fileRefName("wiki/obsidian-vault/")).toBe("obsidian-vault");
    expect(fileRefName("C:\\Users\\me\\notes.md")).toBe("notes.md");
  });

  it.each([
    [{ path: "src/app.ts" }, undefined, "app.ts"],
    [{ path: "src/app.ts", line: 42 }, undefined, "app.ts · L42"],
    [{ path: "src/app.ts", line: 42, endLine: 64 }, undefined, "app.ts · L42–64"],
    [{ path: "src/app.ts", line: 42, column: 7 }, undefined, "app.ts · L42:C7"],
    [{ path: "a/lib/app.ts", line: 3 }, "a/lib", "app.ts · a/lib · L3"],
  ])("labels %o", (ref, suffix, label) => {
    expect(fileRefLabel(ref, suffix)).toBe(label);
  });

  it("composes a decomposed name for display", () => {
    expect(fileRefLabel({ path: "docs/cafe\u0301.md" })).toBe("caf\u00e9.md");
  });
});

describe("telling same-named files apart", () => {
  it("adds the parent folders only where two named files share a name", () => {
    const suffixes = fileRefSuffixes(["society/memory.py", "core/memory.py", "setup/state.py", "society/memory.py"]);
    expect(suffixes.get("society/memory.py")).toBe("society");
    expect(suffixes.get("core/memory.py")).toBe("core");
    expect(suffixes.has("setup/state.py")).toBe(false);
  });

  it("goes as deep as it takes, and at least two folders when there are", () => {
    const suffixes = fileRefSuffixes(["a/x/src/app.ts", "b/x/src/app.ts", "lib/app.ts"]);
    expect(suffixes.get("a/x/src/app.ts")).toBe("a/x/src");
    expect(suffixes.get("b/x/src/app.ts")).toBe("b/x/src");
    expect(suffixes.get("lib/app.ts")).toBe("lib");
  });

  it("reads a path that ends another one as the same file", () => {
    expect(fileRefSuffixes(["core/config.py", "dodaios/core/config.py"]).size).toBe(0);
    const suffixes = fileRefSuffixes(["core/memory.py", "dodaios/core/memory.py", "society/memory.py"]);
    expect(suffixes.get("dodaios/core/memory.py")).toBe("dodaios/core");
    expect(suffixes.get("core/memory.py")).toBe("dodaios/core");
    expect(suffixes.get("society/memory.py")).toBe("society");
  });

  it("reads the paths from inline code, not from fenced blocks", () => {
    const text = "Edit `src/app.ts:4` and `docs/`.\n\n```\nlib/app.ts\n`other/app.ts`\n```\nRun `npm test`.";
    expect(fileRefsInMarkdown(text)).toEqual(["src/app.ts", "docs/"]);
  });
});
