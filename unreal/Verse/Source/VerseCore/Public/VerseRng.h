#pragma once

#include "CoreMinimal.h"

#include "VerseRng.generated.h"

/**
 * Streams of VerseRng. Two uses that draw from the same seed and index but a different
 * salt get independent numbers (combat-state.md 4.4: VerseRng(seed, n, salt=Spread)).
 * The order is frozen: the value enters the stream key.
 */
UENUM(BlueprintType)
enum class EVerseRngSalt : uint8
{
	None,
	Recoil,
	Spread,
	Spawn,
	Perception,
	Aim,
	Brain,
	Fracture,
	Harness
};

/**
 * The one seeded random number generator of the Verse (orchestration.md 5.2: tests seed it,
 * flaky is failed). SplitMix64 over integer arithmetic only, so the integer and unit draws
 * are bit-identical on every platform and compiler; server and owning client derive the
 * same recoil and spread from the same seed. Gaussian draws use sqrt, log and cos and are
 * deterministic per build.
 */
struct VERSECORE_API FVerseRng
{
	/** A stream for one seed. */
	explicit FVerseRng(uint64 Seed = 0);

	/** VerseRng(seed, index, salt): the stream for draw `Index` of a seeded sequence. */
	FVerseRng(uint64 Seed, uint64 Index, EVerseRngSalt Salt = EVerseRngSalt::None);

	/** The SplitMix64 finaliser: a bijective 64-bit mix. */
	static uint64 Mix(uint64 Value);

	/** Order-sensitive hash of three 32-bit values, e.g. Hash(shooter net id, shot counter, match seed). */
	static uint32 Hash(uint32 A, uint32 B, uint32 C);

	uint64 NextU64();
	uint32 NextU32();

	/** Uniform in [0, 1), 53 random bits. */
	double NextUnit();

	/** Uniform in [Min, Max). */
	double Range(double Min, double Max);

	/** Uniform integer in [Min, Max] (inclusive); Min when Max < Min. */
	int32 RangeInt(int32 Min, int32 MaxInclusive);

	/** True with probability P. */
	bool Chance(double P);

	/** Normal distribution, Box-Muller. */
	double Gaussian(double Mean = 0.0, double Sd = 1.0);

	/** Point uniformly in the unit disk (rejection sampling; arithmetic only). */
	FVector2D UnitDisk();

	/** Direction uniformly on the unit sphere. */
	FVector UnitVector();

	/** Direction uniformly inside the cone of half-angle `HalfAngleDeg` around `Axis` (combat-state.md 4.4). */
	FVector ConeDirection(const FVector& Axis, double HalfAngleDeg);

	uint64 GetState() const { return State; }

private:
	uint64 State = 0;
};
