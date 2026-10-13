import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { loadLocaleChunk, useT } from "@/i18n";
import { buildOfficeLayout, type OfficeLayout, type Studio } from "./officeLayout";
import { useOfficeStore } from "./officeStore";
import { ControlHints, OfficeTools, StationPrompt, stationAction, stationLabel } from "./OfficeHud";
import { stationsFor } from "./stations";
import { DEFAULT_OFFICE_SETTINGS, loadOfficeSettings, useOfficeSettings } from "./officeSettings";

const layout = buildOfficeLayout([
  { agentId: "a1", name: "Ada", tier: "specialist", providerLabel: "Codex", state: "idle", createdMs: 1 },
]);

beforeAll(async () => { await loadLocaleChunk("society"); });
beforeEach(() => {
  localStorage.clear();
  useOfficeStore.setState({ selection: null, hover: null, walkTo: null });
  useOfficeSettings.setState({ ...DEFAULT_OFFICE_SETTINGS });
});
afterEach(cleanup);

function tools(overrides: Partial<Parameters<typeof OfficeTools>[0]> = {}) {
  const props = {
    layout, follow: false, onFollow: vi.fn(), onOverview: vi.fn(), helpOpen: false, onHelp: vi.fn(),
    list: { label: "Agents list", ide: false, onOpen: vi.fn() }, ...overrides,
  };
  render(<OfficeTools {...props} />);
  return props;
}

