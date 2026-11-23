"""The pet a fresh install shows.

Lives in core because ``UIConfig.pet_id`` defaults to it; the pets' own
vocabulary (``dodaios.ui.pets.states``) and every pet module read it from here.
"""

from __future__ import annotations

#: The pet a fresh install shows.
DEFAULT_PET_ID: str = "gigi"
