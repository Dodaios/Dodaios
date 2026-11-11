import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  Sidebar,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_RAIL_AT_WIDTH,
  SIDEBAR_RAIL_WIDTH,
} from "@/components/layout/Sidebar";
import { LISTED_NAV_GROUPS, NAV_FOOTER_ITEMS, SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { HUB_GROUPS } from "@/views/settings/hubNav";
import { isSectionId, useEventStore } from "@/store/events";
import { useQuickSwitcher } from "@/store/quickSwitcher";
import { useQuickSwitchSettings } from "@/store/quickSwitchSettings";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useStatusLightStore } from "@/components/layout/statusLightStore";
import { sectionPrefetch } from "@/lib/sectionPrefetch";
import { SECTION_PREFETCH_DELAY_MS } from "@/hooks/useSectionPrefetch";

test.each([SIDEBAR_DEFAULT_WIDTH, SIDEBAR_RAIL_WIDTH])(
  "sidebar intent warms a destination without navigating (width=%s)",
  (width) => {
    vi.useFakeTimers();
    const warm = vi.spyOn(sectionPrefetch, "prefetch").mockResolvedValue();
    try {
      useEventStore.setState({ activeSection: "chats" });
      renderSidebar(width);
      expect(warm).not.toHaveBeenCalled();
      fireEvent.focus(screen.getByTestId("sidebar-profile-toggle"));
      act(() => { vi.advanceTimersByTime(SECTION_PREFETCH_DELAY_MS); });
      expect(warm).toHaveBeenCalledExactlyOnceWith("profile");
      expect(useEventStore.getState().activeSection).toBe("chats");
    } finally {
      cleanup();
      warm.mockRestore();
      vi.useRealTimers();
    }
  },
);

test("IDE rail keeps workspace options and Dodaios Live reachable", () => {
  act(() => {
    useEventStore.setState({ activeSection: "agentic-ide" });
    useIdeProjectsStore.setState({ activeWorkspaceId: null, action: null });
  });
  renderSidebar(SIDEBAR_RAIL_WIDTH);
  expect(screen.queryByTestId("ide-project-tree")).toBeNull();
  const options = screen.getByRole("button", { name: "Workspace options" }) as HTMLButtonElement;
  expect(options.disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Dodaios Live" }));
  expect(useIdeProjectsStore.getState().action?.kind).toBe("toggle-voice");
  act(() => useIdeProjectsStore.setState({ activeWorkspaceId: "w1" }));
  expect(options.disabled).toBe(false);
  fireEvent.click(options);
  expect(useIdeProjectsStore.getState().action).toMatchObject({ kind: "workspace-options", workspaceId: "w1" });
  cleanup();
});

test("the IDE lists its folders; beside the conversation the column stays empty", async () => {
  act(() => {
    useIdeThreadsStore.setState({ layout: "grid" });
    useEventStore.setState({ activeSection: "agentic-ide" });
  });
  try {
    renderSidebar();
    // The project tree is a lazy chunk: a cold CI runner can take longer than the default second to load it.
    expect(await screen.findByTestId("ide-project-tree", undefined, { timeout: 10_000 })).toBeDefined();
    // The IDE's column opens with how it reads; the place itself is picked in the caption.
    expect(screen.getByTestId("ide-layout-switch")).toBeTruthy();
    expect(screen.queryByTestId("surface-switch")).toBeNull();
    act(() => useEventStore.setState({ activeSection: "chats" }));
    // Beside the conversation nothing is listed: the assistant's own panel
    // stands to the right of the conversation (views/HomeView).
    expect(screen.queryByTestId("ide-project-tree")).toBeNull();
    expect(screen.queryByTestId("assistant-panel")).toBeNull();
    expect(screen.queryByTestId("earlier-chats")).toBeNull();
    expect(screen.queryByTestId("ide-layout-switch")).toBeNull();
  } finally {
    // A failure here must not leave the IDE section and its sidebar behind for the next test.
    cleanup();
    act(() => useEventStore.setState({ activeSection: "chats" }));
  }
}, 30_000);

// The sidebar header avatar must mirror the chosen on-screen display style:
// the ghost mascot ONLY when the user explicitly picked "mascot"; the slim bar
// for "jarvis_bar"/"none" and while the style is still loading (config null).
// Mock the overlay-style hook so the test controls the style without a fetch.
const overlayMock = vi.hoisted(() => ({ style: "jarvis_bar" as string | null }));
vi.mock("@/hooks/useOverlayStyle", () => ({
  useOverlayStyle: () => ({
    config: overlayMock.style
      ? { style: overlayMock.style, options: ["jarvis_bar", "mascot", "none"] }
      : null,
    loading: false,
    error: null,
    refetch: () => {},
    saveStyle: () => {},
  }),
}));

// usePluginAttention polls /api/marketplace/plugins; mock it so the sidebar's
// plugin reconnect dot is driven by the test, not a fetch.
const pluginAttentionMock = vi.hoisted(() => ({ needsReconnect: false }));
vi.mock("@/hooks/usePluginAttention", () => ({
  usePluginAttention: () =>
    pluginAttentionMock.needsReconnect
      ? { count: 1, names: ["Cloudflare"] }
      : { count: 0, names: [] },
}));

// useVoiceMode fetches /api/settings/voice-mode; mock it so the footer card's
// pipeline-vs-realtime split is driven by the test, not a fetch. The default
// mirrors a fresh pipeline install (the pre-existing footer tests rely on it).
const voiceModeMock = vi.hoisted(() => ({
  value: {
    mode: "pipeline",
    activeProvider: null as string | null,
    activeProviderLabel: null as string | null,
    activeModel: null as string | null,
    sessionActive: false,
    activeSessionMode: null as "pipeline" | "realtime" | null,
    activeSessionProvider: "",
    activeSessionModel: "",
  },
}));
vi.mock("@/hooks/useVoiceMode", () => ({
  useVoiceMode: () => voiceModeMock.value,
}));

function renderSidebar(width?: number) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <Sidebar width={width} />
    </QueryClientProvider>,
  );
}

