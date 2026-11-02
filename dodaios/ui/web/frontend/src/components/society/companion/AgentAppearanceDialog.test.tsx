import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AgentAppearanceDialog } from "./AgentAppearanceDialog";
import { SAMPLE_ROSTER } from "../mockRoster";
import { defaultCompanion } from "./appearance";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("./CompanionPreview", () => ({ CompanionPreview: () => <div data-testid="preview" /> }));
vi.mock("../figures/AgentFigureViewer", () => ({ AgentFigureViewer: () => <div data-testid="character-preview" /> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const PETS = { active: "gigi", scale: 1, bubble: true, strip_always: false, visible: true, pets: ["gigi", "ember", "miso", "bolt", "brew", "mochi", "shelly", "cocoa", "dodaios"].map(id => ({
  id, name: id, description: "", builtin: true, frame_size: 48, animations: { idle: { row: 0, frames: 1, fps: 1, loop: true } }, sheet_url: `/api/pets/${id}/sheet.png`,
})) };

function setup(fail = false, legacy = false, companion: Record<string, unknown> = { pet: "ember" }) {
  const original = SAMPLE_ROSTER.find(a => a.tier !== "lead")!;
  const figure = legacy ? { contract: 1 as const, archetype: "biped" as const, base: "rogue", parts: {} } : original.figure!;
  const agent = { ...original, agentId: "appearance-test", figure: { ...figure, companion: { ...defaultCompanion("test"), shape: "circle" as const, pet: undefined, ...companion } } };
  const close = vi.fn();
  // The look picker reads agent levels; an unreachable level system leaves every look open.
  const fetcher = vi.fn(async (url: RequestInfo | URL) => String(url).startsWith("/api/progression")
    ? new Response("{}", { status: 404 })
    : String(url).startsWith("/api/pets") ? new Response(JSON.stringify(PETS), { status: 200 })
    : new Response(JSON.stringify({ agent }), { status: fail ? 500 : 200 }));
  const saves = () => fetcher.mock.calls.filter(([url]) => String(url).startsWith("/api/society/agents/"));
  vi.stubGlobal("fetch", fetcher);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><AgentAppearanceDialog agent={agent} sample={false} onClose={close} /></QueryClientProvider>);
  return { agent, fetcher, close, saves };
}

it("saves a picked pet without overwriting character parts or other agent fields", async () => {
  const { agent, saves } = setup();
  fireEvent.click(await screen.findByRole("button", { name: "cocoa" }));
  fireEvent.click(screen.getByRole("button", { name: "society.card.save" }));
  await waitFor(() => expect(saves()).toHaveLength(1));
  const [, init] = saves()[0] as unknown as [string, RequestInit];
  const body = JSON.parse(init.body as string);
  expect(Object.keys(body)).toEqual(["avatar"]);
  expect(body.avatar.companion.pet).toBe("cocoa");
  expect(body.avatar.parts).toEqual(agent.figure?.parts);
  expect(body.avatar.base).toBe(agent.figure?.base);
});

it("protects an unsaved pet choice after a rejected save", async () => {
  const { close } = setup(true);
  fireEvent.click(await screen.findByRole("button", { name: "cocoa" }));
  fireEvent.click(screen.getByRole("button", { name: "society.card.save" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "cocoa" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getAllByRole("button", { name: "society.card.close" })[0]);
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByText("society.profile_card.unsaved")).toBeTruthy();
});

it("keeps the pet choice while editing the character", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "cocoa" }));
  fireEvent.click(screen.getByRole("tab", { name: "society.companion.character" }));
  await screen.findByTestId("character-preview");
  fireEvent.click(screen.getByRole("tab", { name: "society.companion.companion" }));
  expect(screen.getByRole("button", { name: "cocoa" }).getAttribute("aria-pressed")).toBe("true");
});

it("offers only pets: no shapes, no pixel creatures, no colours and no sliders", async () => {
  setup();
  expect(await screen.findByRole("button", { name: "ember" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "ember" }).getAttribute("aria-pressed")).toBe("true");
  for (const gone of ["society.companion.look_creature", "society.companion.look_shape", "society.companion.look_pet", "society.companion.shapes.cloud"]) {
    expect(screen.queryByRole("button", { name: gone })).toBeNull();
  }
  expect(screen.queryByTestId("creature-picker")).toBeNull();
  expect(screen.queryByLabelText("society.companion.custom_color")).toBeNull();
  expect(screen.queryByRole("slider")).toBeNull();
});

it("opens an agent that still wears a pixel creature on a pet, and saves no creature", async () => {
  const { saves } = setup(false, false, { creature: { seed: 24, palette: "neon", eyes: "dot" }, look: "shape" });
  const picker = await screen.findByTestId("companion-pet-picker");
  await waitFor(() => expect(within(picker).getAllByRole("button", { pressed: true })).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "cocoa" }));
  fireEvent.click(screen.getByRole("button", { name: "society.card.save" }));
  await waitFor(() => expect(saves()).toHaveLength(1));
  const companion = JSON.parse((saves()[0] as unknown as [string, RequestInit])[1].body as string).avatar.companion;
  expect(companion.pet).toBe("cocoa");
  expect(companion.creature).toBeUndefined();
  expect(companion.look).toBeUndefined();
});

it("saves a chosen hairstyle on the recipe without dropping its colours", async () => {
  const { agent, saves } = setup();
  fireEvent.click(screen.getByRole("tab", { name: "society.companion.character" }));
  await screen.findByTestId("character-preview");
  fireEvent.click(screen.getByRole("button", { name: "society.office.hair_beanie" }));
  expect(screen.getByRole("button", { name: "society.office.hair_beanie" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "society.card.save" }));
  await waitFor(() => expect(saves()).toHaveLength(1));
  const [, init] = saves()[0] as unknown as [string, RequestInit];
  const body = JSON.parse(init.body as string);
  expect(body.avatar.hairStyle).toBe("beanie");
  expect(body.avatar.palette).toEqual(agent.figure?.palette);
});
