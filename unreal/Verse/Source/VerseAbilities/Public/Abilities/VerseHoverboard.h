#pragma once

#include "CoreMinimal.h"

/**
 * The commander's hoverboard (parity Z-09, reference `actors/hoverboard.ts`):
 * a small grav board that folds out under the feet (B) and glides across the
 * deck several times faster than a walk. It speeds up toward the held
 * direction, coasts to a stop when the keys are let go and loses its speed
 * against a wall; the rider floats a hand's breadth up with a slow bob and
 * leans into speed and turns.
 *
 * Pure motion helpers, Unreal units (cm, s, radians for angles).
 * `UVerseHoverboardComponent` rides on them.
 */
namespace VerseBoard
{
	/** Cruising speed, cm/s (a walk is about 130). */
	inline constexpr float SpeedCm = 550.f;
	/** Shift on the board: boost, cm/s. */
	inline constexpr float BoostCm = 850.f;
	/** The reference's walking pace, cm/s (`DEFAULT_WALK_SPEED`). */
	inline constexpr float WalkCm = 130.f;
	/** How fast the board reaches the held velocity, 1/s (higher = snappier). */
	inline constexpr float Accel = 3.2f;
	/** How fast it coasts down once the keys are let go, 1/s. */
	inline constexpr float Coast = 2.2f;
	/** Below this speed a coasting board has stopped, cm/s. */
	inline constexpr float StoppedCm = 5.f;
	/** The rider's feet stand this high above the floor, cm. */
	inline constexpr float LiftCm = 16.f;
	/** Folding out or away takes this long, s. */
	inline constexpr float DeployS = 0.32f;

	/** The speed the board wants for the held keys, cm/s. */
	VERSEABILITIES_API float BoardSpeed(bool bBoost);

	/**
	 * One step of the board's horizontal velocity toward the wanted one
	 * (`Direction` unit length, or null to coast).
	 */
	VERSEABILITIES_API FVector2D Glide(FVector2D Velocity, const FVector2D* Direction, bool bBoost, float Dt);

	/**
	 * After a step that went only part of the way (a wall, a person), keep just
	 * the velocity the board really travelled with, so it does not push on into
	 * the wall. `Wanted` and `Moved` are the step's displacements.
	 */
	VERSEABILITIES_API FVector2D Absorb(FVector2D Velocity, FVector2D Wanted, FVector2D Moved, float Dt);

	/** The fold-out share after a step toward `bOn` (0 folded away, 1 out); at once with reduced motion. */
	VERSEABILITIES_API float DeployStep(float Share, bool bOn, float Dt, bool bReduced);

	/** Eased fold-out scale: springs out a touch past full size (ease-out-back). */
	VERSEABILITIES_API float DeployScale(float Share);

	/** The rider's lift and hover bob above the floor, cm. */
	VERSEABILITIES_API float HoverHeight(float Share, float TimeS, float Speed, bool bReduced);

	/**
	 * Lean of the rider and board, radians: X pitches forward with speed, Y rolls
	 * into a turn (`TurnRate` is the Unreal yaw rate, rad/s, positive turning right;
	 * a right turn rolls the right side down, a positive Unreal roll).
	 */
	VERSEABILITIES_API FVector2D Lean(float Speed, float TurnRate, bool bReduced);
}