describe("Sidebar voice header", () => {
  beforeEach(() => {
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
    });
  });

  afterEach(() => {
    cleanup();
  });

  test("does not render the floating mascot bubble while listening", () => {
    // The mascot's listening speech-bubble is anchored to the left of the
    // mascot (right: calc(100% + 10px)). In the sidebar the mascot sits flush
    // against the window edge, so the bubble slides off-screen and only its
    // yellow border + glow bleed back in — the spurious "yellow frame" the
    // user reported. The sidebar must not render that bubble.
    useEventStore.setState({
      voiceState: "listening",
      transcription: "auflegen",
      transcriptionFinal: false,
    });

    const { container } = renderSidebar();

    expect(container.querySelector(".gigi-bubble-listening")).toBeNull();
    expect(container.querySelector(".gigi-bubble")).toBeNull();
  });

  test("no longer shows the live transcription — that lane moved to the voice stage", () => {
    // Since 2026-08-23 the transcript is read on the front page itself
    // (components/home/VoiceStage), where it has the room to be read; the
    // sidebar box would be a second, cramped copy of the same words.
    useEventStore.setState({
      voiceState: "listening",
      transcription: "auflegen",
      transcriptionFinal: false,
    });

    renderSidebar();

    expect(screen.queryByText("auflegen")).toBeNull();
  });

  test("carries no place switch and no duplicate voice controls", () => {
    // Dodaios or IDE is picked in the window caption (AppSurfaceSwitch).
    renderSidebar();
    expect(screen.queryByTestId("home-surface-switch")).toBeNull();
    expect(screen.queryByTestId("surface-switch")).toBeNull();
    expect(screen.queryByTestId("sidebar-mode-switch")).toBeNull();
  });
});

describe("Sidebar settings-hub entry", () => {
  beforeEach(() => {
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
      voiceReady: true,
      activeSection: "chats",
    });
  });

  afterEach(() => {
    cleanup();
  });

  test("the profile button opens the hub on the Profile tab", () => {
    // The popup is gone: one click lands in the Settings hub, on Profile.
    renderSidebar();

    fireEvent.click(screen.getByTestId("sidebar-profile-toggle"));

    expect(useEventStore.getState().activeSection).toBe("profile");
  });

  test("the profile button stays lit while any hub section is on screen", () => {
    // It IS the hub's entry point, so it carries "you are here" for all of
    // the hub's sections — including ones only reachable from inside the hub.
    useEventStore.setState({ activeSection: "appshots" });
    renderSidebar();

    expect(screen.getByTestId("sidebar-profile-toggle").className).toMatch(
      /jarvis-nav-active/,
    );
  });

  test("the profile button is calm on non-hub sections", () => {
    useEventStore.setState({ activeSection: "board" });
    renderSidebar();

    expect(screen.getByTestId("sidebar-profile-toggle").className).not.toMatch(
      /jarvis-nav-active/,
    );
  });

  test("opens no popup — the hub is the only destination", () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId("sidebar-profile-toggle"));

    expect(screen.queryByTestId("sidebar-profile-panel")).toBeNull();
    expect(screen.queryByTestId("sidebar-brain-card")).toBeNull();
  });
});

