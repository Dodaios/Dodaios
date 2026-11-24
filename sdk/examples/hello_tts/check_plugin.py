"""Run inside an environment with only dodaios-sdk and dodaios-hello-tts installed."""

import asyncio
import sys
from importlib.metadata import entry_points

import dodaios_sdk

# Nothing of the Dodaios app may be importable here.
for forbidden in ("dodaios", "jarvis"):
    try:
        __import__(forbidden)
    except ImportError:
        continue
    sys.exit(f"{forbidden} is importable: the plugin is not standalone")

(ep,) = [e for e in entry_points(group=dodaios_sdk.entry_point_group("tts")) if e.name == "hello"]
plugin = dodaios_sdk.check_plugin("tts", ep.load())


async def main() -> int:
    chunks = [c async for c in plugin.synthesize("hi")]
    assert len(chunks) == 2 and all(isinstance(c, dodaios_sdk.AudioChunk) for c in chunks)
    return len(chunks)


print("OK", asyncio.run(main()))
