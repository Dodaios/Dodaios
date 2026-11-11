import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/agenticIdeApi", () => ({
  fetchFolders: vi.fn(),
  searchFolders: vi.fn(),
  fetchRecents: vi.fn(),
  forgetRecent: vi.fn(),
  resolveDroppedFolder: vi.fn(),
  fetchNativePickerSupport: vi.fn(),
  openNativePicker: vi.fn(),
  createFolder: vi.fn(),
}));

import {
  FolderPicker,
  extractDropPayload,
  isAbsolutePath,
  joinPath,
  lastUsedLabel,
  leafName,
  looksLikePath,
  normalizeTypedPath,
  pathCrumbs,
  resolveTypedPath,
  separatorOf,
  splitTypedPath,
} from "./FolderPicker";
import { foldCrumbs, isFolderName, matchByName, parentPath, typedParts } from "./folderPaths";
import * as api from "@/lib/agenticIdeApi";

const HOME = "/home/ruben";

/** The folders of a small pretend machine: path -> names of its sub-folders. */
const DISK: Record<string, string[]> = {
  "/": ["home", "srv"],
  "/home": ["ruben"],
  "/home/ruben": ["webshop", "notes"],
  "/home/ruben/webshop": ["src"],
  "/home/ruben/webshop/src": [],
  "/home/ruben/notes": [],
  "/srv": ["deploy"],
  "/srv/deploy": [],
};

const REPOS = new Set(["/home/ruben/webshop"]);

function item(path: string) {
  return {
    name: path.split("/").pop() || "/",
    path,
    is_project: REPOS.has(path),
    is_repo: REPOS.has(path),
  };
}