describe("Sidebar assistant name header", () => {
  beforeEach(() => {
    // The field stands atop the IDE's workspace list; beside the
    // conversation search is one of the shortcut rows instead.
    useIdeThreadsStore.setState({ layout: "grid" });
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
      voiceReady: true,
      activeSection: "agentic-ide",
    });
  });

  afterEach(() => {
    cleanup();
  });

  test("renders the resolved assistant name (not a hardcoded 'Jarvis')", () => {
    // The header wordmark must follow the configured assistant name so a user
    // who renames the assistant (e.g. to "Ruben") never sees a stale "Jarvis".
    useEventStore.setState({ assistantName: "Ruben" });

    renderSidebar();

    // The name lives in the search bar's accessible name now.
    const bar = screen.getByTestId("sidebar-search");
    expect(bar.getAttribute("aria-label")).toContain("Ruben");
    expect(bar.getAttribute("aria-label")).not.toContain("Jarvis");
  });

  test("follows a live assistant-name change", () => {
    useEventStore.setState({ assistantName: "Nova" });
    renderSidebar();
    const bar = () => screen.getByTestId("sidebar-search").getAttribute("aria-label") ?? "";
    expect(bar()).toContain("Nova");

    act(() => {
      useEventStore.setState({ assistantName: "Athena" });
    });

    expect(bar()).toContain("Athena");
    expect(bar()).not.toContain("Nova");
  });

  test("the search bar is a field you type into, not a door to a window", () => {
    renderSidebar();
    const bar = screen.getByTestId("sidebar-search") as HTMLInputElement;
    fireEvent.change(bar, { target: { value: "agen" } });
    expect(bar.value).toBe("agen");
    // Typing here never opens the Spotlight window in the middle.
    expect(useQuickSwitcher.getState().open).toBe(false);
  });

  test("switching the quick switcher off takes the field away", () => {
    useQuickSwitchSettings.setState({ enabled: false });
    renderSidebar();
    expect(screen.queryByTestId("sidebar-search")).toBeNull();
    useQuickSwitchSettings.setState({ enabled: true });
  });
});

describe("Sidebar plugin reconnect indicator", () => {
  beforeEach(() => {
    useEventStore.setState({ connected: true, voiceReady: true });
  });

  afterEach(() => {
    cleanup();
    pluginAttentionMock.needsReconnect = false;
  });

  test("marks the profile button when a plugin needs reconnect", () => {
    // A revoked / expired plugin must be visible app-wide, not only on the
    // Plugins page. Plugins are reached through Settings, so the button that
    // leads there carries the amber dot and names the plugin.
    pluginAttentionMock.needsReconnect = true;

    renderSidebar();

    const dot = screen.getByTestId("sidebar-profile-attention");
    expect(dot.getAttribute("aria-label")).toContain("Cloudflare");
    expect(dot.className).toContain("bg-warning");
  });

  test("no dot when every plugin is healthy", () => {
    pluginAttentionMock.needsReconnect = false;

    renderSidebar();

    expect(screen.queryByTestId("sidebar-profile-attention")).toBeNull();
  });
});

