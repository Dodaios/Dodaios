/**
 * Who gets the keys: a press on the stage takes the focus from the IDE's
 * terminal beside it, nothing else does, and the hint shows while the keys
 * go elsewhere. The toolbar says why first person is off in a small panel.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { Toolbar } from "../hud/DeckBar";
import { keysReachStage, takeFocusOnPress, typesText, useStageFocus } from "./stageFocus";

afterEach(cleanup);

function Harness() {
  const host = useRef<HTMLDivElement>(null);
  const { keysReach, onPointerDownCapture } = useStageFocus(host, true);
  return (
    <div>
      <textarea data-testid="terminal" />
      <div ref={host} data-testid="stage" tabIndex={-1} data-keys={keysReach ? "stage" : "elsewhere"} onPointerDownCapture={onPointerDownCapture}>
        <canvas data-testid="surface" />
        <input data-testid="field" />
      </div>
    </div>
  );
}

describe("the stage's keyboard focus", () => {
  it("reads the keys while the focus is inside the stage or nowhere in particular", () => {
    const host = document.createElement("div");
    const inner = document.createElement("button");
    const outside = document.createElement("textarea");
    host.append(inner);
    document.body.append(host, outside);
    expect(keysReachStage(host, null)).toBe(true);
    expect(keysReachStage(host, document.body)).toBe(true);
    expect(keysReachStage(host, inner)).toBe(true);
    expect(keysReachStage(host, outside)).toBe(false);
    host.remove();
    outside.remove();
  });

  it("knows a text field (and a terminal's input) from the rest", () => {
    expect(typesText(document.createElement("textarea"))).toBe(true);
    expect(typesText(document.createElement("input"))).toBe(true);
    expect(typesText(document.createElement("canvas"))).toBe(false);
    expect(typesText(null)).toBe(false);
  });

  it("takes the focus from the terminal on a press on the stage, and the hint goes", () => {
    render(<Harness />);
    const terminal = screen.getByTestId("terminal");
    const stage = screen.getByTestId("stage");
    act(() => terminal.focus());
    expect(document.activeElement).toBe(terminal);
    expect(stage.dataset.keys).toBe("elsewhere");
    fireEvent.pointerDown(screen.getByTestId("surface"));
    expect(document.activeElement).toBe(stage);
    expect(stage.dataset.keys).toBe("stage");
  });

  it("never pulls the focus on its own, and leaves a field inside the stage alone", () => {
    render(<Harness />);
    const terminal = screen.getByTestId("terminal");
    act(() => terminal.focus());
    // Nothing pressed on the stage: the terminal keeps its keys.
    expect(document.activeElement).toBe(terminal);
    const field = screen.getByTestId("field");
    expect(takeFocusOnPress(screen.getByTestId("stage"), field)).toBe(false);
    expect(document.activeElement).toBe(terminal);
  });

  it("does not move the focus within the stage", () => {
    render(<Harness />);
    const stage = screen.getByTestId("stage");
    const field = screen.getByTestId("field");
    act(() => field.focus());
    expect(takeFocusOnPress(stage, screen.getByTestId("surface"))).toBe(false);
    expect(document.activeElement).toBe(field);
  });
});

describe("the toolbar in a small side panel", () => {
  const t = (key: string) => key;
  const noop = () => undefined;

  it("greys out first person with the panel's own reason", () => {
    render(<Toolbar t={t} view="third" firstAvailable={false} firstUnavailable="too small" onView={noop} onLift={noop} onCommander={noop} onHelp={noop} />);
    const first = document.querySelector<HTMLButtonElement>('[data-view="first"]')!;
    expect(first.disabled).toBe(true);
    expect(first.title).toBe("too small");
  });

  it("offers first person where the panel is roomy enough", () => {
    render(<Toolbar t={t} view="third" firstAvailable onView={noop} onLift={noop} onCommander={noop} onHelp={noop} />);
    const first = document.querySelector<HTMLButtonElement>('[data-view="first"]')!;
    expect(first.disabled).toBe(false);
  });
});
