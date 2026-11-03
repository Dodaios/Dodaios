import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetLauncherImportForTests, VerseLauncherCard } from "../VerseLauncherCard";
import { VerseSettingsGroup } from "../VerseSettingsGroup";
import { formatBytes, parseInstall } from "../verseHostApi";

const notInstalled = { status: "not_installed", state: null, pid: null, vram_mb: null, fps: null, crash_report: null };
const stopped = { ...notInstalled, status: "stopped" };
const idle = {
  state: "idle", done_bytes: 0, total_bytes: 0, version: "5.0.0", installed_version: null,
  download_bytes: 7_400_000_000, install_bytes: 10_300_000_000, error: null, bytes_per_s: null,
};

type Handler = (init?: RequestInit) => unknown;

function server(routes: Record<string, Handler>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    const handler = routes[key];
    if (!handler) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(handler(init)), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

describe("install helpers", () => {
  it("formats sizes and reads an unknown state as unavailable", () => {
    expect(formatBytes(7_400_000_000)).toBe("7.4 GB");
    expect(formatBytes(820_000_000)).toBe("820 MB");
    expect(parseInstall({ state: "weird" }).state).toBe("unavailable");
    expect(parseInstall(idle)).toEqual(idle);
  });
});

describe("launcher card download", () => {
  beforeEach(() => resetLauncherImportForTests());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the size, downloads with progress and cancel, then hands back to the card", async () => {
    let status: unknown = notInstalled;
    let progress: Record<string, unknown> = idle;
    let finish = false;
    const fetchMock = server({
      "GET /api/verse/status": () => status,
      "POST /api/verse/settings/import": () => ({ imported: [] }),
      "GET /api/verse/install/progress": () => progress,
      "POST /api/verse/install": () => {
        progress = finish
          ? { ...idle, state: "installed", installed_version: "5.0.0" }
          : { ...idle, state: "downloading", done_bytes: 1_850_000_000, total_bytes: 7_400_000_000 };
        return progress;
      },
      "DELETE /api/verse/install": () => {
        progress = { ...idle, state: "cancelled", done_bytes: 1_850_000_000, total_bytes: 7_400_000_000 };
        return { cancelled: true, removed: false, ...progress };
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VerseLauncherCard />);
    expect((await screen.findByTestId("verse-install-size")).textContent).toContain("7.4 GB");
    fireEvent.click(screen.getByText("Download the Verse"));
    expect((await screen.findByTestId("verse-install-progress")).textContent).toBe("Downloading… 1.9 GB of 7.4 GB");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("25");
    fireEvent.click(screen.getByText("Cancel"));
    await screen.findByText("Continue the download");
    expect(fetchMock.mock.calls.some(([u, i]) => String(u) === "/api/verse/install" && i?.method === "DELETE")).toBe(true);

    finish = true;
    status = stopped;
    fireEvent.click(screen.getByText("Continue the download"));
    await screen.findByText("Ready to start.");
    expect(screen.queryByTestId("verse-install")).toBeNull();
  });

  it("says when no download is published yet", async () => {
    vi.stubGlobal("fetch", server({
      "GET /api/verse/status": () => notInstalled,
      "POST /api/verse/settings/import": () => ({ imported: [] }),
      "GET /api/verse/install/progress": () => ({ ...idle, state: "unavailable", version: null, download_bytes: null }),
    }));
    render(<VerseLauncherCard />);
    await screen.findByTestId("verse-install-unavailable");
    expect(screen.queryByText("Download the Verse")).toBeNull();
  });
});

describe("Settings: Remove the Verse", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("removes an installed Verse after a confirm", async () => {
    let progress: Record<string, unknown> = { ...idle, installed_version: "5.0.0" };
    const fetchMock = server({
      "GET /api/verse/flags": () => ({ unreal_preview: false, dev_bridge: false }),
      "GET /api/verse/install/progress": () => progress,
      "DELETE /api/verse/install": () => {
        progress = { ...idle };
        return { cancelled: false, removed: true, ...progress };
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VerseSettingsGroup />);
    await screen.findByText(/Installed, version 5.0.0 · 10.3 GB/);
    fireEvent.click(screen.getByRole("button", { name: "Remove the Verse" }));
    const confirm = await screen.findByTestId("verse-settings-confirm");
    fireEvent.click(confirm.querySelector("button:last-child") as HTMLButtonElement);
    await screen.findByText("Not installed. Download it from the Verse view.");
    expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "DELETE")).toHaveLength(1);
  });

  it("stays hidden with no Verse installed and the preview off", async () => {
    const fetchMock = server({
      "GET /api/verse/flags": () => ({ unreal_preview: false }),
      "GET /api/verse/install/progress": () => idle,
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<VerseSettingsGroup />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(container.textContent).toBe("");
  });
});