describe("Sidebar voice-boot indicator", () => {
  beforeEach(() => {
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
      voiceReady: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  test("shows a 'Voice starting…' spinner while connected but voice not ready", () => {
    // The window connects in ~1s but the voice feature warms up ~20s in the
    // background. During that gap the header must signal "starting", not the
    // normal idle "Ready" state (which would imply the mic already works).
    useEventStore.setState({ connected: true, voiceReady: false });

    renderSidebar();

    // The spinner itself is drawn in the caption's Dodaios switch (AppSurfaceSwitch.test).
    expect(screen.getByText("Voice starting…")).toBeTruthy();
    // The normal idle voice label must NOT be shown during warmup.
    expect(screen.queryByText("Ready")).toBeNull();
  });

  test("reverts to the normal voice state once voice is ready", () => {
    useEventStore.setState({ connected: true, voiceReady: true, voiceState: "idle" });

    renderSidebar();

    // At rest the caption's dot alone says "fine"; no line of text here.
    expect(screen.queryByText("Ready")).toBeNull();
    expect(screen.queryByText("Voice starting…")).toBeNull();
    expect(screen.queryByTestId("sidebar-voice-label")).toBeNull();
  });

  test("shows 'Offline' (not the spinner) when disconnected and NOT warming", () => {
    // Truly offline: no live socket AND the WS is not in the fast-boot warming
    // loop (no 1013) — the honest state is Offline.
    useEventStore.setState({ connected: false, voiceReady: false, wsWarming: false });

    renderSidebar();

    expect(screen.getByText("Offline")).toBeTruthy();
    expect(screen.queryByText("Voice starting…")).toBeNull();
  });

  test("shows the booting label + spinner (not Offline) while warming", () => {
    // Disconnected but the fast-boot bootstrap keeps closing the WS with 1013:
    // the backend is still starting, so the honest state is "Starting…", not
    // the alarming "Offline".
    useEventStore.setState({ connected: false, voiceReady: false, wsWarming: true });

    renderSidebar();

    expect(screen.getByText("Starting…")).toBeTruthy();
    expect(screen.queryByText("Offline")).toBeNull();
  });
});

/*
 * The icon rail — what the sidebar becomes when it is dragged in.
 *
 * The seam used to stop at 200 px, which is still wide enough to read every
 * label; in the Agentic IDE that meant a fifth of the window stayed spent on a
 * nav list nobody was reading while a dozen terminals fought over the rest. Two
 * things have to hold for the rail to be a sidebar rather than a broken one:
 * every destination is still REACHABLE, and every icon still SAYS what it is.
 * A refactor that quietly drops either turns the rail into a column of mystery
 * glyphs, and nothing else on screen would look wrong.
 *
 * Anchored on the row's test id rather than its text: the label is translated,
 * so asserting on it would make these pass or fail with the active locale.
 */
describe("Sidebar icon rail", () => {
  beforeEach(() => {
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
      activeSection: "agentic-ide",
    });
    useIdeThreadsStore.setState({ layout: "threads" });
  });

  afterEach(() => {
    cleanup();
    act(() => useEventStore.setState({ activeSection: "chats" }));
  });

  test("shows its labels at the designed width", () => {
    renderSidebar(SIDEBAR_DEFAULT_WIDTH);

    expect(screen.getByTestId("sidebar").dataset.railed).toBe("false");
    expect(screen.getByTestId("ide-layout-threads").textContent).toContain("Chat");
    expect(screen.getByTestId("ide-layout-grid").textContent).toContain("Grid");
  });

  test("drops to icons once dragged past the snap point", () => {
    renderSidebar(SIDEBAR_RAIL_AT_WIDTH - 1);

    const aside = screen.getByTestId("sidebar");
    expect(aside.dataset.railed).toBe("true");
    // Snapped, not clipped: the band between the rail and a readable sidebar
    // shows half a word per row and reads as a rendering fault, so it is
    // skipped rather than rendered at the dragged width.
    expect(aside.style.width).toBe(`${SIDEBAR_RAIL_WIDTH}px`);
    expect(screen.getByTestId("ide-layout-grid").textContent).toBe("");
  });

  test("keeps both faces named once their labels are off the screen", () => {
    renderSidebar(SIDEBAR_RAIL_WIDTH);

    for (const id of ["ide-layout-threads", "ide-layout-grid"]) {
      const half = screen.getByTestId(id);
      expect(half.getAttribute("aria-label")).toBeTruthy();
      expect(half.getAttribute("title")).toBe(half.getAttribute("aria-label"));
    }
  });

  test("still switches face on a click", () => {
    renderSidebar(SIDEBAR_RAIL_WIDTH);

    act(() => {
      screen.getByTestId("ide-layout-grid").click();
    });

    expect(useIdeThreadsStore.getState().layout).toBe("grid");
  });

  test("keeps the rail canvas transparent and lists no folders", () => {
    renderSidebar(SIDEBAR_RAIL_WIDTH);

    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.querySelector(".jarvis-shell-surface")).toBeNull();
    expect(screen.getByTestId("ide-layout-switch")).toBeTruthy();
    expect(screen.queryByTestId("earlier-chats")).toBeNull();
  });

  test("keeps the wake-word hint and realtime control off the rail", () => {
    // Both are label-shaped controls that cannot say anything useful in 64 px.
    // They step aside rather than being clipped into unreadable stubs.
    useEventStore.setState({
      voiceState: "listening",
      transcription: "auflegen",
      transcriptionFinal: false,
    });

    renderSidebar(SIDEBAR_RAIL_WIDTH);

    expect(screen.queryByText("auflegen")).toBeNull();
    expect(screen.queryByTestId("sidebar-voice-label")).toBeNull();
    // …and the switch, which is the reason the rail exists, is still there.
    expect(screen.getByTestId("ide-layout-switch")).toBeTruthy();
  });
});

