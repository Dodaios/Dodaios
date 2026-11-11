import { describe, expect, it } from "vitest";
import { setVoiceInputLevel } from "@/lib/voiceInputLevel";
import { clearVoiceOutputLevel, setVoiceOutputLevel } from "@/lib/voiceOutputLevel";
import {
  compilePetShader,
  shaderSourceError,
  shaderVoiceLevel,
  stepShaderBlend,
  wrapPetFragment,
  type ShaderBlend,
} from "./shaderPet";

const SOURCE = "void main() { gl_FragColor = vec4(uState, uTime, 0.0, 1.0); }\n";

describe("shader pet", () => {
  it("rejects the same constructs the loader rejects", () => {
    expect(shaderSourceError(SOURCE)).toBeNull();
    expect(shaderSourceError("void main() { while (true) {} }")).toMatch(/while/);
    expect(shaderSourceError("void main() { sampler2D tex; }")).toMatch(/sampler/);
    expect(shaderSourceError("void main() { for (int i = 0; i < n; i++) {} }")).toMatch(/for loop/);
    expect(shaderSourceError("void main() { for (int i = 0; i < 32; i++) { for (int k = 0; k < 5; k++) {} } }")).toBeNull();
    expect(shaderSourceError("void main() { for (int i = 0; j < 8; i++) {} }")).toMatch(/for loop/);
    expect(shaderSourceError("void main() { for (int i = 0; i < 4; i++) { i = 0; } }")).toMatch(/counter/);
    expect(shaderSourceError("void main() { for (int i = 0; i < 32; i++) { for (int k = 0; k < 32; k++) {} } }")).toMatch(/160/);
    expect(shaderSourceError("void main() { wh\\\nile (true) {} }")).toMatch(/while/);
    expect(shaderSourceError("void main() {}\n#undef uState\n")).toMatch(/#undef/);
  });

  it("reports a missing WebGL context instead of a successful compile", () => {
    expect(compilePetShader(SOURCE)).toMatch(/WebGL/);
  });

  it("calls the author's main twice and mixes the two colours", () => {
    const wrapped = wrapPetFragment(SOURCE);
    expect(wrapped).toContain("void petMain(");
    expect(wrapped).not.toContain("void main() { gl_FragColor");
    expect(wrapped).toContain("uStateFrom");
    expect(wrapped).toContain("uniform float uLevel");
    expect(wrapped).toContain("uniform float uLevelFrom");
    expect(wrapped.indexOf("petLevel = uLevelFrom;")).toBeLessThan(wrapped.indexOf("petMain();"));
    expect(wrapped).toContain("mix(petFrom, gl_FragColor");
  });

  it("follows the assistant while talking and the microphone while listening", () => {
    setVoiceOutputLevel(0.7);
    setVoiceInputLevel(0.4, "native", 1_000);
    expect(shaderVoiceLevel("talking", 1_000)).toBe(0.7);
    expect(shaderVoiceLevel("listening", 1_000)).toBe(0.4);
    expect(shaderVoiceLevel("idle", 1_000)).toBe(0);
    expect(shaderVoiceLevel("thinking", 1_000)).toBe(0);
    clearVoiceOutputLevel();
    expect(shaderVoiceLevel("talking", 1_000)).toBe(0);
  });

  it("mixes from the state on screen to the next one, then rests there", () => {
    const blend: ShaderBlend = { from: 0, to: 0, blend: 1 };
    stepShaderBlend(blend, 1, 0.1, false);
    expect(blend.from).toBe(0);
    expect(blend.to).toBe(1);
    expect(blend.blend).toBeCloseTo(0.1 / 0.33);
    stepShaderBlend(blend, 1, 1, false);
    expect(blend.blend).toBe(1);
    stepShaderBlend(blend, 1, 0.2, true);
    expect(blend.blend).toBe(1);
  });
});
