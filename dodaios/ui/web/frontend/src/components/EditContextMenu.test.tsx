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
