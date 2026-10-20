/**
 * The character contract (public/verse/characters/characters.json, written by
 * the character pipeline) and the loader for its bodies and clips.
 *
 * Humans share one skeleton per body type and one clips file; drones carry
 * their clips in their own file. A body is loaded once and cloned per actor
 * with SkeletonUtils, so every crew member has its own skeleton and its own
 * materials (tinted per rank tier and accent) while sharing geometry.
 */
import { type AnimationClip, type Group, type Material, type Mesh, type Object3D, type Skeleton, type SkinnedMesh } from "three";
import { GLTFLoader, type GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

export type BodyKind = "officer" | "technician" | "trooper" | "drone" | "companion";
export type Tier = "deck" | "line" | "command" | "flag";

export interface ModelEntry {
  id: string;
  url: string;
  kind: BodyKind;
  /** Humans: the skeleton id whose shared clips file drives the body. */
  skeleton?: string;
  /** Drones: their own clips. */
  clips?: Record<string, { loop: boolean; seconds: number }>;
  materials: string[];
  height: number;
  hoverHeight?: number;
  driveSpeed?: number;
}

export interface SkeletonEntry {
  height: number;
  clips: string;
  walkSpeed: number | null;
}

export interface TierColours {
  M_Uniform: string;
  /** Breeches; older manifests leave it out and the tunic colour is used. */
  M_Trousers?: string;
  M_Trim: string;
  M_Cap: string;
  tile: string;
  cap: boolean;
}

export interface CharacterContract {
  version: number;
  seatHeight: number;
  /** Colour of an unlit rank-plate tile. */
  tileUnlit?: string;
  skeletons: Record<string, SkeletonEntry>;
  tiers: Record<Tier, TierColours>;
  models: ModelEntry[];
}

/** Walking pace when the contract does not say (m/s); a calm shipboard walk. */
export const DEFAULT_WALK_SPEED = 1.3;

export function contractUrl(): string {
  return `${import.meta.env.BASE_URL}verse/characters/characters.json`;
}

function assetUrl(relative: string): string {
  return `${import.meta.env.BASE_URL}${relative.replace(/^\/+/, "")}`;
}

/** A light shape check; a contract that fails it leaves the decks without people rather than broken. */
export function parseContract(json: unknown): CharacterContract {
  const c = json as Partial<CharacterContract> | null;
  if (!c || typeof c !== "object" || !Array.isArray(c.models) || !c.tiers || !c.skeletons) {
    throw new Error("characters.json: expected models, tiers and skeletons");
  }
  for (const m of c.models) {
    if (typeof m.id !== "string" || typeof m.url !== "string" || typeof m.kind !== "string") {
      throw new Error("characters.json: every model needs id, url and kind");
    }
  }
  for (const tier of ["deck", "line", "command", "flag"] as const) {
    if (!c.tiers[tier]) throw new Error(`characters.json: tier ${tier} missing`);
  }
  return c as CharacterContract;
}

export interface CharacterInstance {
  root: Group;
  /** Every clip the body can play, by name. */
  clips: ReadonlyMap<string, AnimationClip>;
  /** This instance's own materials, by material name. */
  materials: ReadonlyMap<string, Material[]>;
  meshes: readonly Mesh[];
  model: ModelEntry;
  walkSpeed: number;
}

export class CharacterLibrary {
  private readonly loader: GLTFLoader;
  private readonly gltfs = new Map<string, Promise<GLTF>>();

  constructor(readonly contract: CharacterContract) {
    this.loader = new GLTFLoader();
    this.loader.setMeshoptDecoder(MeshoptDecoder);
  }

  static async load(signal: AbortSignal): Promise<CharacterLibrary> {
    const res = await fetch(contractUrl(), { signal });
    if (!res.ok) throw new Error(`characters.json: HTTP ${res.status}`);
    return new CharacterLibrary(parseContract(await res.json()));
  }

  /** The body `prefer` names, else one of the kind's bodies chosen by `seed` (officers come in two builds). */
  model(kind: BodyKind, prefer?: string, seed = 0): ModelEntry | undefined {
    const named = prefer ? this.contract.models.find((m) => m.id === prefer) : undefined;
    if (named) return named;
    const all = this.contract.models.filter((m) => m.kind === kind);
    return all.length ? all[seed % all.length] : undefined;
  }

  private gltf(url: string): Promise<GLTF> {
    let pending = this.gltfs.get(url);
    if (!pending) {
      pending = this.loader.loadAsync(assetUrl(url));
      this.gltfs.set(url, pending);
      pending.catch(() => this.gltfs.delete(url));
    }
    return pending;
  }

  /** A fresh, independently animated and tinted copy of a body. */
  async instantiate(model: ModelEntry): Promise<CharacterInstance> {
    const body = await this.gltf(model.url);
    const skeleton = model.skeleton ? this.contract.skeletons[model.skeleton] : undefined;
    const clipSource = skeleton?.clips ? await this.gltf(skeleton.clips).catch(() => null) : null;
    const clips = new Map<string, AnimationClip>();
    for (const clip of [...body.animations, ...(clipSource?.animations ?? [])]) clips.set(clip.name, clip);
    const root = cloneSkinned(body.scene) as Group;
    const materials = new Map<string, Material[]>();
    const meshes: Mesh[] = [];
    root.traverse((o: Object3D) => {
      const mesh = o as Mesh;
      if (!mesh.isMesh) return;
      meshes.push(mesh);
      mesh.frustumCulled = false;
      const own = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map((m) => m.clone());
      mesh.material = Array.isArray(mesh.material) ? own : own[0];
      for (const m of own) {
        const list = materials.get(m.name) ?? [];
        list.push(m);
        materials.set(m.name, list);
      }
    });
    return { root, clips, materials, meshes, model, walkSpeed: skeleton?.walkSpeed ?? model.driveSpeed ?? DEFAULT_WALK_SPEED };
  }
}

/** Free what is this instance's own: its materials and its cloned skeletons (each has a bone texture on the GPU). */
export function disposeInstance(instance: CharacterInstance): void {
  for (const list of instance.materials.values()) for (const m of list) m.dispose();
  const skeletons = new Set<Skeleton>();
  for (const mesh of instance.meshes) if ((mesh as SkinnedMesh).isSkinnedMesh) skeletons.add((mesh as SkinnedMesh).skeleton);
  for (const skeleton of skeletons) skeleton.dispose();
}
