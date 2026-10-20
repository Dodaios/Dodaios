/**
 * A studio's lettering shows a name the person typed. Each wall owns its
 * lettering and lets go of it: renaming, creating and deleting teams all
 * session long must leave exactly one texture per wall on screen.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, createRoot, extend, type ReconcilerRoot } from "@react-three/fiber";
import * as THREE from "three";
import type { Mesh, MeshStandardMaterial, Object3D } from "three";
import { AgentsDepartment } from "./AgentsFloorLook";
import { buildOfficeLayout, type Department, type OfficeAgentInput } from "./officeLayout";

/** Just enough of a WebGLRenderer for R3F to mount a scene graph without a GPU. */
function fakeRenderer(canvas: HTMLCanvasElement) {
  const noop = () => undefined;
  return {
    domElement: canvas,
    render: noop, setSize: noop, setPixelRatio: noop, setAnimationLoop: noop, dispose: noop,
    getPixelRatio: () => 1,
    shadowMap: { enabled: false, type: 0, needsUpdate: false },
    xr: { enabled: false, isPresenting: false, addEventListener: noop, removeEventListener: noop, setAnimationLoop: noop },
    outputColorSpace: "srgb", toneMapping: 0, toneMappingExposure: 1,
    info: { render: {}, memory: {} },
  };
}

/**
 * A 2D context that accepts every call and draws nothing: jsdom has no canvas, and without a context no texture
 * is made at all. Measuring text answers a fixed width, a gradient takes its stops.
 */
function inertContext(): CanvasRenderingContext2D {
  const gradient = { addColorStop: () => undefined };
  return new Proxy({}, {
    get: (_target, prop) => {
      if (prop === "measureText") return () => ({ width: 10 });
      if (prop === "createLinearGradient" || prop === "createRadialGradient") return () => gradient;
      if (prop === "createImageData") return (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h });
      return () => undefined;
    },
    set: () => true,
  }) as CanvasRenderingContext2D;
}

extend(THREE);

const realGetContext = HTMLCanvasElement.prototype.getContext;
beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = (() => inertContext()) as unknown as typeof HTMLCanvasElement.prototype.getContext;
});
afterAll(() => {
  HTMLCanvasElement.prototype.getContext = realGetContext;
});

let root: ReconcilerRoot<HTMLCanvasElement> | null = null;
let scene: Object3D | null = null;

/** Render into one root, so a second call updates what the first one mounted. */
async function render(element: JSX.Element): Promise<Object3D> {
  if (!root) {
    const canvas = document.createElement("canvas");
    root = createRoot(canvas);
    root.configure({
      // Test double: R3F only needs the renderer's shape here, nothing is drawn.
      gl: fakeRenderer(canvas) as unknown as NonNullable<Parameters<typeof root.configure>[0]>["gl"],
      frameloop: "never",
      size: { width: 100, height: 100, top: 0, left: 0 },
    });
  }
  const current = root;
  await act(async () => { current.render(<group ref={(g) => { if (g) scene = g; }}>{element}</group>); });
  if (!scene) throw new Error("the element did not mount");
  return scene;
}

afterEach(() => {
  root?.unmount();
  root = null;
  scene = null;
});

const staff: OfficeAgentInput[] = Array.from({ length: 6 }, (_, i) => ({
  agentId: `a${i + 1}`, name: `Agent ${i + 1}`, tier: "specialist", providerLabel: "Codex", state: "idle", createdMs: i,
}));
const studio: Department = buildOfficeLayout(staff, { teams: [{ id: "g1", name: "Launch crew", members: ["a1", "a2", "a3"], createdMs: 1 }] })
  .departments.find((d) => d.teamId === "g1")!;

/** The wall's lettering: the one cut-out, textured sheet on it. */
function lettering(node: Object3D): MeshStandardMaterial {
  const found: MeshStandardMaterial[] = [];
  node.traverse((child) => {
    const material = (child as Mesh).isMesh ? ((child as Mesh).material as MeshStandardMaterial) : null;
    if (material?.isMeshStandardMaterial && material.alphaTest > 0.25 && material.alphaTest < 0.35) found.push(material);
  });
  expect(found).toHaveLength(1);
  return found[0];
}

describe("a studio's lettering", () => {
  it("belongs to its wall: a renamed team's old lettering is disposed, texture and all, and the last one with the studio", async () => {
    let made = 0, gone = 0, texturesGone = 0;
    const seen = new Set<MeshStandardMaterial>();
    const watch = (material: MeshStandardMaterial) => {
      if (seen.has(material)) return material;
      seen.add(material);
      made += 1;
      material.addEventListener("dispose", () => { gone += 1; });
      expect(material.map).toBeTruthy();
      material.map!.addEventListener("dispose", () => { texturesGone += 1; });
      return material;
    };
    const first = watch(lettering(await render(<AgentsDepartment dept={studio} />)));
    // The same name again draws nothing new.
    expect(lettering(await render(<AgentsDepartment dept={{ ...studio }} />))).toBe(first);
    expect([made, gone]).toEqual([1, 0]);

    // Forty renames: forty new letterings, each replacing the one before.
    for (let i = 0; i < 40; i += 1) {
      const next = watch(lettering(await render(<AgentsDepartment dept={{ ...studio, label: `Launch crew ${i}` }} />)));
      expect(next).not.toBe(first);
      expect(made - gone, `rename ${i}`).toBe(1);
      expect(texturesGone).toBe(gone);
    }
    expect(made).toBe(41);

    // The team is deleted: its studio goes, and its lettering with it.
    await act(async () => { root?.unmount(); });
    root = null;
    expect([gone, texturesGone]).toEqual([41, 41]);
  });
});
