import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { UrgentCallCard } from "./UrgentCallCard";
import type { UrgentCallSettings } from "@/lib/remindersApi";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
afterEach(cleanup);

const OFF: UrgentCallSettings = {
  enabled: false,
  events: { approval: true, question: true, watchdog: true },
  keywords: [],
  deadline_min: 15,
  max_per_day: 3,
  escalate_after_min: 5,
  route: "desktop",
  phone_number: "",
};

it("ships off and turns on only by the owner's switch", () => {
  const save = vi.fn();
  render(<UrgentCallCard value={OFF} saving={false} onSave={save} />);
  expect((screen.getByTestId("notify-urgent-event-approval") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByTestId("notify-urgent-enabled"));
  expect(save).toHaveBeenCalledWith({ urgent_call: { enabled: true } });
});

it("saves a number when the field is left and a route on click", () => {
  const save = vi.fn();
  render(<UrgentCallCard value={{ ...OFF, enabled: true }} saving={false} onSave={save} />);
  const cap = screen.getByTestId("notify-urgent-max_per_day");
  fireEvent.change(cap, { target: { value: "5" } });
  fireEvent.blur(cap);
  expect(save).toHaveBeenCalledWith({ urgent_call: { max_per_day: 5 } });
  fireEvent.click(screen.getByTestId("notify-urgent-route-phone"));
  expect(save).toHaveBeenCalledWith({ urgent_call: { route: "phone" } });
});

it("does not save a malformed phone number", () => {
  const save = vi.fn();
  render(<UrgentCallCard value={{ ...OFF, enabled: true, route: "phone" }} saving={false} onSave={save} />);
  const phone = screen.getByTestId("notify-urgent-phone");
  fireEvent.change(phone, { target: { value: "0151 123" } });
  fireEvent.blur(phone);
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toBe("notify.urgent_phone_invalid");
  fireEvent.change(phone, { target: { value: "+49 151 1234567" } });
  fireEvent.blur(phone);
  expect(save).toHaveBeenCalledWith({ urgent_call: { phone_number: "+491511234567" } });
});
