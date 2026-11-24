# dodaios-sdk

The contracts a Dodaios plugin implements, and nothing else. Standard library
only (Python 3.11+). Use it to write a plugin, or to take one Dodaios module
(a speech engine, a brain, a tool) into your own code without the rest of the
repo.

## Groups

One module per group. Register your class under the entry-point group shown.

| Group (`dodaios.<slot>`) | Contract | Module |
| --- | --- | --- |
| `stt` | `STTProvider` | `dodaios_sdk.stt` |
| `tts` | `TTSProvider` | `dodaios_sdk.tts` |
| `brain` | `Brain` | `dodaios_sdk.brain` |
| `wakeword` | `WakeWordProvider` | `dodaios_sdk.wakeword` |
| `turn` | `TurnDetector` (declared, no shipped provider) | `dodaios_sdk.turn` |
| `harness` | `Harness` | `dodaios_sdk.harness` |
| `channel` | `ChannelAdapter` | `dodaios_sdk.channel` |
| `realtime` | `RealtimeProvider` | `dodaios_sdk.realtime` |
| `tool` | `Tool` | `dodaios_sdk.tool` |

The contracts are `typing.Protocol` classes: you do not inherit from them.
Match the attributes and method signatures and `isinstance` passes.

## Example

```python
# my_plugin/__init__.py
from dodaios_sdk import AudioChunk

class MyTTS:
    name = "my-tts"
    supports_streaming = True

    async def synthesize(self, text, voice=None, language_code=None):
        yield AudioChunk(pcm=b"\x00\x00" * 2400, sample_rate=24000, timestamp_ns=0)

    def list_voices(self, language=None):
        return ["default"]
```

```toml
# pyproject.toml of your plugin
dependencies = ["dodaios-sdk>=0.1.0"]

[project.entry-points."dodaios.tts"]
my-tts = "my_plugin:MyTTS"
```

Check it in your own tests:

```python
from dodaios_sdk import check_plugin
check_plugin("tts", MyTTS)   # raises TypeError if the contract is not met
```

A complete package is in `examples/hello_tts/`.

## How Dodaios finds a plugin

At start the app reads every installed distribution's entry points in the
groups `dodaios.<slot>` and `jarvis.<slot>` (the older name, still read), loads
the class, builds it with no arguments and uses it under its entry-point name.
Install your package into the same environment and it appears in the provider
list. Missing optional dependencies fail that one plugin only.

## One source of truth

The app does not import this package: it keeps its own copy of the contracts in
`dodaios/core/protocols.py`, `dodaios/channels/base.py` and
`dodaios/realtime/protocol.py`, so the packaged app and its installers do not
depend on a second distribution. `tests/unit/sdk/test_sdk_contract_parity.py`
fails when the two drift apart. Change a contract in both places.

## Building

`pip install sdk/` builds from source; `python -m build sdk/` makes sdist and
wheel. Publishing to PyPI is a separate step and has not been done.
