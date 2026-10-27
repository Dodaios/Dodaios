import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import en from "@/i18n/locales/society/en.json";

vi.mock("@/i18n", () => ({
  useLocaleChunk: () => true,
  useUiLanguage: () => "en",
  useI18nStore: { getState: () => ({ ui: "en" }) },
  useT: () => (key: string) => key.split(".").reduce<unknown>((value, part) => (value as Record<string, unknown>)?.[part], en) as string ?? key,
}));

import { TriggerBuilder } from "../TriggerBuilder";

afterEach(cleanup);

test("the trigger editor reads the schedule back as a sentence while typing", () => {
  render(<QueryClientProvider client={new QueryClient()}>
    <TriggerBuilder timeOnly initialValue={{ type: "cron", expression: "0 9 * * 1", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }} onChange={() => {}} />
  </QueryClientProvider>);
  expect(screen.getByTestId("trigger-preview").textContent).toMatch(/^Weekly on Monday at 09:00/);
  fireEvent.change(screen.getByDisplayValue("0 9 * * 1"), { target: { value: "*/15 * * * *" } });
  expect(screen.getByTestId("trigger-preview").textContent).toBe("Every 15 minutes");
});
