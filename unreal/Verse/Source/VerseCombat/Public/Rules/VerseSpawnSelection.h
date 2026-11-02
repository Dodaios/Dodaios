#pragma once

#include "CoreMinimal.h"
#include "Templates/Function.h"

/** One spawn candidate for VerseSpawnSelection::Choose. */
struct VERSECOMBAT_API FVerseSpawnCandidate
{
	/** Floor point, world cm. */
	FVector Floor = FVector::ZeroVector;
	/** Probe heights above the floor, metres (AVerseSpawnPoint::ProbeHeightsM). */
	TArray<float> ProbeHeightsM = {0.3f, 1.0f, 1.65f};
	/** A pawn, Bulwark or armed breach charge within BlockRadiusCm. */
	bool bBlocked = false;
};

/** What Choose found, for logs and the D2/D3 tests. */
struct VERSECOMBAT_API FVerseSpawnChoice
{
	int32 Index = INDEX_NONE;
	bool bVisible = false;
	float DistanceCm = 0.f;
	/** Every candidate's visibility and distance as Choose saw them (same order as the input). */
	TArray<bool> Visible;
	TArray<float> Distances;
	TArray<int32> Pool;
};

/**
 * Spawn selection of combat-state.md 9.2, as a pure function: no world, so the rule is tested
 * on its own and the ruleset only gathers the inputs.
 *
 *   candidates = not blocked (all of them when every one is blocked)
 *   visible(c) = a line from the opponent's eye to any probe point of c is clear
 *   dist(c)    = path length from the opponent to c (Euclidean when there is no path)
 *   pool       = the candidates out of sight, or all candidates when none is
 *   pick       = the largest dist in the pool; ties within 1 m broken by VerseRng(seed, deaths)
 *
 * Without an opponent (the first spawn of a match) every candidate ties and the seed picks.
 */
namespace VerseSpawnSelection
{
	inline constexpr float BlockRadiusCm = 300.f;
	inline constexpr float TieCm = 100.f;

	VERSECOMBAT_API FVerseSpawnChoice Choose(
		const TArray<FVerseSpawnCandidate>& Candidates,
		const TOptional<FVector>& OpponentEye,
		TFunctionRef<bool(const FVector& From, const FVector& To)> LineClear,
		TFunctionRef<float(const FVector& From, const FVector& To)> PathLength,
		uint64 MatchSeed,
		uint64 DeathCount);
}
