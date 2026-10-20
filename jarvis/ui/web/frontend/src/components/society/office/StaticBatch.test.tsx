import { afterEach, describe, expect, it } from "vitest";
import { act, createRoot, extend, type ReconcilerRoot } from "@react-three/fiber";
import * as THREE from "three";
import { Box3, BoxGeometry, InstancedMesh, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry, type Mesh, type Object3D } from "three";
import { StaticBatch } from "./StaticBatch";

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

extend(THREE);

let root: ReconcilerRoot<HTMLCanvasElement> | null = null;

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
  // A local: an earlier test's root lets go of its own group late, and must not clear this one.
  let captured: Object3D | null = null;
  await act(async () => { current.render(<group ref={(g) => { if (g) captured = g; }}>{element}</group>); });
  if (!captured) throw new Error("the element did not mount");
  return captured;
}

afterEach(() => {
  root?.unmount();
  root = null;
});

const box = new BoxGeometry(1, 1, 1);
const small = new BoxGeometry(0.1, 0.1, 0.1);
const oak = new MeshStandardMaterial({ color: "#d9bf97", roughness: 0.6 });
const oakish = new MeshStandardMaterial({ color: "#b89b74", roughness: 0.55 });
const steel = new MeshStandardMaterial({ color: "#23262b", roughness: 0.45, metalness: 0.5 });
const glass = new MeshStandardMaterial({ color: "#d6ecff", transparent: true, opacity: 0.3 });
const glow = new MeshStandardMaterial({ color: "#fff0d8", emissive: "#fff0d8", emissiveIntensity: 1.5 });
const flatPaint = new MeshBasicMaterial({ color: "#ff0000" });

const drawn = (node: Object3D) => { const out: Mesh[] = []; node.traverseVisible((c) => { if ((c as Mesh).isMesh) out.push(c as Mesh); }); return out; };
const all = (node: Object3D) => { const out: Mesh[] = []; node.traverse((c) => { if ((c as Mesh).isMesh) out.push(c as Mesh); }); return out; };
const triangles = (meshes: Mesh[]) => meshes.reduce((sum, m) => sum + (m.geometry.index ? m.geometry.index.count : m.geometry.getAttribute("position").count) / 3, 0);

function Shelf({ x }: { x: number }) {
  return (
    <group position={[x, 0, 0]} name={`shelf:${x}`}>
      <mesh geometry={box} material={oak} position={[0, 0.5, 0]} castShadow receiveShadow />
      <mesh geometry={box} material={oakish} position={[0, 1.6, 0]} scale={[1, 0.1, 1]} castShadow receiveShadow />
      <mesh geometry={box} material={steel} position={[0.4, 1, 0]} scale={[0.05, 2, 0.05]} castShadow receiveShadow />
      <mesh geometry={small} material={oak} position={[0, 1.7, 0]} castShadow receiveShadow />
      <mesh geometry={box} material={glass} position={[0, 1, 0.5]} scale={[1, 1, 0.02]} />
      <mesh geometry={box} material={glow} position={[0, 2, 0]} scale={[1, 0.02, 0.05]} />
    </group>
  );
}

