"""The Hugging Face finder must keep understanding the LIVE API.

The unit tests pin the parsers against JSON snapshots, which cannot notice
Hugging Face renaming a field. This guard fetches one real search and one
real tree listing and asserts the shapes still read. Network-dependent, so it
is marked ``integration`` and self-skips when huggingface.co cannot be reached
or rate-limits the runner. Run explicitly with ``pytest -m integration``.
"""

from __future__ import annotations

import re

import pytest

import dodaios.brain.hf_gguf as hf

pytestmark = pytest.mark.integration


# A 5xx is Hugging Face having a bad minute (a 504 failed a pull request on
# 2026-10-14), not a change in its API; a 4xx still fails.
_SERVER_ERROR = re.compile(r"answered 5\d\d\b")


def _skip_on_network_error(error: str | None) -> None:
    if error and (
        "did not answer" in error or "rate-limiting" in error or _SERVER_ERROR.search(error)
    ):
        pytest.skip(f"huggingface.co unavailable: {error}")


@pytest.mark.asyncio
async def test_live_search_and_tree_still_parse() -> None:
    hf._search_cache.clear()
    hf._files_cache.clear()

    result = await hf.search("qwen", sort="downloads", limit=5)
    _skip_on_network_error(result["error"])
    assert result["error"] is None, result["error"]
    assert result["repos"], "the live search answered no GGUF repository for 'qwen'"
    first = result["repos"][0]
    assert "/" in first["id"]
    assert first["downloads"] > 0
    assert first["architecture"], "expand[]=gguf no longer carries the architecture"

    user, repo = first["id"].split("/", 1)
    listing = await hf.files(user, repo)
    _skip_on_network_error(listing["error"])
    assert listing["error"] is None, listing["error"]
    assert listing["files"], f"{first['id']} listed no .gguf file"
    sized = [f for f in listing["files"] if f["size_gb"] is not None]
    assert sized, "tree/main no longer reports lfs.size for GGUF files"
    assert any(f["quant"] for f in listing["files"]), "no quantization label parsed"
    assert all(f["fit"] in ("comfortable", "tight", "unknown") for f in listing["files"])
