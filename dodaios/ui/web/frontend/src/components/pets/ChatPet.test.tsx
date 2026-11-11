import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatPet } from "@/components/pets/ChatPet";

function show(chat?: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["pets"], { active: "gigi", pets: [], ...(chat === undefined ? {} : { chat }) });
  return render(
    <QueryClientProvider client={client}>
      <ChatPet>
        <span data-testid="chat-pet">pet</span>
      </ChatPet>
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("ChatPet", () => {
  it("stays visible when the setting is absent", () => {
    show();
    expect(screen.getByTestId("chat-pet")).toBeTruthy();
  });

  it("hides the pet when the setting is off", () => {
    show(false);
    expect(screen.queryByTestId("chat-pet")).toBeNull();
  });
});
