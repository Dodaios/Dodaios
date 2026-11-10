import { describe, expect, it } from "vitest";

import { language, pickLanguage, setLanguage, t } from "./strings";
import { floatToPcm16, mono, resample } from "./audio";

describe("phone strings", () => {
  it("picks a known language from the phone's list, English otherwise", () => {
    expect(pickLanguage(["fr-FR", "de-DE"])).toBe("de");
    expect(pickLanguage(["pt-BR"])).toBe("pt");
    expect(pickLanguage(["zh-Hans-CN"])).toBe("zh");
    expect(pickLanguage(["fr"])).toBe("en");
    expect(pickLanguage([])).toBe("en");
  });

  it("reads the mobile.app namespace with fills and an English fallback", () => {
    setLanguage("de");
    expect(language()).toBe("de");
    expect(t("approve")).toBe("Erlauben");
    expect(t("approvals_waiting", { count: 2 })).toBe("2 warten auf deine Freigabe");
    expect(t("no_such_key")).toBe("no_such_key");
    setLanguage("en");
    expect(t("approve")).toBe("Allow");
  });
});

describe("voice note audio", () => {
  it("resamples and converts to int16", () => {
    const samples = new Float32Array([0, 0.5, 1, -1, -0.5, 0, 0.25, 0.75]);
    const down = resample(samples, 32_000, 16_000);
    expect(down.length).toBe(4);
    const pcm = new DataView(floatToPcm16(new Float32Array([0, 1, -1])));
    expect(pcm.getInt16(0, true)).toBe(0);
    expect(pcm.getInt16(2, true)).toBe(0x7fff);
    expect(pcm.getInt16(4, true)).toBe(-0x8000);
  });

  it("mixes channels down to one", () => {
    const left = new Float32Array([1, 0]);
    const right = new Float32Array([0, 1]);
    const mixed = mono({ numberOfChannels: 2, length: 2, getChannelData: (i) => (i === 0 ? left : right) });
    expect(Array.from(mixed)).toEqual([0.5, 0.5]);
  });
});
