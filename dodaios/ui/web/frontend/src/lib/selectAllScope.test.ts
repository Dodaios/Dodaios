import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { installSelectAllScope, selectAllScope } from "./selectAllScope";

function press(target: Element, init: KeyboardEventInit = { metaKey: true }): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

function selected(): string {
  return document.getSelection()?.toString() ?? "";
}

describe("select all stays in the conversation", () => {
  let remove = () => {};

  beforeEach(() => {
    document.body.innerHTML = `
      <aside id="sidebar"><span>Projects</span><button id="row">A thread</button></aside>
      <main>
        <section id="pane-one">
          <header id="header-one">First thread</header>
          <div data-select-all id="talk-one"><p>first answer</p></div>
          <textarea id="composer"></textarea>
        </section>
        <section id="pane-two">
          <header id="header-two">Second thread</header>
          <div data-select-all id="talk-two"><p>second answer</p></div>
        </section>
      </main>`;
    document.getSelection()?.removeAllRanges();
    remove = installSelectAllScope();
  });

  afterEach(() => {
    remove();
    document.body.innerHTML = "";
  });

  it("selects the conversation, not the window", () => {
    const event = press(document.body);
    expect(event.defaultPrevented).toBe(true);
    expect(selected()).toBe("first answer");
  });

  it("works with Ctrl as well", () => {
    expect(press(document.body, { ctrlKey: true }).defaultPrevented).toBe(true);
    expect(selected()).toBe("first answer");
  });

  it("selects the conversation of the pane last pressed in", () => {
    document.getElementById("header-two")!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    press(document.body);
    expect(selected()).toBe("second answer");
  });

  it("selects the conversation the pointer was pressed inside", () => {
    document.querySelector("#talk-two p")!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    press(document.body);
    expect(selected()).toBe("second answer");
  });

  it("follows the focus too", () => {
    document.getElementById("header-two")!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    document.getElementById("row")!.dispatchEvent(new Event("focusin", { bubbles: true }));
    press(document.body);
    expect(selected()).toBe("first answer");
  });

  it("leaves a text field its own select all", () => {
    const event = press(document.getElementById("composer")!);
    expect(event.defaultPrevented).toBe(false);
    expect(selected()).toBe("");
  });

  it("leaves other chords alone", () => {
    expect(press(document.body, { metaKey: true, shiftKey: true }).defaultPrevented).toBe(false);
    expect(press(document.body, { metaKey: true, altKey: true }).defaultPrevented).toBe(false);
    expect(press(document.body, { metaKey: false }).defaultPrevented).toBe(false);
    expect(press(document.body, { metaKey: true, key: "c" }).defaultPrevented).toBe(false);
  });

  it("skips a conversation that is not shown", () => {
    document.getElementById("pane-one")!.hidden = true;
    press(document.body);
    expect(selected()).toBe("second answer");
  });

  it("keeps the engine's select all while a dialog is open", () => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    document.body.appendChild(dialog);
    expect(press(document.body).defaultPrevented).toBe(false);
  });

  it("keeps the engine's select all on a page without a conversation", () => {
    document.querySelectorAll("[data-select-all]").forEach((element) => element.removeAttribute("data-select-all"));
    expect(press(document.body).defaultPrevented).toBe(false);
    expect(selectAllScope(document.body)).toBeNull();
  });

  it("stops listening when removed", () => {
    remove();
    expect(press(document.body).defaultPrevented).toBe(false);
  });
});
