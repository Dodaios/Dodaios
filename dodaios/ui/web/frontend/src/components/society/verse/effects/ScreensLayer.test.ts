import { describe, expect, it } from "vitest";
import { BoxGeometry, DoubleSide, Group, Mesh, MeshBasicMaterial, Vector3 } from "three";
import { BACKDROP_LAYER } from "../engine/renderOrder";
import { occluderClearance, terminalCanvasSize } from "./ScreensLayer";

function occluderBox(min: [number, number, number], max: [number, number, number]): Group {
  const size = max.map((v, i) => v - min[i]) as [number, number, number];
  const mesh = new Mesh(new BoxGeometry(...size), new MeshBasicMaterial({ side: DoubleSide }));
  mesh.position.set((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2);
  mesh.layers.set(BACKDROP_LAYER);
  const group = new Group();
  group.add(mesh);
  group.updateMatrixWorld(true);
  return group;
}

describe("screen placement", () => {
  // The engineering plate camera looks down at 60 degrees toward -z.
  const toCamera = new Vector3(0, Math.sqrt(3) / 2, 0.5);

  it("moves a screen inside its console's occluder just out of it, toward the camera", () => {
    // term_1: the occluder spans z 13.9..14.42, y 0.78..1.45 around the tilted glass.
    const box = occluderBox([6.68, 0.78, 13.9], [8.12, 1.45, 14.42]);
    const corners: [number, number, number][] = [[6.75, 1.415, 14.08], [8.05, 1.415, 14.08], [8.05, 0.89, 14.41], [6.75, 0.89, 14.41]];
    const lift = occluderClearance(corners, toCamera, box);
    // The middle of the tilted glass sits deepest: it sets the lift (top face y 1.45 from y 1.15).
    expect(lift).toBeGreaterThan(0.3);
    expect(lift).toBeLessThan(0.4);
  });

  it("leaves a screen outside every occluder where it is", () => {
    const box = occluderBox([0, 0, 0], [1, 1, 1]);
    expect(occluderClearance([[5, 5, 5], [6, 5, 5], [6, 4, 5], [5, 4, 5]], toCamera, box)).toBe(0);
    expect(occluderClearance([[5, 5, 5]], toCamera, undefined)).toBe(0);
  });

  it("gives terminal screens a sharp canvas within texture bounds", () => {
    expect(terminalCanvasSize(1.3, 0.62)).toEqual({ width: 1066, height: 508 });
    expect(terminalCanvasSize(9.4, 2.4)).toEqual({ width: 2048, height: 523 });
    expect(terminalCanvasSize(4.5, 2.1)).toEqual({ width: 2048, height: 956 });
  });
});
