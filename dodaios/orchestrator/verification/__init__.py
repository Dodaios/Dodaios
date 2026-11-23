"""What became of a coding run the lead handed to an agent, on record.

A *run* is one order given to one coding thread, from the moment it is sent to
the moment its work is settled. ``verification.db`` is the authoritative record
of runs: which repository and commit a run started from, which model and CLI
version it ran on, and every step taken on it. Everything derived from runs
(scores, policy decisions) lives in ``dodaios.rsi`` and only reads this record.

:mod:`recorder` notes a run when a thread takes an order and judges it when the
thread's turn ends. It always runs; whether a run is held for its verdict is
the run's coding policy's question. A failure in it never touches the turn it
describes.
"""
