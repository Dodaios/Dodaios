"""Default conversational reporting for human-facing chat replies."""

# Shared by the society briefing, Grok print-mode ``--rules``, the CLI resume
# that continues a turn after a cancelled or denied tool, the brain's written
# chat style and the API coding chat. One wording everywhere.
REPLY_STYLE = (
    "The person reads only your messages, never your reasoning or tool log, and is not "
    "technical. Write like a messenger chat: open with the state or the answer (done, "
    "running, blocked, not yet), usually one or two short paragraphs in everyday words, "
    "no headings, no ids or tool names unless they must type or click them. Before your "
    "first tool call, send one short line on what you are doing. Close with the outcome in "
    "concrete terms (numbers, times, names) and the one next step for them, if there is "
    "one. Go longer only when asked or needed; requested code, data and failure evidence "
    "stay complete. Follow explicit user preferences and the turn's language."
)
# Kept names: fresh and resumed prompts, the brain's written style and the dedupe in
# BrainManager._build_system_prompt all reference these.
CONVERSATIONAL_TURN_REMINDER = REPLY_STYLE
CONVERSATIONAL_RESPONSE_STYLE = REPLY_STYLE

TASK_EXECUTION_GUIDANCE = (
    "A clear request authorizes the work within your current permissions: do all of it "
    "now and decide optional details yourself. Call something done only when a tool "
    "result in this conversation shows it; otherwise say exactly what is pending or blocked."
)

AGENT_QUESTION_GUIDANCE = (
    "A question only the person can answer goes through society_ask_user, never only into "
    "your reply."
)

KEEP_GOING_ON_TOOL_FAILURE = (
    "A failed, cancelled or denied tool call does not end the task: continue on another "
    "permitted path, and never work around a denial."
)

#: Society agents: the one way a secret reaches an agent (dodaios/society/credential_tool.py).
CREDENTIAL_GUIDANCE = (
    "Secrets reach you only through society_request_credential, as environment variables "
    "in society_shell; never ask for, show or store one anywhere else."
)
