import { beforeEach, describe, expect, it } from "vitest";

import { toastPlacement, useNativeBrowserArea } from "./nativeBrowserArea";

describe("toastPlacement", () => {
  it("leaves the stack in its corner when no browser panel is on screen", () => {
    expect(toastPlacement({}, 2560)).toEqual({ right: null, hidesBrowser: false });
  });

  it("leaves the stack alone when the panel stands elsewhere", () => {
    const areas = { ide: { left: 0, top: 40, right: 1200, bottom: 1300 } };
    expect(toastPlacement(areas, 2560)).toEqual({ right: null, hidesBrowser: false });
  });

  it("moves the stack left of a panel on the right side", () => {
    const areas = { ide: { left: 1600, top: 40, right: 2560, bottom: 1300 } };
    expect(toastPlacement(areas, 2560)).toEqual({ right: 2560 - 1600 + 16, hidesBrowser: false });
  });

  it("hides the browser when no room is left beside the panel", () => {
    const areas = { ide: { left: 100, top: 40, right: 2560, bottom: 1300 } };
    expect(toastPlacement(areas, 2560)).toEqual({ right: null, hidesBrowser: true });
  });

  it("ignores a panel that starts below the stack", () => {
    const areas = { ide: { left: 1600, top: 900, right: 2560, bottom: 1300 } };
    expect(toastPlacement(areas, 2560)).toEqual({ right: null, hidesBrowser: false });
  });
});

describe("useNativeBrowserArea", () => {
  beforeEach(() => useNativeBrowserArea.setState({ areas: {} }));

  it("stores rounded boxes and drops them again", () => {
    const { setArea } = useNativeBrowserArea.getState();
    setArea("ide", { left: 10.4, top: 20.6, right: 300.2, bottom: 400.7 });
    expect(useNativeBrowserArea.getState().areas.ide).toEqual({ left: 10, top: 21, right: 300, bottom: 401 });
    const before = useNativeBrowserArea.getState().areas;
    setArea("ide", { left: 10.1, top: 20.9, right: 300.4, bottom: 401.2 });
    expect(useNativeBrowserArea.getState().areas).toBe(before);
    setArea("ide", null);
    expect(useNativeBrowserArea.getState().areas).toEqual({});
  });
});
