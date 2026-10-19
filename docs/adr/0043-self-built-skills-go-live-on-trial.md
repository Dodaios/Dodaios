# ADR-0043 — Skills the self-building loop proved go live on trial

**Status:** Accepted · **Date:** 2026-10-19

## Context

Two rules assume that a person approves every skill a model wrote before it
can run:

- MASTERPLAN §6.7: agents may draft skills, and "a visible approval flow
  (model card → Learned skills) is the only path to active".
- AP-SM6 (`docs/self_mod.md` §7): generated skills are forced to `draft`, the
  trigger matcher skips drafts, and only the person promotes one.

The self-building loop (`docs/self-build.md`) builds skills on its own
initiative from what the person keeps doing. Under the two rules every such
skill would wait as a draft that the person has to find and activate, so the
loop could never take work off them without first asking, and the "trial,
measure, keep or archive" cycle would have nothing to measure.

The rules exist for good reasons. Unverified self-written skills make agents
worse, not better: in SkillsBench (2026) self-generated skills scored 1.3
points below no skills at all. What works in the literature keeps only
artefacts whose success was checked (Voyager's critic, Agent Workflow Memory,
ReasoningBank), and the checker must stay out of the builder's reach (the
Darwin Gödel Machine learned to game its own). <!-- i18n-allow: a proper name -->

## Decision

1. **One narrow exception.** A skill may go from `draft` to `active` without
   the person's click when all of the following hold:
   - it was made by the trusted self-build service (`dodaios/self_build/`),
     which runs at the scheduler's privilege and is not a tool any agent or
     chat can call;
   - it passed the judge (`dodaios/self_build/judge.py`): a replay of the
     person's own past requests through the production skill router
     (`dodaios.skills.eval_harness.route`) catches at least two thirds of
     them and fires on none of the person's other recent requests, the
     skill validator, the pre-promote lint and the duplicate check pass, and
     it needs only tools the assistant used for those requests;
   - `[self_build].skill` is `trial` or `full`, or the person accepted the
     build's card (which is itself the visible approval §6.7 asks for).
2. **Every other path keeps the old rule.** Skills from an agent's own
   review, from a chat or voice request (`create-skill`, the creator dialog,
   `spawn_skill_author`) still land as drafts and wait for the person. The
   writer still renders `state: draft`; the builder then calls the
   registry's own `promote`, which runs the same pre-promote lint as a
   person's click. No new write path to skills exists.
3. **Live means on trial, not kept.** The skill carries the `self-built` tag,
   has a ledger record that says why it exists and how it was checked, and
   is undone with one click. Its uses are counted from real runs
   (`SkillInvoked`) and corrections right after them; a trial that is not
   used is archived (switched off, restorable), and only at autonomy `full`
   is a used one kept without the person.
4. **The judge is not the builder.** The judge is deterministic Python that
   takes the finished skill and the person's recorded turns; no model output
   decides whether a skill passes, and the builder has no way to change what
   is checked. A failed proof records the lesson, and the same build is not
   tried again.

## Consequences

- With the shipped defaults (`skill = "suggest"`, seven silent days) nothing
  changes for a person until they raise the autonomy or accept a card.
- A self-built skill can be wrong in a way the replay does not catch (it
  routes correctly but its steps do a poor job). The trial bounds that: it is
  labelled, counted, corrected-against and archived when it does not help.
- The replay only proves routing and form. Executing the steps in a sandbox
  would prove more but needs the full agent loop with tools; that is left
  for a later change and the trial carries the risk meanwhile.
- MASTERPLAN §6.7 and AP-SM6 now name this exception.

## References

- SkillsBench (2026): self-generated skills score below no skills.
- Wang et al., *Voyager* (2023): a critic verifies a skill before it enters
  the library.
- Wang et al., *Agent Workflow Memory* (2024); Ouyang et al., *ReasoningBank*
  (2025): keep checked workflows, learn from failures too.
- Zhang et al., *Darwin Gödel Machine* (2025): a self-improving agent edited <!-- i18n-allow: a proper name -->
  its own checker; keep the judge out of the builder's reach.
