/**
 * A figure's merged parts are baked again only when what it wears changes.
 * The level store takes a freshly parsed snapshot about once a minute; the
 * regalia built from it are then new JSX with the same content, and must not
 * make every dressed figure on the floor bake all its parts again.
 */
import { afterEach, describe, expect, it } from "vitest";
import { act, createRoot, extend, type ReconcilerRoot } from "@react-three/fiber";
import * as THREE from "three";
import type { Mesh, Object3D } from "three";
import { loadProfile, playerLook } from "./playerProfile";
import { PERSON_SUBJECT, type ProgressionSnapshot, type RewardRow } from "../progression/progressionApi";
import { useProgression } from "../progression/progressionStore";
import { regaliaFor, useDressedFigure } from "../progression/regalia/dress";
import { contentKey, ToyFigure, type FigureRegalia } from "./ToyFigure";

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

/** The merged meshes a figure is drawn with right now; a bake replaces every one of them. */
function merged(node: Object3D): Mesh[] {
  const out: Mesh[] = [];
  node.traverse((child) => { if ((child as Mesh).isMesh && child.userData.staticBatched && child.visible) out.push(child as Mesh); });
  return out;
}

const REWARDS: RewardRow[] = [
  { rewardId: "decoration_ribbon_bar", slot: "decoration", levels: { person: 3, agent: 3, pet: null } },
  { rewardId: "headwear_patrol_cap", slot: "headwear", levels: { person: 7, agent: null, pet: null } },
];
const BANDS = [{ level: 1, title: "private" }, { level: 2, title: "private_second_class" }, { level: 4, title: "private_first_class" }];

/** A snapshot as the server sends it: parsed afresh every time, so no array in it is ever the same object twice. */
function snapshot(level: number, xp: number): ProgressionSnapshot {
  return {
    subjects: [{ subjectId: PERSON_SUBJECT, kind: "person", xp, level, xpIntoLevel: 0, xpForNext: 90, title: "private_first_class" }],
    petId: "ember", recent: [], latestSeq: 0, maxLevel: 50, levelXp: [0, 40, 105, 195, 310, 450, 600, 760], rules: [],
    rewards: REWARDS.map((row) => ({ ...row, levels: { ...row.levels } })),
    titles: { person: BANDS.map((b) => ({ ...b })), agent: BANDS.map((b) => ({ ...b })), pet: BANDS.map((b) => ({ ...b })) },
    looks: { cap: 1, suit: 4, crown: 10 },
  };
}

const still = { current: { mode: "idle" as const, speed: 0 } };
const look = playerLook(loadProfile());

describe("a dressed figure", () => {
  it("does not bake its parts again when the level store takes an equal snapshot, and does when it wears something new", async () => {
    const seen: FigureRegalia[] = [];
    function Dressed() {
      const dressed = useDressedFigure("person", PERSON_SUBJECT, look);
      seen.push(dressed.regalia);
      return <ToyFigure look={dressed.look} regalia={dressed.regalia} drive={still} paused />;
    }
    useProgression.getState().hydrate(snapshot(4, 200), []);
    const figure = await render(<Dressed />);
    const first = merged(figure);
    expect(first.length).toBeGreaterThan(4);
    expect(seen[seen.length - 1].chest).toBeTruthy();

    // The minute's re-read: the same levels and rewards in new objects.
    await act(async () => { useProgression.getState().hydrate(snapshot(4, 200), []); });
    // The regalia are new JSX (which is what made the figure bake again)...
    expect(seen[seen.length - 1].chest).not.toBe(seen[0].chest);
    // ...with the same content, so every merged mesh is still the one from before.
    expect(merged(figure)).toHaveLength(first.length);
    expect(merged(figure).every((mesh, i) => mesh === first[i])).toBe(true);

    // A new rank and a cap: now the figure is baked again.
    await act(async () => { useProgression.getState().hydrate(snapshot(7, 700), []); });
    expect(seen[seen.length - 1].hat).toBeTruthy();
    const dressedAnew = merged(figure);
    expect(dressedAnew.some((mesh) => first.includes(mesh))).toBe(false);
  });

  it("names what is worn by its content, not by the JSX object", () => {
    const a = regaliaFor("private_first_class", { decoration: "decoration_ribbon_bar", headwear: "headwear_patrol_cap" });
    const b = regaliaFor("private_first_class", { decoration: "decoration_ribbon_bar", headwear: "headwear_patrol_cap" });
    expect(a.hat).not.toBe(b.hat);
    expect(contentKey([a.hat, a.chest, a.shoulder, a.sleeve])).toBe(contentKey([b.hat, b.chest, b.shoulder, b.sleeve]));
    const bare = regaliaFor("private_first_class", { decoration: "decoration_ribbon_bar" });
    expect(contentKey([bare.hat, bare.chest])).not.toBe(contentKey([a.hat, a.chest]));
    const other = regaliaFor("private", { decoration: "decoration_ribbon_bar", headwear: "headwear_patrol_cap" });
    expect(contentKey([other.hat, other.sleeve, other.shoulder])).not.toBe(contentKey([a.hat, a.sleeve, a.shoulder]));
    // Nothing worn has an empty name, whatever shape "nothing" takes.
    expect(contentKey([undefined, null, false])).toBe(contentKey([undefined, undefined, undefined]));
  });
});
