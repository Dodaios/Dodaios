"""The verse host: the backend side of the Unreal Verse (``verse.bridge/1``).

``Verse.exe`` is a supervised child of the desktop process. This package
launches and watches it (:mod:`.supervisor`), checks the machine can run it
(:mod:`.probe`), serves the one WebSocket it talks to (:mod:`.bridge`) and
turns backend state and bus events into bridge topics (:mod:`.relays`).

The frozen contract is ``docs/verse/unreal/contracts/bridge-protocol.md``;
the process model is ``docs/verse/unreal/architecture.md`` section 1.
"""
