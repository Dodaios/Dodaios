/**
 * Test helpers for the node bar every editor is framed with (`EditorShell`).
 *
 * The bar's "⋯" holds undo, redo and each type's tools used now and then;
 * `barItem` opens it when it is shut and hands back the item. Closing the
 * node goes through the leave guard (`leaveGuard.ts`): `renderEditor` puts
 * an editor under one, and `leave` closes it the way the stage's close
 * button does (save first, then close).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { createElement } from "react";

import { LeaveGuardContext, createLeaveGuard, type LeaveGuard } from "./leaveGuard";

/** An item of the bar's "⋯" menu, the menu opened first when it is shut. */
export function barItem(testId: string): HTMLButtonElement {
  const found = screen.queryByTestId(testId);
  if (found) return found as HTMLButtonElement;
  fireEvent.click(screen.getByTestId("node-editor-more"));
  return screen.getByTestId(testId) as HTMLButtonElement;
}

/** Shut the bar's menu again, with a press outside it. */
export function closeBarMenu(): void {
  fireEvent.pointerDown(document.body);
}

/** Render an editor under a leave guard, as the stage does. */
export function renderEditor(ui: ReactElement): ReturnType<typeof render> & { guard: LeaveGuard } {
  const guard = createLeaveGuard();
  const view = render(createElement(LeaveGuardContext.Provider, { value: guard }, ui));
  return { ...view, guard };
}

/** Close the node the way the stage's close button does: the editor saves first, then `go` runs. */
export function leave(guard: LeaveGuard, go: () => void = () => {}): void {
  act(() => guard.leave(go));
}
