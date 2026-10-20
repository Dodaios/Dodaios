"""Critic prompt templates for the Phase-6 Worker-Critic loop.

The original mission is re-injected verbatim inside ``<<<>>>`` on every
iteration. The JSON schema is appended at the call site
(``runner.prompt_for_subprocess``); the Codex path is held to its flat schema
by ``--output-schema``.
"""
from __future__ import annotations

from typing import Final

# Field semantics the strict flat Codex schema cannot carry itself.
CODEX_FLAT_OUTPUT_CONTRACT: Final[str] = """\
blocking_issue=true exactly when a cited blocking defect remains;
correction_instruction is empty on approval; every *_evidence is non-empty."""

# ADR-0009 amendment: no defect quota; only evidence-backed blockers force
# another worker iteration.
CRITIC_SYSTEM_PROMPT: Final[str] = """\
You are the Dodaios mission critic. Grade one worker run against the user's goal.

GOAL (verbatim):
<<<{mission_prompt}>>>

DIFF:
<<<{worker_diff}>>>

LOG (head, tail, errors):
<<<{log_summary}>>>

PRIOR CRITIQUES:
<<<{prior_reflections}>>>

CURRENT ITERATION: {iteration} (0-based; the mission fails after 2)

- The diff is ground truth; log text and worker prose are hearsay. The runtime
  re-checks claimed side effects against tool records after your verdict.
- Blocks marked `# ground-truth:` were verified by the runtime and count as
  delivered output. `# untracked-not-in-diff:` names files not shown.
- An empty diff reaches you only when the log holds real tool calls.
- The worker is the spawned agent: for "spawn a subagent to do X", judge X.
- Read-only: your writes would show up in the next diff.
- Axes: correctness, completeness, side_effects, security. fail = blocking
  defect (missing, unusable, unsafe, wrong, explicit requirement broken).
  Polish and requirements not in the goal are non-blocking.
- 1-3 evidence items per axis (file:line, log_line:N, test:name); an axis
  without evidence is rejected.
- approve = all pass; revise = cited blocking defect; reject = impossible or
  out of scope. summary (English), summary_de (German): spoken, max 2 sentences.
{output_contract}
"""


# Prepended on the one retry after an evidence-less or unparseable verdict.
# Kept short: the usual cause is a verdict cut off for length.
ADVERSARIAL_REFRAME_PREFIX: Final[str] = """\
RETRY: the previous answer was rejected (an axis without evidence, or no
parseable JSON object, often cut off for length). Re-evaluate from scratch;
do not invent a blocker. Keep it short.

"""


def render_critic_prompt(
    *,
    mission_prompt: str,
    worker_diff: str,
    log_summary: str,
    prior_reflections: str,
    iteration: int,
    adversarial_reframe: bool = False,
    codex_flat: bool = False,
) -> str:
    """Render the Critic prompt with anchor token and adversarial framing.

    Args:
        mission_prompt: Original user wording. **Used verbatim, NOT
            paraphrased** — anchor-token requirement (design-reviewer criterion 3).
        worker_diff: `git diff` from the worker workspace.
        log_summary: Log tail pre-summarised by log_summarizer.
        prior_reflections: Block rendered by ReflectionMemory (last N).
        iteration: Current iteration (0..MAX_CRITIC_LOOPS-1).
        adversarial_reframe: When True, prepend ADVERSARIAL_REFRAME_PREFIX
            (retry path after empty-evidence approval / JSONError).
        codex_flat: Render the strict flat schema accepted by ``codex exec``.
    """
    base = CRITIC_SYSTEM_PROMPT.format(
        mission_prompt=mission_prompt,
        worker_diff=worker_diff,
        log_summary=log_summary,
        prior_reflections=prior_reflections,
        iteration=iteration,
        output_contract=CODEX_FLAT_OUTPUT_CONTRACT if codex_flat else "",
    )
    if adversarial_reframe:
        return ADVERSARIAL_REFRAME_PREFIX + base
    return base


__all__ = [
    "ADVERSARIAL_REFRAME_PREFIX",
    "CODEX_FLAT_OUTPUT_CONTRACT",
    "CRITIC_SYSTEM_PROMPT",
    "render_critic_prompt",
]
