/**
 * Space only through glass (docs/verse/realtime.md, "Outside the hull").
 *
 * Runs after the deck: marks the glass, draws space behind it (spaceView's
 * `renderBehind`, only on pixels the deck left empty), then paints the hull.
 *
 * The decks were built for a camera looking down at 60 degrees: above a
 * viewport's header, behind a beam or where a ceiling stops short there can
 * be open gaps that the plate never saw. The old star cards filled them; with
 * real space behind the deck they would look out of the ship. After the deck
 * is drawn, the glass (GLASS_LAYER) marks its pixels in the stencil where it
 * is in front of the deck, and every pixel the deck left empty that no glass
 * covers is painted the dark of the hull.
 *
 * Two draws in all: every render into the multisampled target resolves it,
 * and resolving (stencil above all) is slow on Direct3D, so the glass goes
 * in one draw through its own layer, never one draw per mesh.
 */
import {
  AlwaysStencilFunc, BufferAttribute, BufferGeometry, Color, DoubleSide, KeepStencilOp, LessEqualDepth, Mesh,
  MeshBasicMaterial, NotEqualStencilFunc, OrthographicCamera, PerspectiveCamera, ReplaceStencilOp, ShaderMaterial,
  type Material, type Scene, type WebGLRenderer, type WebGLRenderTarget,
} from "three";
import { GLASS_LAYER } from "../renderOrder";
import type { SpaceView } from "./spaceView";
import { Pass } from "three/examples/jsm/postprocessing/Pass.js";

/** Linear radiance of the hull in the gaps: near black, like a deep shadow. */
const HULL = new Color(0.004, 0.0045, 0.005);

const FILL_VERTEX = /* glsl */ `
void main() {
  // On the far plane: only pixels the deck left empty (depth still 1) pass.
  gl_Position = vec4( position.xy, 1.0, 1.0 );
}
`;

const FILL_FRAGMENT = /* glsl */ `
uniform vec3 hull;
void main() {
  gl_FragColor = vec4( hull, 1.0 );
}
`;

export class HullMask {
  /** Whether the deck has any glass; without any, every gap is hull. */
  enabled = false;
  private readonly maskCamera = new PerspectiveCamera();
  private readonly mark = new MeshBasicMaterial({
    colorWrite: false,
    depthWrite: false,
    depthTest: true,
    side: DoubleSide,
    stencilWrite: true,
    stencilRef: 1,
    stencilFunc: AlwaysStencilFunc,
    stencilZPass: ReplaceStencilOp,
  });
  private readonly fill: Mesh;
  private readonly fillCamera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);

  constructor() {
    const material = new ShaderMaterial({
      vertexShader: FILL_VERTEX,
      fragmentShader: FILL_FRAGMENT,
      uniforms: { hull: { value: HULL } },
      depthTest: true,
      depthWrite: false,
      depthFunc: LessEqualDepth,
      stencilWrite: true,
      stencilRef: 1,
      stencilFunc: NotEqualStencilFunc,
      stencilFail: KeepStencilOp,
      stencilZFail: KeepStencilOp,
      stencilZPass: KeepStencilOp,
      stencilWriteMask: 0,
    });
    const tri = new BufferGeometry();
    tri.setAttribute("position", new BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3));
    this.fill = new Mesh(tri, material);
    this.fill.frustumCulled = false;
  }

  /** Draws into the bound target, which must hold the deck's depth and have a stencil buffer. */
  draw(renderer: WebGLRenderer, scene: Scene, camera: PerspectiveCamera, space: SpaceView): void {
    const autoClear = renderer.autoClear;
    renderer.autoClear = false;
    renderer.clearStencil();
    this.maskCamera.copy(camera);
    this.maskCamera.layers.set(GLASS_LAYER);
    const override = scene.overrideMaterial;
    const background = scene.background;
    if (this.enabled) {
      scene.overrideMaterial = this.mark;
      scene.background = null;
      renderer.render(scene, this.maskCamera);
      scene.overrideMaterial = override;
      scene.background = background;
    }
    space.renderBehind(renderer);
    renderer.render(this.fill, this.fillCamera);
    renderer.autoClear = autoClear;
  }

  dispose(): void {
    this.mark.dispose();
    (this.fill.material as Material).dispose();
    this.fill.geometry.dispose();
  }
}

/** After the deck: space through the glass, hull dark in the other gaps. */
export class HullMaskPass extends Pass {
  constructor(
    private readonly mask: HullMask,
    private readonly scene: Scene,
    private readonly camera: PerspectiveCamera,
    private readonly space: SpaceView,
  ) {
    super();
    this.needsSwap = false;
  }

  render(renderer: WebGLRenderer, _writeBuffer: WebGLRenderTarget, readBuffer: WebGLRenderTarget): void {
    renderer.setRenderTarget(this.renderToScreen ? null : readBuffer);
    this.mask.draw(renderer, this.scene, this.camera, this.space);
  }
}
