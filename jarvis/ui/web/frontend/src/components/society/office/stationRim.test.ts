import { describe, expect, it } from "vitest";
import { BackSide, BoxGeometry, Group, InstancedMesh, Mesh, MeshBasicMaterial, PlaneGeometry, Scene } from "three";
import { attachRim, attachedTo, createRimMaterial, detachRim, rimTargets } from "./stationRim";

function prop() {
  const root = new Group();
  root.name = "prop:reception-desk";
  const counter = new Mesh(new BoxGeometry(2, 1, 0.8), new MeshBasicMaterial());
  const wall = new Mesh(new BoxGeometry(2.6, 2.2, 0.1), new MeshBasicMaterial());
  // A drawn face, a hidden hit box and an instanced detail: none of them has a silhouette to rim.
  const face = new Mesh(new PlaneGeometry(1, 0.6), new MeshBasicMaterial());
  const hidden = new Mesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial());
  hidden.visible = false;
  const slats = new InstancedMesh(new BoxGeometry(0.05, 2, 0.05), new MeshBasicMaterial(), 12);
  const inner = new Group();
  inner.add(wall, face);
  root.add(counter, inner, hidden, slats);
  return { root, counter, wall, face, hidden, slats };
}

describe("station rim", () => {
  it("draws only back faces, so the object hides all of it but its edge", () => {
    const material = createRimMaterial();
    expect(material.side).toBe(BackSide);
    expect(material.depthWrite).toBe(false);
    expect(material.uniforms.rimOpacity.value).toBe(0);
  });

  it("wraps the solid, visible meshes of an object and nothing else", () => {
    const { root, counter, wall } = prop();
    expect(rimTargets(root)).toEqual([counter, wall]);
  });

  it("puts a shell on each of them that shares their geometry and takes no clicks", () => {
    const { root, counter, wall } = prop();
    const material = createRimMaterial();
    const shells = attachRim(root, material);
    expect(shells.map((shell) => shell.parent)).toEqual([counter, wall]);
    expect(shells[0]!.geometry).toBe(counter.geometry);
    expect(shells.every((shell) => shell.material === material && !shell.castShadow)).toBe(true);
    const hits: unknown[] = [];
    shells[0]!.raycast(undefined as never, hits as never);
    expect(hits).toEqual([]);
    // Lighting it a second time must not rim the rim.
    expect(rimTargets(root)).toEqual([counter, wall]);
  });

  it("leaves the object exactly as it was when the rim comes off", () => {
    const { root, counter, wall } = prop();
    const before = [counter.children.length, wall.children.length];
    const shells = attachRim(root, createRimMaterial());
    detachRim(shells);
    expect([counter.children.length, wall.children.length]).toEqual(before);
    expect(shells.every((shell) => shell.parent === null)).toBe(true);
  });

  it("notices an object that was rebuilt and left the scene", () => {
    const scene = new Scene();
    const { root, wall } = prop();
    scene.add(root);
    expect(attachedTo(wall, scene)).toBe(true);
    scene.remove(root);
    expect(attachedTo(wall, scene)).toBe(false);
  });
});
