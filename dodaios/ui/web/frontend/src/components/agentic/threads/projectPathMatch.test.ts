import { describe, expect, it } from "vitest";

import { filesFromFolder, matchProjectPath } from "./projectPathMatch";

const FILES = [
  "README.md",
  "dodaios/core/config.py",
  "dodaios/core/branding.py",
  "dodaios/memory/vault/legacy_import.py",
  "dodaios/setup/state.py",
  "dodaios/society/memory.py",
  "dodaios/agent_chat/memory.py",
  "dodaios/ui/web/frontend/src/components/society/arcade/Arcade.tsx",
  "dodaios/ui/web/frontend/src/components/society/arcade/parts/Tile.tsx",
  "docs/architecture-overview.md",
  "tests/unit/core/test_config.py",
];
const FOLDER = "/Users/me/Dodaios";

describe("which project file a path means", () => {
  it.each([
    // Named from inside the package, as agents often do.
    ["core/config.py", "dodaios/core/config.py"],
    ["memory/vault/legacy_import.py", "dodaios/memory/vault/legacy_import.py"],
    ["setup/state.py", "dodaios/setup/state.py"],
    // The project folder's own name repeated in front.
    ["Dodaios/docs/architecture-overview.md", "docs/architecture-overview.md"],
    // A bare name that only one file has.
    ["branding.py", "dodaios/core/branding.py"],
    ["readme.md", "README.md"],
    ["core\\config.py", "dodaios/core/config.py"],
  ])("%s is %s", (written, path) => {
    expect(matchProjectPath(written, FOLDER, FILES)).toEqual({ path, kind: "file" });
  });

  it.each([
    ["components/society/arcade/", "dodaios/ui/web/frontend/src/components/society/arcade"],
    ["society/arcade", "dodaios/ui/web/frontend/src/components/society/arcade"],
    ["arcade/", "dodaios/ui/web/frontend/src/components/society/arcade"],
    ["Dodaios/dodaios/memory/", "dodaios/memory"],
  ])("finds the folder %s", (written, path) => {
    expect(matchProjectPath(written, FOLDER, FILES)).toEqual({ path, kind: "directory" });
  });

  it.each([
    "memory.py", // two files of that name
    "nothing/here.py",
    "/Users/me/Dodaios/core/config.py",
    "./core/config.py",
    "../core/config.py",
    "~/core/config.py",
    "C:\\Repo\\core\\config.py",
    "",
  ])("never guesses for %s", (written) => {
    expect(matchProjectPath(written, FOLDER, FILES)).toBeNull();
  });
});

describe("the project's files from the thread's folder", () => {
  it("are the listing itself when the thread works in the workspace folder", () => {
    expect(filesFromFolder(["a/b.py"], "/Users/me/Dodaios/", "/Users/me/Dodaios")).toEqual(["a/b.py"]);
  });

  it("are the files under the thread's folder when it is inside the workspace", () => {
    expect(filesFromFolder(["web/src/app.ts", "core/x.py"], "/repo", "/repo/web")).toEqual(["src/app.ts"]);
    expect(filesFromFolder(["Web\\src\\app.ts"], "C:\\Repo", "c:\\repo\\web")).toEqual(["src/app.ts"]);
  });

  it("are unknown for a thread outside the workspace folder", () => {
    expect(filesFromFolder(["a.py"], "/repo", "/elsewhere")).toBeNull();
    expect(filesFromFolder(["a.py"], "/repo", "/repository")).toBeNull();
  });
});
