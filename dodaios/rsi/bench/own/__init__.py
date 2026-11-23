"""Benchmark tasks from the person's own memory and messages.

The seed suite is an invented person. What the assistant should be good at is
this person: their memories, the way they ask. So an installation builds its
own recall tasks, at night, in two ways:

* **questions** (:mod:`questions`): for a memory, a model writes two messages
  the person might send that need exactly that memory. The gold is known by
  construction.
* **messages** (:mod:`messages`): real messages the person sent to the
  assistant, with the stored memories that could matter. A model says which of
  them the message needs, or none. It is asked twice with the candidates in
  another order, and a message counts only when both answers agree. This is
  where the true mix comes from: most messages need no memory at all.

Both run against a copy of the memory taken that night (:mod:`world`), never
against the live one.

What leaves the machine, and where to: the memories and messages go to the
provider the person's assistant already answers on, on its subscription, and
to no one else (:class:`dodaios.memory.learning.review.ModelReviewer` with
``allow_metered=False``). Memories marked sensitive are never sent. A key that
bills per token is never used: without a subscription or a local model no
tasks are made, and the nights stay quiet.

Forgetting reaches the tasks. When a memory is forgotten or replaced, every
task that names it is retired and its text is erased (:mod:`maker`).
"""
