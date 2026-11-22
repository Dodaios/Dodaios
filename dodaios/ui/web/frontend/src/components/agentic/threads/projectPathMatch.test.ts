import { describe, expect, it } from "vitest";

import { matchProjectPath } from "./projectPathMatch";

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

  it("reads folders listed with a trailing slash, as the file search lists them", () => {
    const listed = ["dodaios/", "dodaios/memory/", "dodaios/memory/vault/", "mcps/", "dodaios/memory/vault/store.py"];
    expect(matchProjectPath("memory/vault/", FOLDER, listed)).toEqual({ path: "dodaios/memory/vault", kind: "directory" });
    expect(matchProjectPath("mcps/", FOLDER, listed)).toEqual({ path: "mcps", kind: "directory" });
    expect(matchProjectPath("vault/store.py", FOLDER, listed)).toEqual({ path: "dodaios/memory/vault/store.py", kind: "file" });
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
