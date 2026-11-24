import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { EditContextMenu, wantsNativeTextMenu } from "@/components/EditContextMenu";
import { captureEditSnapshot } from "@/lib/editActions";

type Host = { __JARVIS_EMBEDDED_DESKTOP?: boolean; __DODAIOS_NATIVE_TEXT_MENU?: boolean };
const host = window as unknown as Host;

afterEach(() => {
  cleanup();
  delete host.__JARVIS_EMBEDDED_DESKTOP;
  delete host.__DODAIOS_NATIVE_TEXT_MENU;
  document.body.innerHTML = "";
});

function field(): HTMLTextAreaElement {
  const area = document.createElement("textarea");
  area.value = "Hallo Welt";
  document.body.appendChild(area);
  return area;
}

describe("wantsNativeTextMenu", () => {
  it("leaves a text field to the native menu when the shell enabled it", () => {
    host.__JARVIS_EMBEDDED_DESKTOP = true;
    host.__DODAIOS_NATIVE_TEXT_MENU = true;
    expect(wantsNativeTextMenu(captureEditSnapshot(field()))).toBe(true);
  });

  it("keeps the app menu in the desktop window without the shell flag", () => {
    host.__JARVIS_EMBEDDED_DESKTOP = true;
    expect(wantsNativeTextMenu(captureEditSnapshot(field()))).toBe(false);
  });

  it("keeps the app menu on plain chrome with nothing selected", () => {
    host.__DODAIOS_NATIVE_TEXT_MENU = true;
    const div = document.createElement("div");
    document.body.appendChild(div);
    expect(wantsNativeTextMenu(captureEditSnapshot(div))).toBe(false);
  });

  it("keeps the app menu in a terminal", () => {
    host.__DODAIOS_NATIVE_TEXT_MENU = true;
    const term = document.createElement("div");
    term.setAttribute("data-jarvis-terminal", "");
    Object.assign(term, {
      __jarvisTerminalBridge: { getSelection: () => "ls", paste: () => {}, focus: () => {} },
    });
    document.body.appendChild(term);
    expect(wantsNativeTextMenu(captureEditSnapshot(term))).toBe(false);
  });
});

describe("EditContextMenu", () => {
  it("does not open over a text field and lets the native menu through", () => {
    host.__JARVIS_EMBEDDED_DESKTOP = true;
    host.__DODAIOS_NATIVE_TEXT_MENU = true;
    render(<EditContextMenu />);
    const area = field();
    const notCancelled = fireEvent.contextMenu(area, { clientX: 10, clientY: 10 });
    expect(notCancelled).toBe(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("EditContextMenu area entries", () => {
  it("shows the clicked area's own entries and runs them", async () => {
    const { attachContextActions } = await import("@/lib/contextActions");
    render(<EditContextMenu />);
    const area = document.createElement("div");
    const inner = document.createElement("span");
    area.appendChild(inner);
    document.body.appendChild(area);
    const ran: string[] = [];
    attachContextActions(area, () => [
      { id: "clear", label: "Clear terminal", run: () => void ran.push("clear") },
    ]);
    const notCancelled = fireEvent.contextMenu(inner, { clientX: 5, clientY: 5 });
    expect(notCancelled).toBe(false);
    fireEvent.click(screen.getByRole("menuitem", { name: /Clear terminal/ }));
    await Promise.resolve();
    expect(ran).toEqual(["clear"]);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("offers Open link and Copy link address on a link", () => {
    render(<EditContextMenu />);
    const link = document.createElement("a");
    link.href = "https://example.com/page";
    link.textContent = "page";
    document.body.appendChild(link);
    fireEvent.contextMenu(link, { clientX: 5, clientY: 5 });
    expect(screen.getByRole("menuitem", { name: /Open link|edit_menu.open_link/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Copy link address|edit_menu.copy_link/ })).toBeTruthy();
  });

  it("enables Select all in a terminal that can select its buffer", () => {
    render(<EditContextMenu />);
    const term = document.createElement("div");
    term.setAttribute("data-jarvis-terminal", "");
    let selected = false;
    Object.assign(term, {
      __jarvisTerminalBridge: {
        getSelection: () => "",
        paste: () => {},
        focus: () => {},
        selectAll: () => {
          selected = true;
        },
      },
    });
    document.body.appendChild(term);
    fireEvent.contextMenu(term, { clientX: 5, clientY: 5 });
    const item = screen.getByRole("menuitem", { name: /Select all|edit_menu.select_all/ });
    expect((item as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(item);
    expect(selected).toBe(true);
  });

  it("stays out when a component already claimed the click", () => {
    render(<EditContextMenu />);
    const term = document.createElement("div");
    term.setAttribute("data-jarvis-terminal", "");
    Object.assign(term, {
      __jarvisTerminalBridge: { getSelection: () => "", paste: () => {}, focus: () => {} },
    });
    term.addEventListener("contextmenu", (e) => e.preventDefault());
    document.body.appendChild(term);
    fireEvent.contextMenu(term, { clientX: 5, clientY: 5 });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
