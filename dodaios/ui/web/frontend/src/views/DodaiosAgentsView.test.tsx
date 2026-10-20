import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DodaiosAgentsView } from "./DodaiosAgentsView";

vi.mock("@/i18n", () => ({ useLocaleChunk: () => true }));
vi.mock("@/components/society/world/WorldStage", () => ({ WorldStage: () => { throw new Error("Legacy world must not mount"); } }));
vi.mock("@/components/society/mars/MarsWorldStage", () => ({ MarsWorldStage: () => { throw new Error("Mars must not mount as the map"); } }));
vi.mock("@/components/society/verse/VerseStage", () => ({ VerseStage: ({ active, onOpenLedger, onSelectAgent }: any) => <div data-testid="ship-map" data-active={active}><button onClick={onOpenLedger}>Open agents</button><button onClick={() => onSelectAgent("a1")}>Agent a1</button></div> }));
const initialUrl = window.location.href;
afterEach(() => { cleanup(); window.history.replaceState(null, "", initialUrl); });

it.each(["?view=agents", "?view=agents&world=legacy", "?view=agents&world=mars"])("mounts only the ship for %s", async (url) => {
  window.history.replaceState(null, "", url);
  const openAgents = vi.fn();
  render(<DodaiosAgentsView onOpenAgents={openAgents} />);
  expect(await screen.findByTestId("ship-map")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /previous|preview/i })).toBeNull();
  fireEvent.click(screen.getByText("Open agents"));
  expect(openAgents).toHaveBeenCalledOnce();
});

it("forwards an agent picked on the ship", async () => {
  const onSelect = vi.fn();
  render(<DodaiosAgentsView onOpenAgents={() => undefined} onSelectAgent={onSelect} />);
  fireEvent.click(await screen.findByText("Agent a1"));
  expect(onSelect).toHaveBeenCalledWith("a1");
});

it("forwards visibility without replacing the ship", () => {
  const view = render(<DodaiosAgentsView onOpenAgents={() => undefined} />);
  const ship = screen.getByTestId("ship-map");
  expect(ship.dataset.active).toBe("true");
  view.rerender(<DodaiosAgentsView active={false} onOpenAgents={() => undefined} />);
  expect(screen.getByTestId("ship-map")).toBe(ship);
  expect(ship.dataset.active).toBe("false");
});
