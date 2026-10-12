import { useEffect, useMemo } from "react";
import { BoxGeometry, Color, InstancedMesh, Matrix4, MeshStandardMaterial } from "three";
import { creatureBody, creatureCubes, creaturePose, GRID, type CreatureLook } from "./creature";

/**
 * A pixel creature in the Verse: the same cubes the profile face paints, as
 * one instanced mesh standing on the ground and facing +z like the shapes.
 * It is built once per look and holds its resting pose.
 */
export function CreatureModel({ creature, sizeM }: { creature: CreatureLook; sizeM: number }) {
  const { seed, palette, eyes } = creature;
  const resources = useMemo(() => {
    const body = creatureBody({ seed, palette, eyes });
    // Frame 5 of the idle loop: eyes open, looking ahead.
    const cubes = creatureCubes(body, creaturePose("idle", 5));
    // A full grid stands as tall as a shape; a shorter creature keeps its cube size.
    const cube = sizeM / GRID;
    const geometry = new BoxGeometry(1, 1, 1);
    const material = new MeshStandardMaterial({ roughness: 0.7 });
    const mesh = new InstancedMesh(geometry, material, cubes.length);
    mesh.castShadow = true;
    mesh.frustumCulled = false;
    const matrix = new Matrix4();
    const colour = new Color();
    cubes.forEach((entry, index) => {
      matrix.makeScale(cube, cube, cube);
      matrix.setPosition((entry.x - 4) * cube, (body.bottom - entry.y + 0.5) * cube, entry.z * cube);
      mesh.setMatrixAt(index, matrix);
      mesh.setColorAt(index, colour.setRGB(entry.color[0] / 255, entry.color[1] / 255, entry.color[2] / 255, "srgb"));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    return { mesh, geometry, material };
  }, [seed, palette, eyes, sizeM]);
  useEffect(() => () => {
    resources.mesh.dispose();
    resources.geometry.dispose();
    resources.material.dispose();
  }, [resources]);
  return <primitive object={resources.mesh} dispose={null} />;
}
