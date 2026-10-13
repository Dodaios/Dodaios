import { describe, expect, it } from "vitest";
import { PLATE_RANGE, plateDetail, type PlateDetail, type PlateInput } from "./namePlate";

const far: PlateInput = { cameraDistance: 40, personDistance: 30, pointed: false, selected: false };

describe("name plate detail", () => {
  it("is a dot from across the floor", () => {
    expect(plateDetail("dot", far)).toBe("dot");
    expect(plateDetail("full", far)).toBe("dot");
  });

  it("opens for the agent that is pointed at or selected, however far away", () => {
    expect(plateDetail("dot", { ...far, pointed: true })).toBe("full");
    expect(plateDetail("dot", { ...far, selected: true })).toBe("full");
  });

  it("opens when the camera comes near", () => {
    expect(plateDetail("dot", { ...far, cameraDistance: PLATE_RANGE.camera.open - 0.1 })).toBe("full");
  });

  it("opens for the people round the person, even in the overview", () => {
    expect(plateDetail("dot", { ...far, personDistance: PLATE_RANGE.person.open - 0.1 })).toBe("full");
  });

  it("stays as it is inside the gap, so a plate at the threshold never flickers", () => {
    const between = { ...far, cameraDistance: (PLATE_RANGE.camera.open + PLATE_RANGE.camera.close) / 2 };
    expect(plateDetail("dot", between)).toBe("dot");
    expect(plateDetail("full", between)).toBe("full");
    const strolling = { ...far, personDistance: (PLATE_RANGE.person.open + PLATE_RANGE.person.close) / 2 };
    expect(plateDetail("dot", strolling)).toBe("dot");
    expect(plateDetail("full", strolling)).toBe("full");
  });

  it("changes once, not on every step, while someone paces across the threshold", () => {
    // An agent wandering between 4.4 m and 5.8 m from the person: inside the gap except at the near end.
    const path = [5.8, 5.2, 4.7, 4.4, 4.7, 5.2, 5.8, 5.2, 4.7, 4.4, 4.9, 5.8];
    let detail: PlateDetail = "dot";
    let changes = 0;
    for (const personDistance of path) {
      const next = plateDetail(detail, { ...far, personDistance });
      if (next !== detail) changes += 1;
      detail = next;
    }
    expect(changes).toBe(1);
    expect(detail).toBe("full");
  });

  it("closes again only beyond the far edge", () => {
    expect(plateDetail("full", { ...far, cameraDistance: PLATE_RANGE.camera.close + 0.1 })).toBe("dot");
    expect(plateDetail("full", { ...far, personDistance: PLATE_RANGE.person.close + 0.1 })).toBe("dot");
  });

  it("keeps a real gap on both ranges", () => {
    expect(PLATE_RANGE.camera.close - PLATE_RANGE.camera.open).toBeGreaterThanOrEqual(1);
    expect(PLATE_RANGE.person.close - PLATE_RANGE.person.open).toBeGreaterThanOrEqual(1);
  });
});
