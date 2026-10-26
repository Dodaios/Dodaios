/**
 * The viewmodel's draw in the eye view's post chain: after the deck's render
 * pass, into the same (multisampled HDR) target, depth cleared first, so the
 * arms get the deck's anti-aliasing, bloom and tone mapping and never meet
 * its walls. No full-screen pass of its own; with nothing to draw it skips.
 */
import type { WebGLRenderer, WebGLRenderTarget } from "three";
import { Pass } from "three/examples/jsm/postprocessing/Pass.js";
import type { ViewmodelDraw } from "../runtime";

export class ViewmodelPass extends Pass {
  /** What to draw this frame (null or invisible: nothing). */
  draw: ViewmodelDraw | null = null;

  constructor() {
    super();
    this.needsSwap = false;
    this.clear = false;
  }

  override render(renderer: WebGLRenderer, _writeBuffer: WebGLRenderTarget, readBuffer: WebGLRenderTarget): void {
    const vm = this.draw;
    if (!vm?.visible) return;
    drawViewmodel(renderer, vm, this.renderToScreen ? null : readBuffer);
  }
}

/** Clear depth on `target` (null: the screen) and draw the viewmodel over what is there. */
export function drawViewmodel(renderer: WebGLRenderer, vm: ViewmodelDraw, target: WebGLRenderTarget | null): void {
  const autoClear = renderer.autoClear;
  renderer.setRenderTarget(target);
  renderer.autoClear = false;
  renderer.clearDepth();
  renderer.render(vm.scene, vm.camera);
  renderer.autoClear = autoClear;
}
