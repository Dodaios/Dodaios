# Vosk wake confirm: shape plus acoustic competition

- Spelling cannot confirm an arbitrary wake word: an offline model spelled only 28 % of genuine calls, and no threshold separates them from chatter (AP-27). `sound_confirm` is therefore accept-only.
- The word-agnostic fallback is the SHAPE of the free decode at the phrase span (duration budget, name-sized core body). Duration questions are hard rejections; token-count and confidence questions only mark the candidate UNDECIDED.
- A shape-only acceptance must also win an acoustic competition (phrase vs "<prefix> [unk]" vs the free ear's own hypothesis) over the span-trimmed audio. Gating the whole verify on it cost 13 % of genuine recall and was rejected.
- The "leading isolation" gate was removed by maintainer mandate: the wake word must fire mid- or end-of-sentence.
- The authoritative confirm fails OPEN (never eat a real wake); the visual-only early check fails CLOSED.
