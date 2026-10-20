import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { ownsKeyboard } from "./OfficePlayer";
import { StationSheet, StationSidePanel } from "./StationSheet";

beforeAll(async () => { await loadLocaleChunk("society"); });
afterEach(cleanup);

/** A map host with a button that opens a station's dialog, the way the stage mounts one. */
function Stage({ onReturn }: { onReturn?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <div data-testid="host" tabIndex={0} />
      <button type="button" onClick={() => setOpen(true)}>Open teams</button>
      {open && (
        <StationSheet title="Team room" description="Your teams and their meetings" onClose={() => setOpen(false)}
          returnFocus={() => { onReturn?.(); screen.getByTestId("host").focus(); }}>
          <input aria-label="Team name" />
        </StationSheet>
      )}
    </div>
  );
}

describe("station dialog", () => {
  test("is a labelled modal dialog that owns the keyboard while it is open", () => {
    render(<Stage />);
    fireEvent.click(screen.getByRole("button", { name: "Open teams" }));
    const dialog = screen.getByRole("dialog", { name: "Team room" });
    expect(dialog.getAttribute("data-state")).toBe("open");
    expect(screen.getByText("Your teams and their meetings")).toBeTruthy();
    // The walking keys stand down while a dialog is open, wherever focus sits.
    expect(ownsKeyboard(document.body)).toBe(true);
  });

  test("Escape closes it and hands focus to the map, so the walking keys answer at once", async () => {
    const onReturn = vi.fn();
    render(<Stage onReturn={onReturn} />);
    fireEvent.click(screen.getByRole("button", { name: "Open teams" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(onReturn).toHaveBeenCalledOnce());
    const host = screen.getByTestId("host");
    expect(document.activeElement).toBe(host);
    expect(ownsKeyboard(host)).toBe(false);
  });

  test("the close button does the same", async () => {
    const onReturn = vi.fn();
    render(<Stage onReturn={onReturn} />);
    fireEvent.click(screen.getByRole("button", { name: "Open teams" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(onReturn).toHaveBeenCalledOnce());
    expect(document.activeElement).toBe(screen.getByTestId("host"));
  });
});

describe("station side panel", () => {
  test("is a labelled panel that takes focus without taking the walking keys", () => {
    const onClose = vi.fn();
    render(<StationSidePanel title="Wardrobe" description="Dress yourself or an agent" onClose={onClose}><p>Outfits</p></StationSidePanel>);
    const panel = screen.getByRole("complementary", { name: "Wardrobe" });
    expect(document.activeElement).toBe(panel);
    expect(ownsKeyboard(panel)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
