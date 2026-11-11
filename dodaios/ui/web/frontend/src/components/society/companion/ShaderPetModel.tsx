/**
 * One uploaded fragment shader on a sphere. A state change mixes the
 * previous colour into the next over SHADER_BLEND_S.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { ShaderMaterial } from "three";
import type { PetMood } from "./petRig";
import { PET_STATES, type PetState } from "@/lib/petStates";
import {
  PET_VERTEX_SHADER,
  shaderStateIndex,
  shaderVoiceLevel,
  stepShaderBlend,
  wrapPetFragment,
  type ShaderBlend,
} from "./shaderPet";

const MOOD_STATE: Record<PetMood, PetState> = {
  idle: "idle", work: "working", talk: "talking", sleep: "sleeping",
};

export function ShaderPetModel({ source, heightM, reduced, paused, state, drive, opaque = false }: {
  source: string;
  heightM: number;
  reduced: boolean;
  paused: boolean;
  state?: PetState;
  drive?: { current: { mood: PetMood } };
  /** The pet page draws a solid sphere so the card shows through the corners. */
  opaque?: boolean;
}) {
  const material = useMemo(() => new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uState: { value: 0 },
      uStateFrom: { value: 0 },
      uBlend: { value: 1 },
      uLevel: { value: 0 },
      uLevelFrom: { value: 0 },
    },
    vertexShader: PET_VERTEX_SHADER,
    fragmentShader: wrapPetFragment(source),
    transparent: !opaque,
    depthWrite: opaque,
    toneMapped: false,
  }), [source, opaque]);
  const time = useRef(0);
  const blend = useRef<ShaderBlend>({ from: 0, to: 0, blend: 1 });
  useEffect(() => () => material.dispose(), [material]);
  useFrame((_, delta) => {
    const step = Math.min(delta, 0.05);
    const name = state ?? MOOD_STATE[drive?.current.mood ?? "idle"];
    stepShaderBlend(blend.current, shaderStateIndex(name), reduced || paused ? 0 : step, reduced);
    if (!reduced && !paused) time.current += step;
    material.uniforms.uTime.value = time.current;
    material.uniforms.uStateFrom.value = blend.current.from;
    material.uniforms.uState.value = blend.current.to;
    material.uniforms.uBlend.value = blend.current.blend;
    const fromName: PetState = PET_STATES[blend.current.from] ?? "idle";
    const toName: PetState = PET_STATES[blend.current.to] ?? name;
    material.uniforms.uLevelFrom.value = shaderVoiceLevel(fromName);
    material.uniforms.uLevel.value = shaderVoiceLevel(toName);
  });
  return (
    <mesh material={material} scale={heightM}>
      <sphereGeometry args={[0.5, 64, 48]} />
    </mesh>
  );
}

/** A worn shader pet: load the fragment the pack saved, then draw it. */
export function ShaderPet({ url, heightM, reduced, paused, drive }: {
  url: string;
  heightM: number;
  reduced: boolean;
  paused: boolean;
  drive?: { current: { mood: PetMood } };
}) {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setSource(null);
    void fetch(url)
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error("missing"))))
      .then((text) => { if (live) setSource(text); })
      .catch(() => { if (live) setSource(null); });
    return () => { live = false; };
  }, [url]);
  if (!source) return null;
  return <ShaderPetModel source={source} heightM={heightM} reduced={reduced} paused={paused} drive={drive} />;
}
