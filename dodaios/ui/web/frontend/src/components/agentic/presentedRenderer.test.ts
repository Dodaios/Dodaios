import { describe, expect, it, vi } from "vitest";
import type { Terminal } from "@xterm/xterm";
import { keepPresentedRendererAwake, wakePresentedRenderer } from "./presentedRenderer";

interface FakeService {
  _isPaused: boolean;
  _needsFullRefresh: boolean;
  _rowCount: number;
  _pausedResizeTask: { flush: ReturnType<typeof vi.fn> };
  _handleIntersectionChange: (entry: { isIntersecting?: boolean }) => void;
  refreshRows: ReturnType<typeof vi.fn>;
}

function fakeTerm(paused: boolean) {
  const service: FakeService = {
    _isPaused: paused,
    _needsFullRefresh: paused,
    _rowCount: 24,
    _pausedResizeTask: { flush: vi.fn() },
    _handleIntersectionChange(entry) {
      this._isPaused = entry.isIntersecting === false;
    },
    refreshRows: vi.fn(),
  };
  const term = {
    rows: 24,
    refresh: vi.fn(),
    _core: { _renderService: service },
  };
  return { term: term as unknown as Terminal, service };
}

describe("presented renderer", () => {
  it("unpauses a renderer that still thinks it is off screen", () => {
    const { term, service } = fakeTerm(true);
    wakePresentedRenderer(term);
    expect(service._isPaused).toBe(false);
    expect(service._pausedResizeTask.flush).toHaveBeenCalledOnce();
    expect(service.refreshRows).toHaveBeenCalledWith(0, 23);
  });

  it("leaves a renderer that is already drawing alone", () => {
    const { term, service } = fakeTerm(false);
    wakePresentedRenderer(term);
    expect(service.refreshRows).not.toHaveBeenCalled();
  });

  it("ignores a late not-intersecting entry until the window lets go", () => {
    const { term, service } = fakeTerm(true);
    const release = keepPresentedRendererAwake(term);
    expect(service._isPaused).toBe(false);
    expect(service.refreshRows).toHaveBeenCalled();
    service._handleIntersectionChange({ isIntersecting: false });
    expect(service._isPaused).toBe(false);
    release();
    service._handleIntersectionChange({ isIntersecting: false });
    expect(service._isPaused).toBe(true);
  });
});