/**
 * The collapse state (the toggle itself moved to the window caption).
 *
 * The sidebar header no longer carries its own button — it lives in the
 * caption's leading navigation (SectionNavButtons, owned by TopBar), beside
 * back/forward, so the controls sit in the empty caption corner on every
 * section. The collapsed STATE still belongs to the sidebar: the rail wins
 * while it holds, and the drag stays as the finer way in.
 */
describe("Sidebar collapse state", () => {
  // The IDE's column is the one with two faces; beside the conversation it is always the rail.
  beforeEach(() => {
    useEventStore.setState({ activeSection: "agentic-ide", connected: true });
    useIdeThreadsStore.setState({ layout: "grid" });
  });

  afterEach(() => {
    cleanup();
    act(() => useEventStore.setState({ activeSection: "chats" }));
  });

  function renderCollapsed(collapsed: boolean) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={client}>
        <Sidebar
          width={SIDEBAR_DEFAULT_WIDTH}
          collapsed={collapsed}
        />
      </QueryClientProvider>,
    );
  }

  test("collapses to the rail even at a wide dragged width", () => {
    renderCollapsed(true);

    const aside = screen.getByTestId("sidebar");
    // The collapse is a STATE, not a width: the dragged 280 px is remembered
    // for the expand, and the rail wins while collapsed.
    expect(aside.dataset.railed).toBe("true");
    expect(aside.style.width).toBe(`${SIDEBAR_RAIL_WIDTH}px`);
  });

  test("expands to the dragged width once the state lifts", () => {
    const { rerender } = renderCollapsed(true);
    expect(screen.getByTestId("sidebar").dataset.railed).toBe("true");

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    rerender(
      <QueryClientProvider client={client}>
        <Sidebar
          width={SIDEBAR_DEFAULT_WIDTH}
          collapsed={false}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("sidebar").dataset.railed).toBe("false");
  });

  test("beside the conversation the column is the rail at any width", () => {
    act(() => useEventStore.setState({ activeSection: "chats" }));
    renderCollapsed(false);

    const aside = screen.getByTestId("sidebar");
    expect(aside.dataset.railed).toBe("true");
    expect(aside.style.width).toBe(`${SIDEBAR_RAIL_WIDTH}px`);
    expect(screen.getByTestId("nav-rail")).toBeTruthy();
    // No line of text: the person's name is the button's hover bubble.
    expect(screen.queryByTestId("sidebar-profile-name")).toBeNull();
  });

  test("carries no toggle of its own — the caption owns it", () => {
    // The header button moved to the caption's leading navigation
    // (SectionNavButtons): a sidebar that flipped its own state would drift
    // from the shell that owns the width beside it.
    renderCollapsed(false);

    expect(screen.queryByTestId("sidebar-collapse-toggle")).toBeNull();
    expect(screen.getByTestId("sidebar")).toBeTruthy();
  });
});

