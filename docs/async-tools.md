# Slow tools as background jobs

A slow tool call (a long shell command, a browser task) does not hold the lead's
conversation. The call returns `{"started": true, "job_id": ...}` after a short
budget, the work goes on as a job in the jobs ledger, and its result arrives in
the conversation later as an event. The lead keeps answering new messages in the
meantime. Code: `dodaios/orchestrator/async_tools.py`; the hook is the one
`tool.execute` call in `dodaios/safety/tool_executor.py`, after approval.

## Behaviour

- **Fast calls are unchanged.** A call that ends inside the budget (default 20 s)
  returns its result as before. Nothing is written to the ledger.
- **Slow calls become jobs.** After the budget the call returns `started` with a
  `job_id`. The row (kind `async_tool`) is owned by the chat turn that made the
  call, and the work is registered as delegated work (ADR-0041): the turn is held
  until the job ends, or hands its seat to the next message, which is answered at
  once. When the job ends, its result is delivered as a continuation of the
  request that started it, marked as a background result. This is the same path
  on the brain seat and on CLI seats (their tools run through the MCP server).
- **Results are never lost.** The finished result is saved next to the ledger
  (`async_tool_results/<job_id>.json`) before the row closes, so a result that
  was finished but not yet delivered when the app restarted is still reported.
  Work that was still running when the app ended is reported `interrupted`, never
  `done`. A failed or raising tool ends as `failed` with a readable reason.
- **Stop.** `job_stop(job_id)` cancels the work (a shell command is killed) and
  the job ends `cancelled`. Pressing stop on the turn while the call is still
  inside its budget cancels it too. `job_status(ids, full=true)` returns the saved
  full result; the delivery to the conversation carries the first 4,000 characters.
- **Only where a result can arrive.** A call is backgrounded only from a chat
  turn that can receive a later result. A voice call, an unattended task or a
  worker keeps the synchronous contract.

## Opt-in per tool class

A tool is backgrounded when its name is in the list or it declares
`long_running = True` (optional `long_running_budget_s = <seconds>`).

- Default list: `run_shell`, `society_browser`.
- `DODAIOS_ASYNC_TOOLS`: a comma list that replaces the default; `off` empties it.
- `DODAIOS_ASYNC_TOOL_BUDGET_S`: the budget in seconds.
- Never wrapped: the job tools, and tools that already return a job id of their
  own (missions, artifacts, team threads, delegation, computer use).
