import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { ColorPicker, MenuItem, NumberField, Popover, ToolbarButton, ToolbarGroup, normalizeHex } from "./controls";

afterEach(cleanup);

describe("ToolbarButton and ToolbarGroup", () => {
  it("names an icon button and says whether a toggle is on", () => {
    render(
      <ToolbarGroup label="Text style">
        <ToolbarButton label="Bold" icon={<b>B</b>} active onClick={() => {}} />
        <ToolbarButton label="Insert chart" showLabel />
      </ToolbarGroup>,
    );
    expect(screen.getByRole("group", { name: "Text style" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bold" }).getAttribute("aria-pressed")).toBe("true");
    const plain = screen.getByRole("button", { name: "Insert chart" });
    expect(plain.hasAttribute("aria-pressed")).toBe(false);
  });
});

describe("NumberField", () => {
  function Harness({ onChange }: { onChange: (value: number | null) => void }) {
    const [value, setValue] = useState<number | null>(10);
    return (
      <NumberField
        label="Width"
        value={value}
        min={0}
        max={100}
        decimals={1}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
    );
  }

  it("takes a typed number on Enter or blur, clamped and rounded, never half-typed", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const field = screen.getByRole("spinbutton", { name: "Width" }) as HTMLInputElement;
    expect(field.value).toBe("10.0");
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "12," } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "12,34" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(12.3);
    fireEvent.change(field, { target: { value: "500" } });
    fireEvent.blur(field);
    expect(onChange).toHaveBeenLastCalledWith(100);
    expect(field.value).toBe("100.0");
    fireEvent.change(field, { target: { value: "abc" } });
    fireEvent.blur(field);
    expect(field.value).toBe("100.0");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("steps with the arrow keys, ten steps with Shift", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const field = screen.getByRole("spinbutton", { name: "Width" });
    fireEvent.keyDown(field, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith(11);
    fireEvent.keyDown(field, { key: "ArrowDown", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith(1);
  });
});

describe("ColorPicker", () => {
  it("offers the kit palette, a colour code and the default", () => {
    const onChange = vi.fn();
    render(<ColorPicker label="Fill" value="" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Fill/ }));
    fireEvent.click(screen.getByRole("button", { name: "#D4532E" }));
    expect(onChange).toHaveBeenLastCalledWith("#D4532E");
    fireEvent.click(screen.getByRole("button", { name: /Fill/ }));
    const code = screen.getByLabelText("Colour code");
    fireEvent.change(code, { target: { value: "0a0" } });
    fireEvent.keyDown(code, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("#00AA00");
    fireEvent.click(screen.getByRole("button", { name: "Default" }));
    expect(onChange).toHaveBeenLastCalledWith("");
  });

  it("normalizes colour codes", () => {
    expect(normalizeHex("#abc")).toBe("#AABBCC");
    expect(normalizeHex("2a6fd0")).toBe("#2A6FD0");
    expect(normalizeHex("red")).toBeNull();
  });
});

describe("Popover", () => {
  it("opens a menu, moves with the arrows, closes on a pick and on Escape", () => {
    const picked = vi.fn();
    render(
      <Popover label="Insert" role="menu" trigger={<button type="button">Insert</button>}>
        <MenuItem label="Row above" onClick={() => picked("above")} />
        <MenuItem label="Row below" onClick={() => picked("below")} />
      </Popover>,
    );
    const trigger = screen.getByRole("button", { name: "Insert" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("menu", { name: "Insert" });
    const items = screen.getAllByRole("menuitem");
    items[0].focus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.click(items[1]);
    expect(picked).toHaveBeenCalledWith("below");
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on a click outside", () => {
    render(
      <div>
        <p>outside</p>
        <Popover label="More" trigger={<button type="button">More</button>}>
          <p>inside</p>
        </Popover>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.pointerDown(screen.getByText("inside"));
    expect(screen.getByRole("dialog", { name: "More" })).toBeTruthy();
    fireEvent.pointerDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog", { name: "More" })).toBeNull();
  });
});