describe("the sidebar holds the two places and nothing else", () => {
  beforeEach(() => {
    useEventStore.setState({ activeSection: "chats", connected: true });
    useIdeChatStore.setState({ workspaces: [], view: "chat" });
  });
  afterEach(() => cleanup());

  test("lists no sections of its own", () => {
    renderSidebar();
    for (const id of ["agents", "dictation", "visualization", "agentic-ide", "plugins", "memory", "self-build", "verse"]) {
      expect(screen.queryByTestId(`nav-row-${id}`)).toBeNull();
    }
    expect(screen.queryByTestId("sidebar-more-toggle")).toBeNull();
    expect(screen.queryByTestId("sidebar-due")).toBeNull();
    expect(screen.queryByTestId("earlier-chats")).toBeNull();
  });

  test("offers the conversation, search and the four pages reached most, in the maintainer's order", () => {
    renderSidebar();
    const rows = ["sidebar-shortcut-chats", "sidebar-search-row", "sidebar-shortcut-plugins", "sidebar-shortcut-dictation", "sidebar-shortcut-visualization", "sidebar-shortcut-appshots"]
      .map((id) => screen.getByTestId(id));
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i - 1].compareDocumentPosition(rows[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // Icons only: each says its name to a screen reader, none prints it.
    for (const row of rows) {
      expect(row.getAttribute("aria-label")).toBeTruthy();
      expect(row.textContent).toBe("");
    }
    expect(rows[0].getAttribute("aria-current")).toBe("page");
    expect(screen.queryByTestId("sidebar-search")).toBeNull();
    fireEvent.click(screen.getByTestId("sidebar-search-row"));
    expect(useQuickSwitcher.getState().open).toBe(true);
    act(() => useQuickSwitcher.getState().hide());
    fireEvent.click(screen.getByTestId("sidebar-shortcut-appshots"));
    expect(useEventStore.getState().activeSection).toBe("appshots");
    fireEvent.click(screen.getByTestId("sidebar-shortcut-chats"));
    expect(useEventStore.getState().activeSection).toBe("chats");
  });

  test("shows what waits on the person as a tile, with no list and no heading", () => {
    renderSidebar();
    expect(screen.queryByTestId("rail-events")).toBeNull();
    act(() => useStatusLightStore.setState({ light: {
      counts: { running: 0, needs_you: 1 }, running: [], trouble: [], findings: [], tone: "calm",
      needs_you: [{ kind: "approval", id: "a1", title: "Write the July manifest", state: "waiting", link: { section: "board" } }],
    } }));
    const tile = screen.getByTestId("rail-event");
    expect(tile.dataset.tone).toBe("needs");
    expect(tile.getAttribute("aria-label")).toContain("Write the July manifest");
    // The old list and its "Needs you" heading are gone from the column.
    expect(screen.queryByTestId("sidebar-status")).toBeNull();
    expect(screen.getByTestId("sidebar").textContent).not.toContain("Needs you");
    fireEvent.click(tile);
    expect(useEventStore.getState().activeSection).toBe("board");
    act(() => useStatusLightStore.setState({ light: null }));
  });

  test("a failing provider reads as its name and what is wrong, and opens the API keys", () => {
    renderSidebar();
    act(() => useStatusLightStore.setState({ light: {
      counts: { running: 0, needs_you: 0 }, running: [], needs_you: [], trouble: [], tone: "warn",
      findings: [{
        id: "seat_failure:openai-live-subscription:realtime:model_unavailable", kind: "seat_failure",
        title: "openai-live-subscription (realtime) is failing: model_unavailable",
        provider: "OpenAI GPT-Live (ChatGPT subscription)", modality: "realtime", status: "model_unavailable",
      }],
    } }));
    const row = screen.getByTestId("rail-event");
    expect(row.dataset.tone).toBe("trouble");
    const name = row.getAttribute("aria-label") ?? "";
    expect(name).toContain("OpenAI GPT-Live");
    expect(name).toContain("model not available · ChatGPT subscription");
    expect(name).not.toContain("model_unavailable");
    fireEvent.click(row);
    expect(useEventStore.getState().activeSection).toBe("apikeys");
    act(() => useStatusLightStore.setState({ light: null }));
  });

  test("keeps the marketplace beside the profile button", () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId("nav-row-marketplace"));
    expect(useEventStore.getState().activeSection).toBe("marketplace");
  });

  test("the profile button opens the hub — hub tabs are the hub's own tests", () => {
    // No popup anymore: entries like Spend live in the hub's left nav
    // (see SettingsHubView.test), so one click on the profile button is the
    // whole interaction and it lands on the Profile tab.
    renderSidebar();
    fireEvent.click(screen.getByTestId("sidebar-profile-toggle"));
    expect(useEventStore.getState().activeSection).toBe("profile");
    expect(screen.queryByTestId("sidebar-profile-panel")).toBeNull();
  });

  test("every listed destination remains reachable", () => {
    renderSidebar();
    const hubLinks = new Set<string>(
      HUB_GROUPS.flatMap((group) => group.entries).flatMap((entry) => (entry.kind === "link" ? [entry.id] : [])),
    );
    for (const item of [...LISTED_NAV_GROUPS.flat(), ...NAV_FOOTER_ITEMS]) {
      // Hub tabs are one profile-button click away; the hub selects them itself.
      if ((SETTINGS_HUB_IDS as readonly string[]).includes(item.id)) continue;
      // The two places are the caption's switch (AppSurfaceSwitch.test).
      if (item.id === "chats" || item.id === "agentic-ide") continue;
      // Every other page is a link inside the Settings hub.
      else expect(hubLinks.has(item.id), item.id).toBe(true);
    }
    // And every hub id is still a valid section id — an id the hub lists
    // that stops resolving strands deep links, the deck and voice commands.
    for (const id of SETTINGS_HUB_IDS) {
      expect(isSectionId(id)).toBe(true);
    }
  });
});
