#pragma once

#include "CoreMinimal.h"

/**
 * Arc Storm, the commander's show of power on the decks (parity Z-05..Z-08,
 * reference `abilities/arcStorm.ts`): while F is held, lightning crackles
 * from both hands toward the aim, re-striking many times a second.
 *
 * This header is the pure part: tuning, the seeded generator, the bolt
 * geometry and one strike's plan. `UVerseArcStormComponent` draws it.
 * Units are Unreal's (cm, s, Z up).
 */
namespace VerseArc
{
	/** How far the bolts reach, cm. */
	inline constexpr float ReachCm = 520.f;
	/** Seconds between strikes (each strike redraws every bolt), before the random spread. */
	inline constexpr float RestrikeS = 0.045f;
	/** Bolts per hand per strike. */
	inline constexpr int32 BoltsPerHand = 3;
	/** Segments of a main bolt (a power of two). */
	inline constexpr int32 Segments = 16;
	/** Sideways jitter of the midpoints, as a share of the bolt's length. */
	inline constexpr float Jitter = 0.2f;
	/** Short side bolts off every main bolt, their segments and jitter. */
	inline constexpr int32 ForksPerBolt = 2;
	inline constexpr int32 ForkSegments = 4;
	inline constexpr float ForkJitter = 0.4f;
	/** Sparks where a main bolt lands, and their length, cm. */
	inline constexpr int32 SparksPerBolt = 3;
	inline constexpr float SparkCm = 22.f;
	/** The power rises over this long while held, and falls over `FallS` once let go. */
	inline constexpr float RaiseS = 0.18f;
	inline constexpr float FallS = 0.12f;
	/** Bolts fly only above this level (the arms are up by then). */
	inline constexpr float OnLevel = 0.6f;

	/**
	 * Colours (linear). The reference was violet-white; the Unreal Verse bans violet
	 * and cyan (README "Look", style bible 8), so the core is a cool white and the
	 * glow the amber accent.
	 */
	VERSEABILITIES_API FLinearColor CoreColor();
	VERSEABILITIES_API FLinearColor GlowColor();

	/**
	 * True for a banned hue of the style bible's palette check: hue 170-200 deg
	 * (cyan) or 270-330 deg (purple to magenta) at a saturation above 0.7,
	 * measured on the sRGB colour.
	 */
	VERSEABILITIES_API bool IsBannedHue(const FLinearColor& Linear);

	/** A small deterministic random generator (mulberry32, the reference's `rng`): [0, 1). */
	struct VERSEABILITIES_API FRand
	{
		explicit FRand(uint32 Seed) : State(Seed) {}
		float operator()();

	private:
		uint32 State;
	};

	/**
	 * A lightning bolt from `A` to `B`: `Segments + 1` points (`Segments` a power
	 * of two), the ends exact, the inside displaced at random across the line,
	 * most at the middle. Pure apart from `Rand`.
	 */
	VERSEABILITIES_API TArray<FVector> BoltPoints(const FVector& A, const FVector& B, int32 Segments, float Jitter, FRand& Rand);

	/** The power's level (0..1) after `Dt` seconds held or let go. */
	VERSEABILITIES_API float Rise(float Level, float Dt, bool bHeld);

	/** One drawn polyline of a strike. */
	struct FBolt
	{
		TArray<FVector> Points;
		enum class EKind : uint8 { Main, Fork, Spark } Kind = EKind::Main;
	};

	/** Everything one strike draws: every bolt from every hand, and where they land on average. */
	struct FStrike
	{
		TArray<FBolt> Bolts;
		/** Mean landing point of the main bolts (the impact light). */
		FVector Impact = FVector::ZeroVector;
		/** Mean of the hands (the hand light sits a little ahead of it). */
		FVector HandsMid = FVector::ZeroVector;
	};

	/**
	 * One strike from `Hands` toward `Aim` (any length; normalised), never below
	 * `FloorZ`: per hand `BoltsPerHand` main bolts landing in a cone ahead (the
	 * first one straightest), each with forks and sparks at its end. Same seed,
	 * same strike.
	 */
	VERSEABILITIES_API FStrike PlanStrike(TConstArrayView<FVector> Hands, const FVector& Aim, float FloorZ, uint32 Seed);
}