/** What the backend would answer: `~`, `..` and relative paths resolved. */
function resolveOnDisk(target: string, base?: string | null): string {
  let full = target === "~" ? HOME : target.replace(/^~\//, `${HOME}/`);
  if (!full.startsWith("/")) full = `${base ?? HOME}/${full}`;
  const out: string[] = [];
  for (const part of full.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") out.pop();
    else out.push(part);
  }
  return `/${out.join("/")}`;
}

async function fakeFolders(target?: string | null, _hidden?: boolean, base?: string | null) {
  if (!target) {
    return {
      path: null,
      parent: null,
      entries: DISK[HOME].map((name) => item(`${HOME}/${name}`)),
      device_name: "Rubens MacBook",
      home: HOME,
    };
  }
  const path = resolveOnDisk(target, base);
  const parent = path === "/" ? null : path.slice(0, path.lastIndexOf("/")) || "/";
  const names = DISK[path];
  if (!names) {
    return {
      path,
      parent,
      entries: [],
      error: `There is no folder called ${path}. Check the spelling, or pick a folder from the list.`,
      device_name: "Rubens MacBook",
      home: HOME,
    };
  }
  return {
    path,
    parent,
    entries: names.map((name) => item(path === "/" ? `/${name}` : `${path}/${name}`)),
    device_name: "Rubens MacBook",
    home: HOME,
  };
}

beforeEach(() => {
  vi.mocked(api.fetchFolders).mockImplementation(fakeFolders);
  vi.mocked(api.fetchRecents).mockResolvedValue({
    device_name: "Rubens MacBook",
    recents: [],
  });
  vi.mocked(api.searchFolders).mockResolvedValue({
    query: "",
    entries: [],
    truncated: false,
  });
  // The default is "this machine cannot show a folder window", which is what a
  // headless install and a remote browser both report — so every test keeps
  // asserting against the path that must work everywhere.
  vi.mocked(api.fetchNativePickerSupport).mockResolvedValue({ available: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function field(): HTMLInputElement {
  return screen.getByTestId("folder-search") as HTMLInputElement;
}

function type(value: string) {
  fireEvent.change(field(), { target: { value } });
}

/** Render the picker and wait for the start view. */
async function open(props: Partial<React.ComponentProps<typeof FolderPicker>> = {}) {
  const onSelect = vi.fn();
  render(<FolderPicker selected={null} onSelect={onSelect} {...props} />);
  await screen.findByText("webshop");
  return onSelect;
}

/** Minimal DataTransfer stand-in — jsdom has no real one. */
function dataTransfer(opts: {
  text?: string;
  uriList?: string;
  directoryName?: string;
  relativePath?: string;
}): DataTransfer {
  const items: unknown[] = [];
  if (opts.directoryName) {
    items.push({
      kind: "file",
      type: "",
      webkitGetAsEntry: () => ({ isDirectory: true, name: opts.directoryName }),
    });
  }
  const files = opts.relativePath
    ? [Object.assign(new File(["x"], "file.txt"), { webkitRelativePath: opts.relativePath })]
    : [];
  return {
    dropEffect: "none",
    getData: (type: string) =>
      type === "text/uri-list" ? (opts.uriList ?? "") : (opts.text ?? ""),
    items,
    files,
    types: ["Files"],
  } as unknown as DataTransfer;
}

describe("extractDropPayload", () => {
  it("prefers a real path from the URI list", () => {
    const payload = extractDropPayload(
      dataTransfer({ uriList: "file:///home/ruben/webshop\r\n" }),
    );
    expect(payload.path).toBe("file:///home/ruben/webshop");
  });

  it("falls back to plain text", () => {
    expect(extractDropPayload(dataTransfer({ text: "C:\\work\\shop" })).path).toBe(
      "C:\\work\\shop",
    );
  });

  it("takes the folder name when no path is offered", () => {
    // This is the normal browser case: a dropped directory exposes its NAME but
    // never its path, so the backend has to search for it.
    const payload = extractDropPayload(dataTransfer({ directoryName: "webshop" }));
    expect(payload.name).toBe("webshop");
    expect(payload.path).toBeUndefined();
  });

  it("derives the folder name from a dropped file inside it", () => {
    const payload = extractDropPayload(
      dataTransfer({ relativePath: "webshop/src/main.ts" }),
    );
    expect(payload.name).toBe("webshop");
  });

  it("returns nothing for an empty drop", () => {
    expect(extractDropPayload(dataTransfer({}))).toEqual({});
    expect(extractDropPayload(null)).toEqual({});
  });
});

describe("the start view", () => {
  it("labels the machine by its own name, not the account folder", async () => {
    await open();
    expect(screen.getByText("Rubens MacBook")).toBeTruthy();
  });

  it("offers recent workspaces and replays their layout", async () => {
    vi.mocked(api.fetchRecents).mockResolvedValue({
      device_name: "Rubens MacBook",
      recents: [
        {
          path: "/home/ruben/webshop",
          name: "webshop",
          terminals: 3,
          agents: { claude: 2, codex: 1 },
          last_used: 1,
          exists: true,
        },
      ],
    });
    const onSelectRecent = vi.fn();
    const onSelect = await open({ onSelectRecent });

    expect(await screen.findByText("Recent folders")).toBeTruthy();
    const icon = await screen.findByTestId("recent-folder-icon");
    // The same folder is a place too; it is listed once, as the recent one.
    expect(screen.getAllByText("webshop")).toHaveLength(1);
    fireEvent.click(icon.closest("button")!);
    expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop");
    expect(onSelectRecent).toHaveBeenCalledWith(
      expect.objectContaining({ terminals: 3, agents: { claude: 2, codex: 1 } }),
    );
  });

  it("shows recent folders on the start view only", async () => {
    vi.mocked(api.fetchRecents).mockResolvedValue({
      device_name: "Rubens MacBook",
      recents: [
        { path: "/srv/deploy", name: "deploy", terminals: 1, agents: {}, last_used: 1, exists: true },
      ],
    });
    await open();
    expect(await screen.findByText("Recent folders")).toBeTruthy();

    fireEvent.click(screen.getByText("notes"));

    await waitFor(() => expect(screen.queryByText("Recent folders")).toBeNull());
  });

  it("says when a recent folder was last used, in words", () => {
    const now = new Date(2026, 8, 30, 10, 0).getTime();
    expect(lastUsedLabel(now / 1000, now)).toBe("Today");
    expect(lastUsedLabel(new Date(2026, 8, 29, 23, 0).getTime() / 1000, now)).toBe(
      "Yesterday",
    );
    // Milliseconds are read as well as the seconds the backend stores.
    expect(lastUsedLabel(new Date(2026, 8, 26, 12, 0).getTime(), now)).toBe("4 days ago");
    expect(lastUsedLabel(new Date(2026, 8, 16, 12, 0).getTime() / 1000, now)).toBe(
      "2 weeks ago",
    );
    expect(lastUsedLabel(0, now)).toBe("");
  });
});

describe("clicking through folders", () => {
  it("opens a folder, chooses it and lists what is inside", async () => {
    const onSelect = await open();

    fireEvent.click(screen.getByText("webshop"));

    expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop");
    expect(await screen.findByText("src")).toBeTruthy();
    expect(api.fetchFolders).toHaveBeenLastCalledWith("/home/ruben/webshop", false);
  });

  it("shows only the folder clicked last when answers arrive out of order", async () => {
    // Two quick clicks: the first folder's listing is slow and lands after the
    // second one's. It used to win, and the list showed one folder under the
    // other one's name.
    await open();
    let releaseSlow: () => void = () => {};
    vi.mocked(api.fetchFolders).mockImplementation(async (target, hidden, base) => {
      if (target === "/home/ruben/webshop") {
        await new Promise<void>((resolve) => {
          releaseSlow = resolve;
        });
      }
      return fakeFolders(target, hidden, base);
    });

    fireEvent.click(screen.getByText("webshop"));
    fireEvent.click(screen.getByRole("button", { name: "Go up one folder" }));
    await screen.findByText("notes");
    await act(async () => {
      releaseSlow();
    });

    expect(screen.queryByText("src")).toBeNull();
    expect(screen.getByText("notes")).toBeTruthy();
  });

  it("keeps the folder before on screen, but closed, while the next one is on its way", async () => {
    const onSelect = await open();
    let release: () => void = () => {};
    vi.mocked(api.fetchFolders).mockImplementation(async (target, hidden, base) => {
      if (target === "/home/ruben/webshop") {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      }
      return fakeFolders(target, hidden, base);
    });

    fireEvent.click(screen.getByText("webshop"));

    // The list does not go blank between two folders...
    expect(screen.getByText("notes")).toBeTruthy();
    // ...but its rows belong to the folder before: a key cannot open one.
    onSelect.mockClear();
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();

    await act(async () => {
      release();
    });
    expect(await screen.findByText("src")).toBeTruthy();
    expect(screen.queryByText("notes")).toBeNull();
  });

  it("opens a crumb and chooses it, the same as opening a folder", async () => {
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes"));

    fireEvent.click(screen.getByRole("button", { name: "home" }));

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home"));
    expect(api.fetchFolders).toHaveBeenLastCalledWith("/home", false);
  });

  it("chooses the folder above when going up", async () => {
    // The folder on screen is the folder chosen — going up must not leave the
    // choice behind on a folder that is no longer shown.
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));

    fireEvent.click(screen.getByRole("button", { name: "Go up one folder" }));

    await waitFor(() => expect(onSelect).toHaveBeenLastCalledWith("/home/ruben"));
  });

  it("goes up on Backspace in the empty field, but not on a held key", async () => {
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));
    onSelect.mockClear();

    // Holding Backspace to clear a long text must not run on up the tree.
    fireEvent.keyDown(field(), { key: "Backspace", repeat: true });
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.keyDown(field(), { key: "Backspace" });
    expect(onSelect).toHaveBeenCalledWith("/home/ruben");
  });

  it("lists hidden folders only once the switch is on", async () => {
    await open();
    expect(api.fetchFolders).toHaveBeenLastCalledWith(null, false);

    fireEvent.click(screen.getByTestId("toggle-hidden"));

    await waitFor(() => expect(api.fetchFolders).toHaveBeenLastCalledWith(null, true));
  });
});

describe("typing a name", () => {
  it("narrows the list on a single character without asking the backend to search", async () => {
    await open();
    type("n");
    expect(screen.queryByText("webshop")).toBeNull();
    expect(screen.getByText("notes")).toBeTruthy();
    expect(api.searchFolders).not.toHaveBeenCalled();
  });

  it("opens the first match on Enter", async () => {
    const onSelect = await open();
    type("not");
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes");
    // The field is ready for the next name, the way a terminal is.
    expect(field().value).toBe("");
  });

  it("does not mistake a recent folder for the folder it lives in", async () => {
    // Seen with a real store: every recent folder on the Desktop has "Desktop"
    // in its PATH, was listed above the Desktop itself, and "cd Desktop"
    // followed by Enter opened one of them.
    vi.mocked(api.fetchRecents).mockResolvedValue({
      device_name: "Rubens MacBook",
      recents: [
        { path: "/home/ruben/notes/drafts", name: "drafts", terminals: 1, agents: {}, last_used: 1, exists: true },
      ],
    });
    const onSelect = await open();
    await screen.findByText("drafts");

    type("cd notes");
    fireEvent.keyDown(field(), { key: "Enter" });

    expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes");
  });

  it("reads a leading cd the way a shell does", async () => {
    const onSelect = await open();
    type("cd webshop");
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop");
  });

  it("moves through the list with the arrow keys", async () => {
    const onSelect = await open();
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    fireEvent.keyDown(field(), { key: "ArrowDown" });
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes");
  });

  it("also finds folders of that name elsewhere on the machine", async () => {
    vi.mocked(api.searchFolders).mockResolvedValue({
      query: "shop",
      entries: [
        { name: "old-webshop", path: "/archive/old-webshop", is_project: true, is_repo: false },
      ],
      truncated: false,
    });
    await open();

    type("shop");

    await waitFor(() => expect(api.searchFolders).toHaveBeenCalledWith("shop"), {
      timeout: 2000,
    });
    // Results show their full path, since they can be anywhere on the machine.
    expect(await screen.findByText("/archive/old-webshop")).toBeTruthy();
    // The folder on screen that matches is still listed, and listed first.
    expect(screen.getByText("webshop")).toBeTruthy();
  });

  it("opens the one folder of that name wherever it is", async () => {
    // Typed and entered before the search under the field has answered: the
    // name is not a folder here, but exactly one folder is called that.
    vi.mocked(api.searchFolders).mockResolvedValue({
      query: "deploy",
      entries: [
        { name: "deploy", path: "/srv/deploy", is_project: false, is_repo: false },
        { name: "deploy-old", path: "/archive/deploy-old", is_project: false, is_repo: false },
      ],
      truncated: false,
    });
    const onSelect = await open();

    type("deploy");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/srv/deploy"));
  });

  it("gives Escape to the field while it holds text", async () => {
    await open();
    // Empty, the key belongs to the host dialog.
    expect(field().closest("[data-escape-local]")).toBeNull();

    type("web");
    expect(field().closest("[data-escape-local]")).toBeTruthy();
    fireEvent.keyDown(field(), { key: "Escape" });

    expect(field().value).toBe("");
    expect(screen.getByText("notes")).toBeTruthy();
  });

  it("confirms the choice on Enter in the empty field", async () => {
    const onConfirm = vi.fn();
    render(<FolderPicker selected="/home/ruben/notes" onSelect={vi.fn()} onConfirm={onConfirm} />);
    await screen.findByText("webshop");

    fireEvent.keyDown(field(), { key: "Enter" });

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("puts names that start with the word before names that contain it", () => {
    const entries = [{ name: "old-shop" }, { name: "Shop" }, { name: "notes" }, { name: "shop-2" }];
    expect(matchByName(entries, "shop").map((e) => e.name)).toEqual(["Shop", "shop-2", "old-shop"]);
    expect(matchByName(entries, "")).toBe(entries);
  });
});

describe("typing a path", () => {
  it("splits what was typed into a folder and what to match", () => {
    expect(splitTypedPath("/home/ruben/web")).toEqual({
      dir: "/home/ruben/",
      leaf: "web",
    });
    expect(splitTypedPath("C:\\work\\sh")).toEqual({ dir: "C:\\work\\", leaf: "sh" });
    // A bare name has no folder part — that is what makes `cd notes` work.
    expect(splitTypedPath("notes")).toEqual({ dir: "", leaf: "notes" });
    // The words that are a folder by themselves have no name part.
    expect(typedParts("..")).toEqual({ dir: "..", leaf: "" });
    expect(typedParts("~")).toEqual({ dir: "~", leaf: "" });
    expect(typedParts("D:")).toEqual({ dir: "D:", leaf: "" });
    expect(typedParts("notes")).toEqual({ dir: "", leaf: "notes" });
  });

  it("reads the separator off a real path instead of guessing", () => {
    // The UI may well be open on a different machine than the backend, so
    // asking the browser which OS this is would answer about the wrong one.
    expect(separatorOf("C:\\work\\shop")).toBe("\\");
    expect(separatorOf("/home/ruben")).toBe("/");
    expect(joinPath("C:\\work", "shop")).toBe("C:\\work\\shop");
    expect(joinPath("/home/ruben/", "webshop")).toBe("/home/ruben/webshop");
  });

  it("reads what was typed the way a shell would", () => {
    // People type the cd. It is not part of the path, and neither are the
    // quotes around a path pasted from a terminal.
    expect(normalizeTypedPath("cd haral\\.personal-jarvis")).toBe(
      "haral\\.personal-jarvis",
    );
    expect(normalizeTypedPath("CD /d D:\\work")).toBe("D:\\work");
    expect(normalizeTypedPath('cd "C:\\My Projects\\shop"')).toBe(
      "C:\\My Projects\\shop",
    );
    expect(normalizeTypedPath("  notes ")).toBe("notes");
    expect(normalizeTypedPath("cd")).toBe("");
    // A folder that happens to start with "cd" is left alone.
    expect(normalizeTypedPath("cdrom")).toBe("cdrom");
    // A prompt copied whole is the path inside it.
    expect(normalizeTypedPath("PS C:\\Users\\me\\.claude>")).toBe("C:\\Users\\me\\.claude");
    expect(normalizeTypedPath("C:\\Users\\me\\.claude> ")).toBe("C:\\Users\\me\\.claude");
  });

  it("knows which paths name their own root", () => {
    expect(isAbsolutePath("/srv/deploy")).toBe(true);
    expect(isAbsolutePath("C:\\work")).toBe(true);
    expect(isAbsolutePath("c:/work")).toBe(true);
    expect(isAbsolutePath("\\\\server\\share")).toBe(true);
    expect(isAbsolutePath("~/code")).toBe(true);
    expect(isAbsolutePath("haral\\.personal-jarvis")).toBe(false);
    expect(isAbsolutePath("notes")).toBe(false);
    expect(looksLikePath("C:\\Users\\me")).toBe(true);
    expect(looksLikePath("Desktop/shop")).toBe(true);
    expect(looksLikePath("~")).toBe(true);
    expect(looksLikePath("shop")).toBe(false);
  });

  it("resolves a relative path against the folder on screen, like cd", () => {
    expect(resolveTypedPath("cd haral\\.personal-jarvis", "C:\\Users")).toBe(
      "C:\\Users\\haral\\.personal-jarvis",
    );
    expect(resolveTypedPath("notes", "/home/ruben")).toBe("/home/ruben/notes");
    expect(resolveTypedPath("/srv/deploy", "/home/ruben")).toBe("/srv/deploy");
    // Nothing on screen yet: the text goes through as typed.
    expect(resolveTypedPath("projects/shop", null)).toBe("projects/shop");
    expect(resolveTypedPath("cd", "/home/ruben")).toBe("");
  });

  it("opens a relative path from the home folder on the start view", async () => {
    const onSelect = await open();

    type("cd webshop/src");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop/src"));
    // The backend resolves it, against the home folder: it knows `..` and `~`.
    expect(api.fetchFolders).toHaveBeenCalledWith("webshop/src", false, "/home/ruben");
  });

  it("opens a relative path from the folder on screen", async () => {
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes"));

    type("cd ../webshop");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenLastCalledWith("/home/ruben/webshop"));
    expect(api.fetchFolders).toHaveBeenCalledWith("../webshop", false, "/home/ruben/notes");
  });

  it("goes up on cd ..", async () => {
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));

    type("cd ..");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenLastCalledWith("/home/ruben"));
  });

  it("goes back to the folder before on cd -", async () => {
    const onSelect = await open();
    fireEvent.click(screen.getByText("webshop"));
    fireEvent.click(await screen.findByText("src"));
    await waitFor(() => expect(onSelect).toHaveBeenLastCalledWith("/home/ruben/webshop/src"));

    type("cd -");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenLastCalledWith("/home/ruben/webshop"));
  });

  it("uses a full path exactly as typed", async () => {
    const onSelect = await open();

    type("/srv/deploy");
    fireEvent.keyDown(field(), { key: "Enter" });

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/srv/deploy"));
    expect(api.fetchFolders).toHaveBeenCalledWith("/srv/deploy", false);
  });

  it("lists the folders a half-typed path could mean", async () => {
    await open();

    type("/home/ruben/web");

    // The list under the field is the completion: only what matches.
    expect(await screen.findByText("Folders in /home/ruben")).toBeTruthy();
    expect(screen.getByText("webshop")).toBeTruthy();
    expect(screen.queryByText("notes")).toBeNull();
  });

  it("Tab completes the name and leaves the next part ready to type", async () => {
    await open();
    type("web");

    fireEvent.keyDown(field(), { key: "Tab" });

    // The trailing separator is the point: typing continues into the folder.
    expect(field().value).toBe("webshop/");
    expect(await screen.findByText("src", {}, { timeout: 2000 })).toBeTruthy();
  });

  it("chooses a full path that names a folder without waiting for Enter", async () => {
    // Someone who types a whole path and then clicks the host's button must
    // get that folder, not the one chosen before.
    const onSelect = await open();

    type("/home/ruben/webshop");

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop"), {
      timeout: 2000,
    });
    expect(api.searchFolders).not.toHaveBeenCalled();
  });

  it("opens a pasted path at once", async () => {
    const onSelect = await open();

    fireEvent.paste(field(), { clipboardData: { getData: () => '"/srv/deploy"' } });

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/srv/deploy"));
    expect(field().value).toBe("");
  });

  it("does not choose a typed path that is not a folder", async () => {
    // A typo — or a path that was never there — must not become the workspace.
    const onSelect = await open();

    type("webshop/nope");
    fireEvent.keyDown(field(), { key: "Enter" });

    expect(await screen.findByText(/no folder called/)).toBeTruthy();
    expect(onSelect).not.toHaveBeenCalled();
    // The text stays, so the typo can be corrected.
    expect(field().value).toBe("webshop/nope");
  });

  it("offers to create the folder when the last part does not exist yet", async () => {
    vi.mocked(api.createFolder).mockResolvedValue({
      folder: { name: "newshop", path: "/home/ruben/newshop", is_project: false, is_repo: false },
      error: null,
    });
    const onSelect = await open();

    type("/home/ruben/newshop");

    const offer = await screen.findByTestId("create-offer", {}, { timeout: 2000 });
    expect(offer.textContent).toContain("newshop");
    // Nothing is chosen until the folder exists, and Enter alone does not
    // create it: a typo must not leave a folder behind on the disk.
    expect(offer.getAttribute("aria-selected")).toBe("false");
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(offer);
    await waitFor(() =>
      expect(api.createFolder).toHaveBeenCalledWith({ parent: "/home/ruben", name: "newshop" }),
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/newshop"));
  });

  it("knows what can be the name of one new folder", () => {
    expect(isFolderName("newshop")).toBe(true);
    expect(isFolderName("my shop 2")).toBe(true);
    expect(isFolderName("..")).toBe(false);
    expect(isFolderName("a/b")).toBe(false);
    expect(isFolderName("what?")).toBe(false);
    expect(isFolderName("  ")).toBe(false);
  });
});