describe("office toolbar", () => {
  test("is a handful of named icon buttons, each doing its one thing", () => {
    const props = tools();
    const bar = screen.getByRole("toolbar", { name: "Map tools" });
    expect(within(bar).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Follow me", "Overview", "Places", "Agents list", "Help & settings",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Follow me" }));
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    fireEvent.click(screen.getByRole("button", { name: "Agents list" }));
    fireEvent.click(screen.getByRole("button", { name: "Help & settings" }));
    expect(props.onFollow).toHaveBeenCalledOnce();
    expect(props.onOverview).toHaveBeenCalledOnce();
    expect(props.list?.onOpen).toHaveBeenCalledOnce();
    expect(props.onHelp).toHaveBeenCalledOnce();
    // The help key is announced, and shown in the button's label on hover.
    const help = screen.getByRole("button", { name: "Help & settings" });
    expect(help.getAttribute("aria-keyshortcuts")).toBe("H");
    expect(help.dataset.tip).toBe("Help & settings (H)");
  });

  test("shows what is on: following, the open directory; and no list on a floor without one", () => {
    tools({ follow: true, helpOpen: true, list: null });
    expect(screen.getByRole("button", { name: "Follow me" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Help & settings" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: "Agents list" })).toBeNull();
  });

  test("the places menu reaches every station by keyboard: open one, or walk there", () => {
    tools();
    const trigger = screen.getByRole("button", { name: "Places" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("group", { name: "Places" });
    // One "open" and one "walk there" button per station of the floor, the reception among them.
    expect(within(menu).getAllByRole("button")).toHaveLength(stationsFor(layout).length * 2);
    expect(within(menu).getByRole("button", { name: "Reception: Open the directory" })).toBeTruthy();

    // Resting on a place lights its object in the world.
    const open = within(menu).getByRole("button", { name: "Team room: Manage teams" });
    fireEvent.focus(open);
    expect(useOfficeStore.getState().hover).toEqual({ kind: "checkpoint", id: "team" });
    fireEvent.click(open);
    expect(useOfficeStore.getState().selection).toEqual({ kind: "checkpoint", id: "team" });
    expect(useOfficeStore.getState().hover).toBeNull();
    expect(screen.queryByRole("group", { name: "Places" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Places" }));
    fireEvent.click(screen.getByRole("button", { name: "Walk to Wardrobe" }));
    const wardrobe = stationsFor(layout).find((s) => s.selection.id === "wardrobe")!;
    expect(useOfficeStore.getState().walkTo?.point).toEqual(wardrobe.approach);
    expect(useOfficeStore.getState().selection).toBeNull();
  });

  test("lists the rooms' places and the teams apart, and gives every row a name", () => {
    const board = (dept: string) => ({ id: `studio-board:${dept}`, x: 4, z: -6, facing: 0 });
    const studios: Studio[] = [
      { deptId: "d0", teamId: "g1", name: "Launch crew", members: ["a1"], leadId: null, board: board("d0"), huddleSpotIds: [], centre: { x: 4, z: -3 } },
      { deptId: "pool", teamId: null, name: "", members: [], leadId: null, board: board("pool"), huddleSpotIds: [], centre: { x: 9, z: -3 } },
    ];
    const campus: OfficeLayout = { ...layout, studios };
    tools({ layout: campus });
    fireEvent.click(screen.getByRole("button", { name: "Places" }));
    const menu = screen.getByRole("group", { name: "Places" });
    const teams = within(menu).getByRole("region", { name: "Teams" });
    expect(within(teams).getByRole("button", { name: "Launch crew: Open the team" })).toBeTruthy();
    // The studio of agents without a team is never a bare "Team board".
    expect(within(teams).getByRole("button", { name: "Without a team: Open the team" })).toBeTruthy();
    expect(within(menu).queryByRole("button", { name: /^Team board/ })).toBeNull();
    const places = within(menu).getByRole("region", { name: "Places" });
    expect(within(places).getByRole("button", { name: "Team room: Manage teams" })).toBeTruthy();
    expect(within(places).queryByRole("button", { name: /Launch crew/ })).toBeNull();
    for (const station of stationsFor(campus)) expect(stationLabel(station, (key) => key)).not.toBe("");
  });

  test("the free plot's stand is listed with the teams, as the place to start one", () => {
    const stand = { id: "team-stand", kind: "lobbyLamp" as const, x: 6, z: 4, rotationY: 0, room: "floor" as const };
    tools({ layout: { ...layout, furniture: [...layout.furniture.filter((item) => item.id !== stand.id), stand] } });
    fireEvent.click(screen.getByRole("button", { name: "Places" }));
    const teams = within(screen.getByRole("group", { name: "Places" })).getByRole("region", { name: "Teams" });
    fireEvent.click(within(teams).getByRole("button", { name: "Free plot: Start a team here" }));
    expect(useOfficeStore.getState().selection).toEqual({ kind: "team", id: "team-stand" });
  });

  test("the arrow keys move through the rows, and sideways to a row's walk button", () => {
    tools();
    fireEvent.click(screen.getByRole("button", { name: "Places" }));
    const menu = screen.getByRole("group", { name: "Places" });
    const rows = [...menu.querySelectorAll<HTMLElement>("[data-place-open]")];
    expect(rows.length).toBeGreaterThan(3);
    const press = (key: string) => {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      const reachedWindow = vi.fn();
      window.addEventListener("keydown", reachedWindow);
      (document.activeElement ?? menu).dispatchEvent(event);
      window.removeEventListener("keydown", reachedWindow);
      // The list keeps its arrows to itself: the character must not walk on them.
      expect(reachedWindow, key).not.toHaveBeenCalled();
      expect(event.defaultPrevented, key).toBe(true);
    };
    rows[0]!.focus();
    press("ArrowDown");
    expect(document.activeElement).toBe(rows[1]);
    press("ArrowDown");
    expect(document.activeElement).toBe(rows[2]);
    press("ArrowUp");
    expect(document.activeElement).toBe(rows[1]);
    press("ArrowRight");
    expect((document.activeElement as HTMLElement).dataset.placeWalk).toBeDefined();
    expect(rows[1]!.closest("[data-place-row]")!.contains(document.activeElement)).toBe(true);
    press("ArrowLeft");
    expect(document.activeElement).toBe(rows[1]);
    press("End");
    expect(document.activeElement).toBe(rows[rows.length - 1]);
    press("ArrowDown");
    expect(document.activeElement).toBe(rows[rows.length - 1]);
    press("Home");
    expect(document.activeElement).toBe(rows[0]);
    press("ArrowUp");
    expect(document.activeElement).toBe(rows[0]);
    // The row in focus is lit in the world.
    expect(useOfficeStore.getState().hover).toEqual(stationsFor(layout)[0]!.selection);
  });

  test("opened from the keyboard it lands on the first place", () => {
    tools();
    const trigger = screen.getByRole("button", { name: "Places" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const menu = screen.getByRole("group", { name: "Places" });
    expect(document.activeElement).toBe(menu.querySelector("[data-place-open]"));
  });

  test("Escape closes the places menu and hands focus back to its button", () => {
    tools();
    const trigger = screen.getByRole("button", { name: "Places" });
    fireEvent.click(trigger);
    fireEvent.focus(screen.getByRole("button", { name: "Team room: Manage teams" }));
    fireEvent.keyDown(screen.getByRole("group", { name: "Places" }), { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Places" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    // Nothing stays lit in the world behind a closed menu.
    expect(useOfficeStore.getState().hover).toBeNull();
  });
});

describe("station prompt", () => {
  test("is one button: the key, the action, the object's name", () => {
    const onUse = vi.fn();
    render(<StationPrompt line={{ how: "key", action: "Create an agent", object: "Spawn point" }} onUse={onUse} />);
    const prompt = screen.getByRole("button");
    expect(prompt.textContent).toBe("ECreate an agentSpawn point");
    fireEvent.click(prompt);
    expect(onUse).toHaveBeenCalledOnce();
  });

  test("in a narrow host it shows the key and the whole action, and keeps the object's name for screen readers", () => {
    render(<StationPrompt compact line={{ how: "key", action: "Call the elevator", object: "Elevator" }} onUse={vi.fn()} />);
    const prompt = screen.getByRole("button");
    expect(prompt.dataset.compact).toBe("true");
    expect(prompt.querySelector("kbd")!.textContent).toBe("E");
    expect(prompt.querySelector("b")!.textContent).toBe("Call the elevator");
    // The name is still part of the button's text, but not drawn.
    const object = screen.getByText("Elevator");
    expect(object.className).toBe("sr-only");
    cleanup();
    render(<StationPrompt line={{ how: "key", action: "Call the elevator", object: "Elevator" }} onUse={vi.fn()} />);
    expect(screen.getByText("Elevator").className).toBe("");
    expect(screen.getByRole("button").dataset.compact).toBeUndefined();
  });

  test("names the click instead of the key for something pointed at from afar", () => {
    render(<StationPrompt line={{ how: "click", action: "Talk to Ada" }} onUse={vi.fn()} />);
    expect(screen.getByRole("button").textContent).toBe("ClickTalk to Ada");
  });

  test("every station of every floor has its action in words", () => {
    const t = (key: string) => key;
    const floors = [layout, buildOfficeLayout([], { variant: "coding" })];
    const ids = new Set(floors.flatMap((floor) => stationsFor(floor).map((s) => s.id)));
    render(<ul>{[...ids].map((id) => <li key={id}><StationWords id={id} /></li>)}</ul>);
    for (const id of ids) {
      const words = screen.getByTestId(`words-${id}`).textContent ?? "";
      expect(words, id).not.toContain("society.");
      expect(words.length, id).toBeGreaterThan(3);
    }
    // The coffee bar's action flips while a break is on.
    expect(stationAction({ id: "break" }, t)).toBe("society.office.use_break");
    expect(stationAction({ id: "break" }, t, true)).toBe("society.office.use_break_end");
    expect(stationAction({ id: "team" }, t, true)).toBe("society.office.use_team");
  });
});

function StationWords({ id }: { id: string }) {
  // The real translator, so a missing key shows up as the key itself.
  const t = useT();
  return <span data-testid={`words-${id}`}>{stationAction({ id }, t)} · {t(`society.office.cp_${id}`)}</span>;
}

describe("control hints", () => {
  test("show the essentials once and are dismissed for good", () => {
    const onDismiss = vi.fn();
    render(<ControlHints onDismiss={onDismiss} />);
    const hints = screen.getByRole("region", { name: "Controls" });
    expect(within(hints).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "WASDWalk", "DragLook around", "EUse what is near", "HAll controls",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  test("are remembered per browser profile", () => {
    expect(loadOfficeSettings().hintsSeen).toBe(false);
    useOfficeSettings.getState().set({ hintsSeen: true });
    expect(loadOfficeSettings().hintsSeen).toBe(true);
    useOfficeSettings.getState().reset();
    expect(loadOfficeSettings().hintsSeen).toBe(false);
  });

  test("stay away for someone who had switched the old permanent hint bar off", () => {
    localStorage.setItem("jarvis.office.settings.v1", JSON.stringify({ alwaysRun: true, showHintBar: false }));
    expect(loadOfficeSettings()).toEqual({ alwaysRun: true, hintsSeen: true });
    localStorage.setItem("jarvis.office.settings.v1", JSON.stringify({ alwaysRun: false, showHintBar: true }));
    expect(loadOfficeSettings().hintsSeen).toBe(false);
  });

  test("fall back to the defaults when storage is unreadable", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    localStorage.setItem("jarvis.office.settings.v1", "{not json");
    expect(loadOfficeSettings()).toEqual(DEFAULT_OFFICE_SETTINGS);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
