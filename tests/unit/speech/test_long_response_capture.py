"""RUB-35: the shared capture buffer never silently drops a command prefix.

The capture-first buffer feeds the realtime session the user's opening words;
an overflow before the consumer caught up must fail loudly instead of
dropping the start of the command.
"""

import pytest

from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import _SessionInputBuffer


@pytest.mark.asyncio
@pytest.mark.parametrize("cutoff", [0, 2])
async def test_unsuppressed_command_prefix_overflow_remains_an_error(cutoff: int) -> None:
    buffer = _SessionInputBuffer(max_buffer_bytes=4)
    buffer.put(AudioChunk(pcm=b"aaaa", sample_rate=16000, timestamp_ns=1))
    stream = buffer.stream(discard_before_ns=lambda: cutoff)
    assert (await anext(stream)).pcm == b"aaaa"
    buffer.put(AudioChunk(pcm=b"bbbb", sample_rate=16000, timestamp_ns=2))
    buffer.put(AudioChunk(pcm=b"cccc", sample_rate=16000, timestamp_ns=3))
    with pytest.raises(RuntimeError, match="refusing to drop the command prefix"):
        await anext(stream)
    await buffer.close()


@pytest.mark.asyncio
async def test_startup_prefix_guard_cannot_be_bypassed_by_old_echo_cutoff() -> None:
    buffer = _SessionInputBuffer(max_buffer_bytes=4)
    buffer.put(AudioChunk(pcm=b"aaaa", sample_rate=16000, timestamp_ns=1))
    buffer.put(AudioChunk(pcm=b"bbbb", sample_rate=16000, timestamp_ns=2))
    with pytest.raises(RuntimeError, match="refusing to drop the command prefix"):
        await anext(buffer.stream(discard_before_ns=lambda: 100))
    await buffer.close()
