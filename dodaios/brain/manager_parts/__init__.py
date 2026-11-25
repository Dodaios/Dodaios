"""Mixins that make up BrainManager (see dodaios/brain/manager.py).

Importing the package first loads the manager, so the cycle manager -> part -> manager
always resolves in the same order.
"""
import dodaios.brain.manager  # noqa: F401
