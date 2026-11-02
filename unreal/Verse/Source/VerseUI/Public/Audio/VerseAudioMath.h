#pragma once

#include "Audio/VerseAudioTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "GameplayTagContainer.h"
#include "Math/RandomStream.h"

class IVersePenetrationQuery;
struct FSoundAttenuationSettings;

// Pure audio rules of WP19: the distance law, attenuation built from DA_Audibility, the voice
// budget, the no-repeat variant picker and occlusion through destructible pieces. No engine
// audio device needed, so every rule is tested headless (-nullrhi -nosound).

namespace Verse::Audio
{
	VERSEUI_API float DbToGain(float Db);

	/** The Noise.* tag of bot.md 3.2 with this name; an invalid tag for any other name. */
	VERSEUI_API FGameplayTag NoiseTagByName(FName TagName);

	/**
	 * Gain at a distance: 1 inside ReferenceM, then (ReferenceM / d) ^ Rolloff floored at FloorDb, and
	 * over the last (1 - FadeStartFraction) of a finite range a smoothstep fade to exactly 0 at RangeM.
	 * RangeM <= 0 means no range (no fade). Python twin: art/verse/audio/reference_mix.py distance_gain.
	 */
	VERSEUI_API float DistanceGain(float DistanceM, float RangeM, const FVerseAudioMixSettings& Mix);

	/** Attenuation end in cm for a range: RangeM x 100, capped at the audio engine's world maximum. */
	VERSEUI_API float MaxAttenuationDistanceCm(float RangeM);

	/** Sphere attenuation that ends exactly at MaxAttenuationDistanceCm(RangeM), shaped by DistanceGain. */
	VERSEUI_API void BuildAttenuation(float RangeM, const FVerseAudioMixSettings& Mix, FSoundAttenuationSettings& Out);

	/** Weight of the far shot layer at a distance (smoothstep from ShotNearFullM to ShotFarFullM). */
	VERSEUI_API float ShotFarWeight(float DistanceM, const FVerseAudioMixSettings& Mix);

	/** Noise.Fracture loudness of a piece change (destruction.md 6.2); 0 for changes that make no noise. */
	VERSEUI_API float FractureLoudness(EVersePieceState From, EVersePieceState To, EVerseFractureCause Cause,
		EVersePenetrationMaterial Material);

	/** Destruction cue of a piece material (dst_<class>). */
	VERSEUI_API FName DestructionCueFor(EVersePenetrationMaterial Material);

	/** Debris settle cue of a piece material (dst_settle_<metal|glass|dust>). */
	VERSEUI_API FName SettleCueFor(EVersePenetrationMaterial Material);

	/** Impact cue of a penetration-table material (imp_<material>). */
	VERSEUI_API FName ImpactCueFor(EVersePenetrationMaterial Material);

	/**
	 * Closest approach of a bolt (origin, unit direction, cm) to the listener: distance in m and the
	 * time after the shot in s at BoltSpeedMps. False when the closest point is behind the muzzle.
	 */
	VERSEUI_API bool BoltClosestApproach(const FVector& Origin, const FVector& Direction, const FVector& Listener,
		float BoltSpeedMps, float& OutDistanceM, float& OutTimeS, FVector& OutPoint);
}

/** Sound through pieces between listener and source. */
struct VERSEUI_API FVerseOcclusion
{
	float LossDb = 0.f;
	float LowpassHz = 20000.f;
	int32 Pieces = 0;

	bool IsOpen() const { return Pieces == 0; }
	float Gain() const { return Verse::Audio::DbToGain(LossDb); }
};

namespace Verse::Audio
{
	/** Occlusion of the pieces a trace entered: losses add (capped), the lowest low-pass wins. */
	VERSEUI_API FVerseOcclusion OcclusionFromHits(TConstArrayView<FVersePenetrationHit> Hits, const FVerseAudioMixSettings& Mix);

	/**
	 * Trace listener to source through the destruction query. The query honours holes and breaches
	 * (destruction.md 5), so an opened piece no longer occludes. A null query means an open path.
	 */
	VERSEUI_API FVerseOcclusion TraceOcclusion(const IVersePenetrationQuery* Query, const FVector& Listener,
		const FVector& Source, const FVerseAudioMixSettings& Mix);
}

/** A voice the budget tracks. EndTime < 0: a loop that ends only on stop. */
struct FVerseVoice
{
	int32 Handle = 0;
	FName CueId;
	float Priority = 1.f;
	double StartTime = 0.0;
	double EndTime = 0.0;
};

/**
 * Voice budget (A19.3): at most Max voices. A cue over its own MaxVoices replaces its oldest voice;
 * over the global cap a play steals the lowest-priority, oldest voice if that one's priority is not
 * higher than the new play's, else it is refused.
 */
class VERSEUI_API FVerseVoiceBudget
{
public:
	struct FDecision
	{
		bool bAdmit = false;
		/** Voice to stop for this play, 0 = none. */
		int32 StealHandle = 0;
	};

	int32 Max = 64;

	FDecision Request(FName CueId, float Priority, int32 CueMaxVoices, double Now);
	void Add(const FVerseVoice& Voice);
	void Remove(int32 Handle);
	void Prune(double Now);
	void Reset() { Voices.Reset(); }
	int32 Num() const { return Voices.Num(); }
	int32 NumOf(FName CueId) const;
	const TArray<FVerseVoice>& GetVoices() const { return Voices; }

private:
	TArray<FVerseVoice> Voices;
};

/** Picks a variant that differs from the last one of the same cue (parity Z-15). Deterministic per seed. */
class VERSEUI_API FVerseVariantPicker
{
public:
	explicit FVerseVariantPicker(int32 Seed = 1907) : Stream(Seed) {}

	int32 Pick(FName CueId, int32 Count);
	float Range(const FVector2D& MinMax) { return float(MinMax.X + (MinMax.Y - MinMax.X) * Stream.GetFraction()); }
	void Reset(int32 Seed) { Stream.Initialize(Seed); Last.Reset(); }

private:
	FRandomStream Stream;
	TMap<FName, int32> Last;
};
