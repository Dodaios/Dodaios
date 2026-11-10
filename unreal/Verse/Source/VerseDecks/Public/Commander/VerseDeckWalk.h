#pragma once

#include "CoreMinimal.h"

struct FVerseDeckStation;

/**
 * How the commander walks on a deck, as pure maths (stream S5), ported from the three.js stage
 * (`engine/realtime/viewMode.ts` bodyFacing, `life/control.ts`, `life/commander.ts`,
 * `actors/locomotion.ts`) into Unreal space: centimetres, Z up, yaw in degrees (0 = +X, growing
 * toward +Y, contracts/coordinates.md 2.2).
 */
namespace Verse::DeckWalk
{
	/** How far off the view the body may face while walking: a strafe leans into it, no more (parity V-12). */
	inline constexpr double StrafeLeanDeg = 45.0;
	/** Moving further off the view than this is walking backwards (the walk plays in reverse). */
	inline constexpr double BackpedalBeyondDeg = 110.0;
	/** The commander's own pace (parity C-17: 1.45 m/s). */
	inline constexpr double PaceCmPerS = 145.0;
	/** Shift: the commander hurries at this multiple of the pace (parity V-13). */
	inline constexpr double HurryFactor = 1.75;
	/** Turning rate of a driven body, degrees per second (9 rad/s). */
	inline constexpr double TurnRateDegPerS = 515.0;
	/** A click on the floor walks to the nearest walkable point within this distance (parity V-15). */
	inline constexpr double ClickSnapCm = 120.0;
	/** How far from a station the commander can still work it with the use key. */
	inline constexpr double StationReachCm = 220.0;
	/** A walk ends when the feet are this close to the target. */
	inline constexpr double ArriveCm = 15.0;

	/** The way a body faces while walking in a shooter view. */
	struct FFacing
	{
		double YawDeg = 0.0;
		/** Walking backwards: the body faces the view and plays its walk in reverse. */
		bool bReverse = false;
	};

	/** Wraps an angle into (-180, 180]. */
	VERSEDECKS_API double WrapDeg(double Deg);

	/** Which way a body walking along `MoveDir` (on the floor) faces in a view looking along `ViewYawDeg` (parity V-12). */
	VERSEDECKS_API FFacing BodyFacing(double ViewYawDeg, const FVector2D& MoveDir);

	/**
	 * The held movement keys relative to the view: `Axes.X` right (+1) / left (-1), `Axes.Y`
	 * forward (+1, W) / back (-1). Unit length on the floor, unset when nothing is held or the
	 * keys cancel out. W walks away from the camera in third and first person alike.
	 */
	VERSEDECKS_API TOptional<FVector2D> WalkDirection(double ViewYawDeg, const FVector2D& Axes);

	/** One frame of turning `YawDeg` toward `TargetDeg` at `RateDegPerS`, eased near the end (`turnToward`). */
	VERSEDECKS_API double TurnToward(double YawDeg, double TargetDeg, double RateDegPerS, double DtS);

	/** Walking slows while the body still turns toward its heading (`turnPace`): 1 straight on, 0.35 at 90 degrees or more. */
	VERSEDECKS_API double TurnPace(double YawDeg, double HeadingDeg);

	/** Walking speed, cm/s, with or without Shift. */
	inline double Speed(bool bHurry) { return PaceCmPerS * (bHurry ? HurryFactor : 1.0); }

	/**
	 * The station within reach of `FeetCm`, or nullptr: given the direction the commander looks
	 * along (`Facing`, unit, may be zero), the one most in front, so the use key works what they
	 * see when two are in reach. A station straight behind counts as twice as far (`stationWithin`).
	 */
	VERSEDECKS_API const FVerseDeckStation* StationWithin(TConstArrayView<FVerseDeckStation> Stations, const FVector& FeetCm,
		const FVector2D& Facing, double ReachCm = StationReachCm);
}

/**
 * The commander's walk order (parity B-07): it belongs to the deck it was given on. Riding the
 * lift ends it, so coming back to that deck never sends the commander toward the old target;
 * they stand where they came aboard.
 */
struct VERSEDECKS_API FVerseWalkOrders
{
	/** A click (or a station) ordered a walk on `Deck`. */
	void Give(FName Deck, const FVector& TargetCm);
	/** The keys took over, or the walk ended. */
	void Clear();
	/** The commander came aboard `Deck` (by lift or directly): any older order is void. */
	void Arrive(FName Deck);
	/** Where the commander heads on `Deck`, unset when there is no order for it. */
	TOptional<FVector> TargetOn(FName Deck) const;

	FName GetDeck() const { return Deck; }
	/** Changes with every order, so a click on the same spot walks again. */
	int32 GetOrder() const { return Order; }

private:
	FName Deck;
	FVector Target = FVector::ZeroVector;
	bool bHasTarget = false;
	int32 Order = 0;
};
