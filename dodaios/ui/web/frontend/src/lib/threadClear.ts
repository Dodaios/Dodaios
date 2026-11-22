/**
 * `/clear` in a coding thread starts its conversation over: the thread shows
 * empty and the agent's next turn opens a new conversation (the backend's
 * `thread_clear`). `/reset` and `/new` are the names Claude Code lists for it;
 * a name after the command becomes the thread's title.
 */
const CLEAR_COMMAND = /^\s*\/(?:clear|reset|new)(?:\s[\s\S]*)?$/;

/** Whether a typed message is the clear command, with or without a name. */
export function isClearCommand(text: string): boolean {
  return CLEAR_COMMAND.test(text);
}
