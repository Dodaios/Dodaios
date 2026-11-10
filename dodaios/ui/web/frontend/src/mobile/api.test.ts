import { describe, expect, it, vi } from "vitest";

import { ApiError, MobileApi, TOKEN_KEY, Unpaired, pairingCodeFromHash, type Storage } from "./api";

function storage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
  };
}

function reply(status: number, body: unknown): Response {
  return { status, ok: status < 300, json: async () => body } as Response;
}

describe("MobileApi", () => {
  it("reads the pairing code from the fragment only", () => {
    expect(pairingCodeFromHash("#pair=abcde23456")).toBe("ABCDE23456");
    expect(pairingCodeFromHash("#x=1&pair=ZZ")).toBe("ZZ");
    expect(pairingCodeFromHash("")).toBe("");
    expect(pairingCodeFromHash("?pair=NO")).toBe("");
  });

  it("refuses to call the phone routes without a token", async () => {
    const api = new MobileApi(storage(), vi.fn());
    await expect(api.me()).rejects.toBeInstanceOf(Unpaired);
  });

  it("keeps the token from a redeemed code and sends it as a Bearer", async () => {
    const store = storage();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/mobile/pair/redeem") {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ code: "ABCDE23456", name: "iPhone" });
        return reply(200, { token: "mdt_secret", assistant_name: "Nova", device: {} });
      }
      expect(new Headers(init?.headers).get("authorization")).toBe("Bearer mdt_secret");
      return reply(200, { assistant_name: "Nova", push_key: "k", push_subscribed: false, device: {} });
    });
    const api = new MobileApi(store, fetchMock as unknown as typeof fetch);
    expect((await api.pair("ABCDE23456", "iPhone")).assistant_name).toBe("Nova");
    expect(store.getItem(TOKEN_KEY)).toBe("mdt_secret");
    expect((await api.me()).assistant_name).toBe("Nova");
  });

  it("forgets the token on a 401 and reports other errors with their detail", async () => {
    const store = storage();
    store.setItem(TOKEN_KEY, "mdt_old");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(409, { detail: "a turn is already running" }))
      .mockResolvedValueOnce(reply(401, { detail: "This phone is not paired." }));
    const api = new MobileApi(store, fetchMock as unknown as typeof fetch);
    await expect(api.sendMessage("x")).rejects.toMatchObject({ status: 409, message: "a turn is already running" });
    await expect(api.lead()).rejects.toBeInstanceOf(Unpaired);
    expect(store.getItem(TOKEN_KEY)).toBeNull();
  });

  it("a failed pairing keeps no token and carries the server's reason", async () => {
    const store = storage();
    const fetchMock = vi.fn().mockResolvedValue(reply(401, { detail: "This pairing code is wrong or has expired." }));
    const api = new MobileApi(store, fetchMock as unknown as typeof fetch);
    await expect(api.pair("WRONG", "Phone")).rejects.toBeInstanceOf(ApiError);
    expect(store.getItem(TOKEN_KEY)).toBeNull();
  });

  it("posts a voice note as raw PCM with its sample rate", async () => {
    const store = storage();
    store.setItem(TOKEN_KEY, "mdt_x");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe("/api/mobile/app/lead/voice-note?sample_rate=16000&language=de");
      expect(new Headers(init?.headers).get("content-type")).toBe("application/octet-stream");
      expect(init?.body).toBeInstanceOf(ArrayBuffer);
      return reply(200, { text: "Hallo" });
    });
    const api = new MobileApi(store, fetchMock as unknown as typeof fetch);
    expect((await api.voiceNote(new ArrayBuffer(32), "de")).text).toBe("Hallo");
  });
});
