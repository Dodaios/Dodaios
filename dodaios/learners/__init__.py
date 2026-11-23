"""The learners: what proposes changes to the assistant (docs/self-improvement.md).

A learner looks at practice tasks and at what happened, and proposes a change.
It decides nothing: the kernel (``dodaios/rsi``) measures every proposal and
lets it in or not. So a learner can be wrong, greedy or naive without harm,
and it lives outside the kernel on purpose: it is itself something that can be
improved later.

What a learner gets from the kernel is narrow: practice tasks, and a function
that tries values on them. It never sees a task the assistant is graded on,
never a result of the gate, and never the registry.
"""
