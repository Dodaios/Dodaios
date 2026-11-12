/**
 * A `chart` fence in an answer is DRAWN as a chart card, with every number
 * one click away as a table; a block that is still arriving holds its place,
 * and one that is no chart stays the code it is.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { LeadReply, splitReply } from "@/components/agentchat/LeadReply";
import { MarkdownProse } from "@/components/outputs/MarkdownProse";
import { SERIES_COLORS } from "@/components/outputs/ChartFence";

afterEach(() => cleanup());

const PRICE = {
  type: "line",
  title: "ACME share price",
  unit: "USD",
  note: "daily close",
  value: "142.30 USD",
  delta: "+2.1 %",
  x: ["1 Jun", "2 Jun", "3 Jun"],
  series: [{ name: "ACME", data: [139.4, 140.1, 142.3] }],
};
const TWO = {
  type: "column",
  title: "Orders",
  x: ["Q1", "Q2", "Q3"],
  series: [{ name: "Shop", data: [10, 12, 15] }, { name: "Retail", data: [4, 6, 5] }],
};

function fenced(spec: unknown): string {
  return "Here is the course.\n\n```chart\n" + JSON.stringify(spec) + "\n```\n\nIt rose.";
}

describe("a chart block in a chat answer", () => {
  it("is drawn as a chart card with its title, headline figure and change", async () => {
    render(<ChatMarkdown text={fenced(PRICE)} />);
    const card = await screen.findByTestId("chart-fence");
    expect(card.dataset.chartType).toBe("line");
    expect(within(card).getByText("ACME share price")).toBeTruthy();
    expect(within(card).getByText("USD · daily close")).toBeTruthy();
    expect(within(card).getByText("142.30 USD")).toBeTruthy();
    expect(within(card).getByTestId("chart-fence-delta").textContent).toBe("+2.1 %");
    expect(card.querySelector(".recharts-line")).not.toBeNull();
    // The JSON itself is not shown.
    expect(screen.queryByText(/"series"/)).toBeNull();
    // The words around the block are still there.
    expect(screen.getByText("Here is the course.")).toBeTruthy();
    expect(screen.getByText("It rose.")).toBeTruthy();
  });

  it("needs no legend for one series and names each of several", async () => {
    const { unmount } = render(<ChatMarkdown text={fenced(PRICE)} />);
    await screen.findByTestId("chart-fence");
    expect(screen.queryByTestId("chart-fence-legend")).toBeNull();
    unmount();
    render(<ChatMarkdown text={fenced(TWO)} />);
    const legend = await screen.findByTestId("chart-fence-legend");
    expect(within(legend).getByText("Shop")).toBeTruthy();
    expect(within(legend).getByText("Retail")).toBeTruthy();
    expect(screen.getByTestId("chart-fence").querySelectorAll(".recharts-bar").length).toBe(2);
  });

  it("shows every number as a table on request", async () => {
    render(<ChatMarkdown text={fenced(PRICE)} />);
    const card = await screen.findByTestId("chart-fence");
    fireEvent.click(within(card).getByRole("button", { name: "Table" }));
    const table = within(card).getByTestId("chart-fence-table");
    expect(within(table).getByText("2 Jun")).toBeTruthy();
    expect(within(table).getByText("140.1 USD")).toBeTruthy();
    expect(within(card).queryByTestId("chart-fence-plot")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Chart" }));
    expect(within(card).getByTestId("chart-fence-plot")).toBeTruthy();
  });

  it("draws a comparison of named things as one bar per row", async () => {
    render(<ChatMarkdown text={fenced({ type: "bar", unit: "%", x: ["Berlin", "Hamburg", "Munich"], values: [12, 9, 7] })} />);
    const card = await screen.findByTestId("chart-fence");
    expect(card.dataset.chartType).toBe("bar");
    expect(card.querySelector(".recharts-bar")).not.toBeNull();
  });

  it("holds the chart's place while its block is still being written", async () => {
    render(<ChatMarkdown text={'Here is the course.\n\n```chart\n{"type": "line", "x": ["1 Jun", "2 J'} />);
    expect(await screen.findByTestId("chart-fence-pending")).toBeTruthy();
    expect(screen.queryByText(/"type"/)).toBeNull();
  });

  it("leaves a finished block that is no chart as code", () => {
    render(<ChatMarkdown text={'```chart\n{"type": "pie", "x": ["a", "b"], "values": [1, 2]}\n```'} />);
    expect(screen.queryByTestId("chart-fence")).toBeNull();
    expect(screen.queryByTestId("chart-fence-pending")).toBeNull();
    expect(document.body.textContent).toContain('"pie"');
  });

  it("writes what the model sent as text, never as markup", async () => {
    render(<ChatMarkdown text={fenced({ ...PRICE, title: "<img src=x onerror=alert(1)>" })} />);
    const card = await screen.findByTestId("chart-fence");
    expect(card.querySelector("img")).toBeNull();
    expect(within(card).getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });
});

describe("a chart in the assistant's own conversation", () => {
  it("is a message of its own, a card without a bubble around it", async () => {
    const parts = splitReply(fenced(PRICE));
    expect(parts.map((part) => [part.note, part.chart ?? false])).toEqual([[false, false], [false, true], [false, false]]);
    render(<LeadReply text={fenced(PRICE)} />);
    const bubbles = screen.getAllByTestId("lead-bubble");
    expect(bubbles).toHaveLength(3);
    expect(bubbles[1].dataset.chart).toBe("");
    expect(bubbles[1].className).not.toContain("jarvis-chat-in");
    expect(await within(bubbles[1]).findByTestId("chart-fence")).toBeTruthy();
  });

  it("does not turn a short answer into a document because its chart has many numbers", () => {
    const x = Array.from({ length: 120 }, (_, i) => `day ${i + 1}`);
    const long = { ...PRICE, x, series: [{ name: "ACME", data: x.map((_, i) => 100 + i) }] };
    expect(JSON.stringify(long).length).toBeGreaterThan(1400);
    expect(splitReply(fenced(long)).map((part) => part.note)).toEqual([false, false, false]);
  });
});

describe("a chart block in a report page", () => {
  it("is drawn there too", async () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={fenced(TWO)} />);
    expect((await screen.findByTestId("chart-fence")).dataset.chartType).toBe("column");
  });
});

describe("the series colours", () => {
  it("are six per theme, in one fixed order", () => {
    expect(SERIES_COLORS.light).toHaveLength(6);
    expect(SERIES_COLORS.dark).toHaveLength(6);
    expect(new Set(SERIES_COLORS.light).size).toBe(6);
  });
});
