import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProviderLogo, providerFamily } from "./ProviderLogo";
import deepseekLogo from "@/assets/providers/deepseek.svg?url";

afterEach(cleanup);

describe("ProviderLogo", () => {
  it("draws DeepSeek's own colour mark on the DeepSeek card", () => {
    expect(providerFamily("deepseek")).toBe("deepseek");
    render(<ProviderLogo providerId="deepseek" label="DeepSeek" />);
    const tile = screen.getByTestId("provider-logo-deepseek");
    expect(tile.getAttribute("data-family")).toBe("deepseek");
    expect(tile.querySelector("img")?.getAttribute("src")).toBe(deepseekLogo);
  });
});
