"""Measured self-improvement of how Dodaios hands work to coding agents.

This package holds what is DERIVED from delegated coding runs: how a run is
tagged (domain, repository, harness), and later the scores and policy
decisions computed from those tags. The runs themselves are recorded by
``dodaios.orchestrator.verification``, which owns ``verification.db``; this
package only ever reads that file.

The tagging helpers here (:mod:`domains`, :mod:`repo_identity`,
:mod:`harness_probe`) are pure functions without a store of their own, so the
recorder can call them when a run starts.
"""