describe("static batch", () => {
  it("draws many parts as a few merged meshes with the same shape, and hides the parts", async () => {
    const group = await render(<StaticBatch signature="a"><Shelf x={0} /><Shelf x={3} /><Shelf x={6} /></StaticBatch>);
    group.updateMatrixWorld(true);
    const parts = all(group).filter((m) => !m.userData.staticBatched || !m.visible);
    const merged = drawn(group);
    expect(parts).toHaveLength(18);
    expect(parts.every((m) => !m.visible)).toBe(true);
    // Oak and its near twin share a finish; steel is more metallic; the tiny box no longer casts; glass and glow keep their materials.
    expect(merged).toHaveLength(5);
    expect(triangles(merged)).toBe(18 * 12);
    // Same extent as the parts had.
    const extent = new Box3().setFromObject(group);
    expect(extent.min.x).toBeCloseTo(-0.5, 6);
    expect(extent.max.x).toBeCloseTo(6.5, 6);
    expect(extent.min.y).toBeCloseTo(0, 6);
    expect(extent.max.y).toBeCloseTo(2.01, 6);
    // The glowing strip is still drawn with the very material object someone may pulse; so is the glass.
    expect(merged.some((m) => m.material === glow)).toBe(true);
    expect(merged.some((m) => m.material === glass)).toBe(true);
    // Plain parts share a white material and carry their own colour in the vertices.
    const plain = merged.filter((m) => (m.material as MeshStandardMaterial).vertexColors);
    expect(plain).toHaveLength(3);
    for (const mesh of plain) {
      expect((mesh.material as MeshStandardMaterial).color.getHexString()).toBe("ffffff");
      expect(mesh.geometry.getAttribute("color")).toBeDefined();
    }
    const wood = plain.find((m) => m.castShadow && (m.material as MeshStandardMaterial).metalness === 0)!;
    const colour = wood.geometry.getAttribute("color");
    expect(colour.getX(0)).toBeCloseTo(oak.color.r, 6);
    // The second part in that mesh is the darker oak.
    expect(colour.getX(36)).toBeCloseTo(oakish.color.r, 6);
    // Shadows: the big parts cast, the hand-sized one does not, receiving is kept.
    const tiny = plain.find((m) => !m.castShadow)!;
    expect(triangles([tiny])).toBe(3 * 12);
    expect(plain.every((m) => m.receiveShadow)).toBe(true);
    // A merged mesh never takes a click meant for a part.
    expect(merged.every((m) => m.userData.staticBatched)).toBe(true);
  });

  it("leaves alone what it cannot bake, and what someone hid", async () => {
    const instanced = new InstancedMesh(box, oak, 4);
    const group = await render(
      <StaticBatch signature="a">
        <mesh geometry={box} material={oak} />
        <mesh geometry={box} material={[oak, steel] as unknown as MeshStandardMaterial} name="multi" />
        <mesh geometry={box} material={flatPaint} name="basic" />
        <mesh geometry={box} material={oak} visible={false} name="hidden" />
        <group visible={false}><mesh geometry={box} material={oak} name="in-hidden-group" /></group>
        <primitive object={instanced} />
      </StaticBatch>,
    );
    const names = drawn(group).map((m) => m.name || (m.userData.staticBatched ? "merged" : (m as unknown as InstancedMesh).isInstancedMesh ? "instanced" : "part"));
    // The plain box is merged (alone), the basic-material one too (by its own material); the rest draw themselves or stay hidden.
    expect(names.sort()).toEqual(["instanced", "merged", "merged", "multi"]);
    expect(all(group).find((m) => m.name === "hidden")!.visible).toBe(false);
  });

  it("keeps flat sheets apart when asked, for pieces that get a silhouette rim", async () => {
    const sheet = new PlaneGeometry(1, 1);
    const group = await render(
      <StaticBatch signature="a" keepFlat>
        <mesh geometry={box} material={oak} />
        <mesh geometry={box} material={oak} position={[2, 0, 0]} />
        <mesh geometry={sheet} material={oak} name="sheet" />
      </StaticBatch>,
    );
    const meshes = drawn(group);
    expect(meshes).toHaveLength(2);
    expect(meshes.find((m) => m.name === "sheet")!.geometry).toBe(sheet);
  });

  it("keeps a jointed thing's shadow whole when asked: small parts still cast, and a finish is one mesh", async () => {
    const parts = (
      <>
        <mesh geometry={small} material={oak} castShadow />
        <mesh geometry={small} material={oakish} position={[0, 0.1, 0]} castShadow />
        <mesh geometry={small} material={oak} position={[0, 0.2, 0]} />
      </>
    );
    // By default a part a hand wide casts nothing, and what casts is kept apart from what does not.
    const plain = drawn(await render(<StaticBatch signature="a">{parts}</StaticBatch>));
    expect(plain.map((m) => m.castShadow)).toEqual([false]);
    root?.unmount();
    root = null;
    const whole = drawn(await render(<StaticBatch signature="a" castAsOne>{parts}</StaticBatch>));
    expect(whole).toHaveLength(1);
    expect(whole[0].castShadow).toBe(true);
    expect(triangles(whole)).toBe(3 * 12);
  });

  it("rebuilds when its content changes and gives the parts back when it goes", async () => {
    const first = await render(<StaticBatch signature="a"><Shelf x={0} /></StaticBatch>);
    expect(drawn(first)).toHaveLength(5);
    const second = await render(<StaticBatch signature="b"><Shelf x={0} /><Shelf x={3} /></StaticBatch>);
    const merged = drawn(second);
    expect(merged).toHaveLength(5);
    expect(triangles(merged)).toBe(12 * 12);
    // No merged mesh of the first bake is left behind.
    expect(all(second).filter((m) => m.userData.staticBatched && m.visible)).toHaveLength(5);
  });
});
