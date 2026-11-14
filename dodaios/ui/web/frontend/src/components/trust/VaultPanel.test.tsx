import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { envNameFor } from "@/lib/trustApi";
import { VaultPanel } from "./VaultPanel";

const KINDS = ["api_key", "token", "client_id", "client_secret", "password", "connection_string", "webhook_url", "private_key", "other"];

function vault(secrets: unknown[] = [], logins: unknown[] = []) {
  return { secrets, logins, kinds: KINDS };
}

function stub(responses: (url: string, init?: RequestInit) => unknown) {
  const calls: { method: string; url: string; body: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url: String(input), body: String(init?.body ?? "") });
    return new Response(JSON.stringify(responses(String(input), init)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("envNameFor", () => {
  it("turns a label into the name the assistant uses", () => {
    expect(envNameFor("Google AI Studio API key")).toBe("GOOGLE_AI_STUDIO_API_KEY");
    expect(envNameFor("Café crème key!")).toBe("CAFE_CREME_KEY");
    expect(envNameFor("1Password token")).toBe("SECRET_1PASSWORD_TOKEN");
    expect(envNameFor("  ")).toBe("");
  });
});

describe("Trust: vault", () => {
  it("lists secrets by name and kind, never by value", async () => {
    stub(() => vault([
      { env: "GOOGLE_AI_STUDIO_API_KEY", label: "Google AI Studio API key", kind: "api_key", note: "PR checks", created_ms: 1, updated_ms: 1, present: true },
      { env: "STRIPE_SECRET", label: "Stripe", kind: "client_secret", created_ms: 1, updated_ms: 1, present: false },
    ], [{ key: "github", label: "GitHub", url: "https://github.com/login", domain: "github.com", created_ms: 1, updated_ms: 1 }]));
    await loadLocaleChunk("trust");
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getAllByTestId("vault-secret")).toHaveLength(2));
    const first = screen.getAllByTestId("vault-secret")[0].textContent ?? "";
    expect(first).toContain("Google AI Studio API key");
    expect(first).toContain("API key");
    expect(first).toContain("GOOGLE_AI_STUDIO_API_KEY");
    expect(first).toContain("PR checks");
    expect(screen.getAllByTestId("vault-secret-missing")).toHaveLength(1);
    expect(screen.getByTestId("vault-login").textContent).toContain("github.com");
  });

  it("adds a secret: the value goes one way, under the name derived from its label", async () => {
    let saved = false;
    const calls = stub((_url, init) => {
      if (init?.method === "PUT") {
        saved = true;
        return { ok: true, secret: { env: "GOOGLE_AI_STUDIO_API_KEY" } };
      }
      return saved
        ? vault([{ env: "GOOGLE_AI_STUDIO_API_KEY", label: "Google AI Studio API key", kind: "api_key", created_ms: 1, updated_ms: 1, present: true }])
        : vault();
    });
    await loadLocaleChunk("trust");
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByTestId("vault-secrets-empty")).toBeTruthy());
    fireEvent.click(screen.getByTestId("vault-add-secret"));
    fireEvent.change(screen.getByTestId("vault-secret-label"), { target: { value: "Google AI Studio API key" } });
    const value = screen.getByTestId("vault-secret-value") as HTMLInputElement;
    expect(value.type).toBe("password");
    fireEvent.change(value, { target: { value: "AIzaSy-test-value" } });
    expect((screen.getByTestId("vault-secret-env") as HTMLInputElement).value).toBe("GOOGLE_AI_STUDIO_API_KEY");
    fireEvent.click(screen.getByTestId("vault-secret-save"));
    await waitFor(() => expect(screen.getAllByTestId("vault-secret")).toHaveLength(1));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toBe("/api/trust/vault/secrets/GOOGLE_AI_STUDIO_API_KEY");
    expect(JSON.parse(put?.body ?? "{}")).toMatchObject({ value: "AIzaSy-test-value", kind: "api_key" });
    expect(document.body.textContent).not.toContain("AIzaSy-test-value");
  });

  it("asks once more before it deletes", async () => {
    const calls = stub(() => vault([
      { env: "GH_TOKEN", label: "GitHub token", kind: "token", created_ms: 1, updated_ms: 1, present: true },
    ]));
    await loadLocaleChunk("trust");
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByTestId("vault-secret")).toBeTruthy());
    fireEvent.click(screen.getByTestId("vault-secret-delete"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByTestId("vault-secret-delete"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/trust/vault/secrets/GH_TOKEN")).toBe(true));
  });
});