describe("a dropped folder", () => {
  it("is resolved through the backend", async () => {
    vi.mocked(api.resolveDroppedFolder).mockResolvedValue({
      resolved: "/home/ruben/webshop",
      candidates: [],
      detail: "",
    });
    const onSelect = await open();

    fireEvent.drop(screen.getByTestId("folder-drop-zone"), {
      dataTransfer: dataTransfer({ uriList: "file:///home/ruben/webshop" }),
    });

    await waitFor(() =>
      expect(api.resolveDroppedFolder).toHaveBeenCalledWith({
        path: "file:///home/ruben/webshop",
      }),
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/webshop"));
  });

  it("offers a choice when its name matches several folders", async () => {
    vi.mocked(api.resolveDroppedFolder).mockResolvedValue({
      resolved: null,
      candidates: [
        { name: "webshop", path: "/a/webshop", is_project: true, is_repo: true },
        { name: "webshop", path: "/b/webshop", is_project: true, is_repo: false },
      ],
      detail: 'Several folders are called "webshop" — pick the right one.',
    });
    await open();

    fireEvent.drop(screen.getByTestId("folder-drop-zone"), {
      dataTransfer: dataTransfer({ directoryName: "webshop" }),
    });

    expect(await screen.findByText(/pick the right one/i)).toBeTruthy();
    expect(await screen.findByText("/a/webshop")).toBeTruthy();
  });

  it("uses the real path the desktop shell reports instead of searching by name", async () => {
    // Inside the shell the host knows where the dropped folder lives and says
    // so a moment after the drop; the picker waits for that instead of asking
    // the backend to guess from the name.
    (window as unknown as { __JARVIS_EMBEDDED_DESKTOP?: boolean }).__JARVIS_EMBEDDED_DESKTOP =
      true;
    try {
      vi.mocked(api.resolveDroppedFolder).mockResolvedValue({
        resolved: "/home/x/Desktop/webshop",
        candidates: [],
        detail: "",
      });
      const onSelect = await open();

      fireEvent.drop(screen.getByTestId("folder-drop-zone"), {
        dataTransfer: dataTransfer({ directoryName: "webshop" }),
      });
      window.dispatchEvent(
        new CustomEvent("jarvis-native-drop", {
          detail: { paths: ["/home/x/Desktop/webshop"], names: ["webshop"] },
        }),
      );

      await waitFor(() =>
        expect(api.resolveDroppedFolder).toHaveBeenCalledWith({
          path: "/home/x/Desktop/webshop",
        }),
      );
      await waitFor(() =>
        expect(onSelect).toHaveBeenCalledWith("/home/x/Desktop/webshop"),
      );
    } finally {
      delete (window as unknown as { __JARVIS_EMBEDDED_DESKTOP?: boolean })
        .__JARVIS_EMBEDDED_DESKTOP;
    }
  });

  it("is refused plainly when the drop carried nothing usable", async () => {
    await open();

    fireEvent.drop(screen.getByTestId("folder-drop-zone"), {
      dataTransfer: dataTransfer({}),
    });

    expect(await screen.findByText(/was not a folder/i)).toBeTruthy();
    expect(api.resolveDroppedFolder).not.toHaveBeenCalled();
  });
});

describe("the system folder window", () => {
  it("is not offered where the machine cannot show one", async () => {
    // The default from the shared setup: a headless server, or a browser on a
    // different machine than the backend. Offering a button that cannot work
    // is worse than not offering one.
    await open();
    expect(screen.queryByTestId("native-browse")).toBeNull();
  });

  it("hands the chosen folder straight to the wizard", async () => {
    vi.mocked(api.fetchNativePickerSupport).mockResolvedValue({
      available: true,
      backend: "powershell",
    });
    vi.mocked(api.openNativePicker).mockResolvedValue({ path: "C:\\work\\shop" });
    const onSelect = await open();

    fireEvent.click(await screen.findByTestId("native-browse"));

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("C:\\work\\shop"));
    // And the in-page browser follows it there, so both views agree.
    expect(api.fetchFolders).toHaveBeenCalledWith("C:\\work\\shop", false);
  });

  it("says a window is waiting, because it can open behind the app", async () => {
    vi.mocked(api.fetchNativePickerSupport).mockResolvedValue({ available: true });
    let release: (value: { path: string }) => void = () => {};
    vi.mocked(api.openNativePicker).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    await open();

    fireEvent.click(await screen.findByTestId("native-browse"));

    expect(await screen.findByText(/folder window has opened/i)).toBeTruthy();
    await act(async () => {
      release({ path: "/home/ruben/webshop" });
    });
  });

  it("changes nothing when the window is closed without choosing", async () => {
    vi.mocked(api.fetchNativePickerSupport).mockResolvedValue({ available: true });
    vi.mocked(api.openNativePicker).mockResolvedValue({ cancelled: true });
    const onSelect = vi.fn();
    render(<FolderPicker selected="/already/here" onSelect={onSelect} />);

    fireEvent.click(await screen.findByTestId("native-browse"));

    await waitFor(() => expect(api.openNativePicker).toHaveBeenCalled());
    expect(onSelect).not.toHaveBeenCalled();
    // Cancelling is a decision, not a failure — nothing is reported.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens the window at the folder already chosen", async () => {
    vi.mocked(api.fetchNativePickerSupport).mockResolvedValue({ available: true });
    vi.mocked(api.openNativePicker).mockResolvedValue({ cancelled: true });
    render(<FolderPicker selected="/home/ruben/webshop" onSelect={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("native-browse"));

    await waitFor(() =>
      expect(api.openNativePicker).toHaveBeenCalledWith("/home/ruben/webshop"),
    );
  });
});

describe("a new folder", () => {
  it("is made in the folder on screen and becomes the selection", async () => {
    vi.mocked(api.createFolder).mockResolvedValue({
      folder: { name: "shop2", path: "/home/ruben/notes/shop2", is_project: false, is_repo: false },
      error: null,
    });
    const onSelect = await open();
    fireEvent.click(screen.getByText("notes"));

    fireEvent.click(screen.getByTestId("new-folder"));
    fireEvent.change(screen.getByTestId("new-folder-name"), { target: { value: "shop2" } });
    fireEvent.submit(screen.getByTestId("new-folder-form"));

    await waitFor(() =>
      expect(api.createFolder).toHaveBeenCalledWith({ parent: "/home/ruben/notes", name: "shop2" }),
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("/home/ruben/notes/shop2"));
  });

  it("goes into the home folder from the start view", async () => {
    vi.mocked(api.createFolder).mockResolvedValue({
      folder: { name: "fresh", path: "/home/ruben/fresh", is_project: false, is_repo: false },
      error: null,
    });
    await open();

    fireEvent.click(screen.getByTestId("new-folder"));
    fireEvent.change(screen.getByTestId("new-folder-name"), { target: { value: "fresh" } });
    fireEvent.submit(screen.getByTestId("new-folder-form"));

    await waitFor(() =>
      expect(api.createFolder).toHaveBeenCalledWith({ parent: null, name: "fresh" }),
    );
  });

  it("shows why it could not be made and keeps the name for correcting", async () => {
    vi.mocked(api.createFolder).mockResolvedValue({
      folder: null,
      error: "A folder name cannot contain slashes. Type just the name.",
    });
    const onSelect = await open();

    fireEvent.click(screen.getByTestId("new-folder"));
    fireEvent.change(screen.getByTestId("new-folder-name"), { target: { value: "a/b" } });
    fireEvent.submit(screen.getByTestId("new-folder-form"));

    expect(await screen.findByText(/cannot contain slashes/)).toBeTruthy();
    expect((screen.getByTestId("new-folder-name") as HTMLInputElement).value).toBe("a/b");
    expect(onSelect).not.toHaveBeenCalled();
    // Its own Escape closes the name field, not the dialog around it.
    expect(screen.getByTestId("new-folder-name").closest("[data-escape-local]")).toBeTruthy();
  });
});

describe("the address bar", () => {
  it("splits a path into crumbs that keep their root", () => {
    expect(pathCrumbs("C:\\Users\\me")).toEqual([
      { label: "C:", path: "C:\\" },
      { label: "Users", path: "C:\\Users" },
      { label: "me", path: "C:\\Users\\me" },
    ]);
    expect(pathCrumbs("/home/ruben")).toEqual([
      { label: "/", path: "/" },
      { label: "home", path: "/home" },
      { label: "ruben", path: "/home/ruben" },
    ]);
    // A server alone is not a folder anyone can open: the share is the root.
    expect(pathCrumbs("\\\\server\\share\\dir")).toEqual([
      { label: "\\\\server\\share", path: "\\\\server\\share" },
      { label: "dir", path: "\\\\server\\share\\dir" },
    ]);
    expect(leafName("C:\\Users\\me\\")).toBe("me");
    expect(leafName("/")).toBe("/");
  });

  it("knows the folder above from the path alone", () => {
    expect(parentPath("C:\\Users\\me")).toBe("C:\\Users");
    expect(parentPath("C:\\Users")).toBe("C:\\");
    expect(parentPath("C:\\")).toBeNull();
    expect(parentPath("/home")).toBe("/");
    expect(parentPath("/")).toBeNull();
    expect(parentPath("\\\\server\\share\\dir")).toBe("\\\\server\\share");
  });

  it("folds the middle of a long path into one crumb that still leads somewhere", () => {
    const folded = foldCrumbs(pathCrumbs("C:\\a\\b\\c\\d\\e"));
    expect(folded.map((crumb) => crumb.label)).toEqual(["C:", "…", "d", "e"]);
    // The folded crumb opens the last folder it hides.
    expect(folded[1]).toMatchObject({ path: "C:\\a\\b\\c", folded: true });
    expect(foldCrumbs(pathCrumbs("C:\\a\\b"))).toHaveLength(3);
  });
});

describe("the chosen folder", () => {
  it("is named under the list", async () => {
    render(<FolderPicker selected="/home/ruben/webshop" onSelect={vi.fn()} />);
    const strip = await screen.findByTestId("folder-selection");
    expect(strip.textContent).toContain("webshop");
    expect(strip.textContent).toContain("/home/ruben/webshop");
  });

  it("says plainly when nothing is chosen yet", async () => {
    render(<FolderPicker selected={null} onSelect={vi.fn()} />);
    expect((await screen.findByTestId("folder-selection")).textContent).toMatch(
      /no folder chosen/i,
    );
  });

  it("is left to a host that reports it itself", async () => {
    render(<FolderPicker selected="/x" onSelect={vi.fn()} showSelection={false} />);
    await screen.findByText("webshop");
    expect(screen.queryByTestId("folder-selection")).toBeNull();
  });
});
