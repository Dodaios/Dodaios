"""The kernel of the assistant's self-improvement: what measures, decides and records.

The assistant changes its own behaviour all the time (parameters, lessons,
skills, how it briefs coding agents). This package is the part that says
whether a change made it better, and the assistant can never change it
(``dodaios/rsi/*`` is a core path of the self-change registry). What proposes
changes lives outside, in the learners. See docs/self-improvement.md.

Shared shapes:

* :mod:`overlay` the state a benchmark run computes under instead of the live one;
* :mod:`fingerprint` which assistant produced a result;
* :mod:`bench.model` a task, its split, a result;
* :mod:`gate.evidence` what the gate found about a change;
* :mod:`storage` the kernel's files, with a schema version that survives app updates.

The first thing built here measures how work is handed to coding agents. The
runs themselves are recorded by ``dodaios.orchestrator.verification``, which
owns ``verification.db``; the tagging helpers (:mod:`domains`,
:mod:`repo_identity`, :mod:`harness_probe`) are pure functions the recorder
calls when a run starts, and the scores and policy decisions are derived from
those tags.
"""
