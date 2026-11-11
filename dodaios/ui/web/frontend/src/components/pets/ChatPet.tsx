/**
 * The user's pet in the main chat. Off (`[ui] pet_chat`) draws nothing.
 * No query client (an isolated test) keeps the pet, which is the default.
 */
import { useContext, type ReactNode } from "react";
import { QueryClientContext, useQuery } from "@tanstack/react-query";

import { petKeys } from "@/hooks/usePets";
import { fetchPets } from "@/lib/petsApi";

export function ChatPet({ children }: { children: ReactNode }) {
  const client = useContext(QueryClientContext);
  if (!client) return <>{children}</>;
  return <ChatPetQuery>{children}</ChatPetQuery>;
}

function ChatPetQuery({ children }: { children: ReactNode }) {
  const { data } = useQuery({
    queryKey: petKeys.all,
    queryFn: fetchPets,
    staleTime: Infinity,
  });
  if (data?.chat === false) return null;
  return <>{children}</>;
}
