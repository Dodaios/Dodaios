/**
 * Development only: force a crew member's duty status from the console
 * (`__verse.setDuty(id, "working")`, `__verse.setDuty(id, null)` to let go),
 * so crew life can be checked on a quiet roster. Production builds never read
 * it.
 */
import { create } from "zustand";
import type { DutyStatus } from "../ranks";

interface DevDuty {
  duty: Readonly<Record<string, DutyStatus>>;
  setDuty: (id: string, status: DutyStatus | null) => void;
}

export const useDevDuty = create<DevDuty>((set) => ({
  duty: {},
  setDuty: (id, status) => set((s) => {
    const duty = { ...s.duty };
    if (status) duty[id] = status;
    else delete duty[id];
    return { duty };
  }),
}));
