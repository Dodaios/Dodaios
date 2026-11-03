#pragma once

#include "CoreMinimal.h"

// The hole rim glow of destruction.md 5 (WP03.6): incandescent white-amber at impact,
// exponential cooling with tau 1.2 s, dull red at about 2.5 s, off at 4 s, then a permanent
// charred rim. Never cyan or violet (art-pipeline.md 8.3). Pure functions, so the renderer,
// the palette test and the bot's glow cue read the same curve.

/** One sample of the rim glow. */
struct FVerseHoleGlowSample
{
	/** Emissive colour, linear, hue only (multiply by Intensity). */
	FLinearColor Color = FLinearColor::Black;
	/** 1 at impact, exp(-age / tau), faded to 0 at the end. */
	float Intensity = 0.f;
	bool bGlowing = false;
};

namespace VerseHoleGlow
{
	inline constexpr float DefaultTauS = 1.2f;
	inline constexpr float DefaultEndS = 4.f;
	/** The last stretch before the end over which the glow fades to exactly 0. */
	inline constexpr float EndFadeS = 0.5f;
	/** Emissive multiplier of a fresh hole in the rim material (scene-referred). */
	inline constexpr float PeakEmissive = 40.f;

	/** White-amber at impact, amber at 1 s, dull red from 2.5 s on. */
	VERSEDESTRUCTION_API FLinearColor ColorAt(float AgeS);

	VERSEDESTRUCTION_API FVerseHoleGlowSample Sample(float AgeS, float TauS = DefaultTauS, float EndS = DefaultEndS);

	/** The charred rim colour after the glow ends (dark, nearly neutral). */
	VERSEDESTRUCTION_API FLinearColor CharredColor();

	/** How far a record may lie in the future of the local server clock and still count as fresh (clock skew). */
	inline constexpr uint32 DefaultMaxFutureMs = 250;

	/**
	 * Age in seconds of a hole stamped TimeMs at server time NowMs. A record up to MaxFutureMs in
	 * the future is 0 s old; one further ahead is treated as long cooled (MAX_flt), so a client
	 * whose clock lags never lights every recent hole at once.
	 */
	VERSEDESTRUCTION_API float AgeS(uint32 TimeMs, uint32 NowMs, uint32 MaxFutureMs = DefaultMaxFutureMs);

	/**
	 * Which holes may glow: the newest `Cap` of those younger than EndS (the oldest cools first).
	 * Times in ms of server time, NowMs the current server time. Returns indices into TimesMs.
	 */
	VERSEDESTRUCTION_API TArray<int32> SelectGlowing(TConstArrayView<uint32> TimesMs, uint32 NowMs, int32 Cap, float EndS = DefaultEndS,
		uint32 MaxFutureMs = DefaultMaxFutureMs);

	/**
	 * The rendered-pixel ban of art-pipeline.md 8.3 for one sRGB pixel: hue in 160..330 deg with
	 * saturation above 0.25 and value above 0.08.
	 */
	VERSEDESTRUCTION_API bool IsBannedPixel(const FColor& Srgb);
}
