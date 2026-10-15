import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  NewPersonalTask,
  PersonalTask,
  PersonalTaskChanges,
  PersonalTaskList,
} from "@/types/today";

const TASKS_KEY = ["today", "tasks"] as const;
const BASE = "/api/today/tasks";

/** The server's reason as one sentence: FastAPI sends a string or a list of field errors. */
async function unwrap<T>(res: Response): Promise<T> {
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const detail = body.detail;
    if (typeof detail === "string") throw new Error(detail);
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item === "object" ? (item as { msg?: unknown }).msg : null))
        .filter((msg): msg is string => typeof msg === "string");
      if (messages.length) throw new Error(messages.join("; "));
    }
    throw new Error(`HTTP ${res.status}`);
  }
  return body as T;
}

async function fetchTasks(): Promise<PersonalTaskList> {
  return unwrap<PersonalTaskList>(await fetch(`${BASE}?view=all`));
}

function send(path: string, method: string, body?: unknown): Promise<Response> {
  return fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const taskPath = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

/**
 * Every task (open first, in Today order, then done). Refreshed every 15 s and
 * on focus, so a task added by voice or chat shows up without a reload.
 */
export function useTodayTasks() {
  return useQuery({
    queryKey: TASKS_KEY,
    queryFn: fetchTasks,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
}

export function useTodayTaskActions() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: TASKS_KEY });
  const options = { onSettled: refresh };

  const add = useMutation({
    mutationFn: async (task: NewPersonalTask) =>
      unwrap<PersonalTask>(await send(BASE, "POST", task)),
    ...options,
  });
  const update = useMutation({
    mutationFn: async ({ id, changes }: { id: string; changes: PersonalTaskChanges }) =>
      unwrap<PersonalTask>(await send(taskPath(id), "PATCH", changes)),
    ...options,
  });
  const complete = useMutation({
    mutationFn: async (id: string) =>
      unwrap<PersonalTask>(await send(`${taskPath(id)}/complete`, "POST")),
    ...options,
  });
  const reopen = useMutation({
    mutationFn: async (id: string) =>
      unwrap<PersonalTask>(await send(`${taskPath(id)}/reopen`, "POST")),
    ...options,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap<{ id: string; deleted: boolean }>(await send(taskPath(id), "DELETE")),
    ...options,
  });

  return { add, update, complete, reopen, remove };
}
