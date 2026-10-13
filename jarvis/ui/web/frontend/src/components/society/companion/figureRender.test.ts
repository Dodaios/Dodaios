// @vitest-environment node
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ACCESSORY_CATALOG, ACCESSORY_ITEMS } from "./accessories";
import { COMPANION_SHAPES } from "./appearance";
import { meshesByName, readGlb } from "./figureGlb";
import { renderFigure, shadeFigure, traceFigure } from "./figureRender";
import { figureFaceMatrix, figureKey, figureParts, figureTraceKey, type FigureLook } from "./figureScene";

const ASSETS = path.resolve(__dirname, "../../../assets/society/companions");
function load(name: string) {
  const file = fs.readFileSync(path.join(ASSETS, name));
  return meshesByName(readGlb(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength) as ArrayBuffer));
}
const bodies = load("companions.glb");
const worn = load("accessories.glb");
const look = (extra: Partial<FigureLook> = {}): FigureLook => ({ shape: "squircle", color: "#00a591", eyes: "lines", accessories: {}, ...extra });
const pixel = (image: { size: number; data: Uint8ClampedArray }, x: number, y: number) => {
  const at = (Math.round(y) * image.size + Math.round(x)) * 4;
  return [image.data[at]!, image.data[at + 1]!, image.data[at + 2]!, image.data[at + 3]!] as const;
};

describe("companion models", () => {
  it.each(COMPANION_SHAPES)("holds a body and both eye kinds for %s", shape => {
    expect(bodies.get(`${shape}.Body`)?.length).toBeGreaterThan(0);
    for (const kind of ["Dots", "Lines"]) for (const side of [0, 1]) expect(bodies.get(`${shape}.${kind}.${side}`)?.length).toBe(1);
  });

  it("holds every catalog item for every shape", () => {
    for (const item of ACCESSORY_ITEMS) for (const shape of COMPANION_SHAPES) {
      const meshes = [worn.get(`acc_${item.id}__${shape}__fit`), worn.get(`acc_${item.id}`), worn.get(`acc_${item.id}__${shape}`)];
      expect(meshes.some(Boolean), `${item.id} on ${shape}`).toBe(true);
    }
  });

  it("refuses a file that is not binary glTF", () => {
    expect(() => readGlb(new ArrayBuffer(64))).toThrow();
  });
});

describe("3D profile faces", () => {
  it.each(COMPANION_SHAPES)("draws %s inside its square, in its own colour", shape => {
    const image = renderFigure(figureParts(look({ shape }), bodies), 48);
    let solid = 0;
    for (let y = 0; y < 48; y++) for (let x = 0; x < 48; x++) {
      const [, , , alpha] = pixel(image, x, y);
      if (alpha > 200) solid++;
      // The figure never touches the edge; only its faint shadow may reach it.
      if (x === 0 || y === 0 || x === 47 || y === 47) expect(alpha).toBeLessThan(120);
    }
    expect(solid).toBeGreaterThan(48 * 48 * 0.2);
    // Teal body: green leads, red trails, wherever the middle of the body is lit.
    const meta = ACCESSORY_CATALOG.shapes[shape];
    const [a, b, c, d, e, f] = figureFaceMatrix(look({ shape }), bodies, image.frame);
    const [red, green, , alpha] = pixel(image, a * 20 + c * (meta.eyeY + 5) + e, b * 20 + d * (meta.eyeY + 5) + f);
    expect(alpha).toBe(255);
    expect(green).toBeGreaterThan(red + 40);
  });

  it("puts the ink eyes where the face matrix says, and leaves them out for a blind figure", () => {
    const seeing = look(), image = renderFigure(figureParts(seeing, bodies), 96);
    const [a, b, c, d, e, f] = figureFaceMatrix(seeing, bodies, image.frame);
    const eyeY = ACCESSORY_CATALOG.shapes.squircle.eyeY;
    for (const eyeX of [15.4, 24.6]) {
      const [red, green, blue] = pixel(image, a * eyeX + c * eyeY + e, b * eyeX + d * eyeY + f);
      expect(Math.max(red, green, blue)).toBeLessThan(60);
    }
    const blind = renderFigure(figureParts(look({ blind: true }), bodies), 96);
    const [, green] = pixel(blind, a * 15.4 + c * eyeY + e, b * 15.4 + d * eyeY + f);
    expect(green).toBeGreaterThan(100);
  });

  it("shades one trace in any colour without changing its outline", () => {
    const teal = figureParts(look(), bodies), red = figureParts(look({ color: "#dd2233" }), bodies);
    const trace = traceFigure(teal, 40);
    const first = shadeFigure(trace, teal), second = shadeFigure(trace, red);
    const mid = (40 * 24 + 16) * 4;
    expect(first.data[mid + 1]).toBeGreaterThan(first.data[mid]!);
    expect(second.data[mid]).toBeGreaterThan(second.data[mid + 1]!);
    for (let at = 3; at < first.data.length; at += 4) expect(second.data[at]).toBe(first.data[at]);
    expect(figureTraceKey(look(), 40)).toBe(figureTraceKey(look({ color: "#dd2233" }), 40));
    expect(figureKey(look(), 40)).not.toBe(figureKey(look({ color: "#dd2233" }), 40));
  });

  it("makes room for what the figure wears", () => {
    const bare = renderFigure(figureParts(look(), bodies, worn), 64);
    const hat = renderFigure(figureParts(look({ accessories: { head: "top_hat" } }), bodies, worn), 64);
    // A tall hat shrinks the body instead of leaving the picture.
    expect(hat.frame.k).toBeLessThan(bare.frame.k);
    for (let x = 0; x < 64; x++) expect(pixel(hat, x, 0)[3]).toBeLessThan(120);
  });

  it("paints a colour design across the body", () => {
    const skin = { colors: ["#ff0000", "#0000ff"], radial: false, angle: 180, effect: 0, highlight: "#ff0000" };
    const image = renderFigure(figureParts(look({ skin }), bodies), 64);
    const [a, b, c, d, e, f] = figureFaceMatrix(look(), bodies, image.frame);
    const top = pixel(image, a * 20 + c * 9 + e, b * 20 + d * 9 + f), bottom = pixel(image, a * 20 + c * 31 + e, b * 20 + d * 31 + f);
    // 180 degrees runs from the top (first colour) to the bottom (last colour).
    expect(top[0]).toBeGreaterThan(top[2]);
    expect(bottom[2]).toBeGreaterThan(bottom[0]);
  });

  it("draws nothing for an empty figure", () => {
    expect(renderFigure([], 16).data.every(value => value === 0)).toBe(true);
  });
});
