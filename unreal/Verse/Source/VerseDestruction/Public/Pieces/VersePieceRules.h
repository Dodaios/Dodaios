#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTuning.h"
#include "Destruction/VerseDestructionTypes.h"

// The piece state machine of contracts/destruction.md 3.1 and 3.2 as pure functions. The
// server simulation calls these; nothing else decides a state.

namespace Verse::Destruction::Rules
{
	/** How a damage request touches a piece. */
	enum class EHitRole : uint8
	{
		/** A bolt or melee strike on this piece. */
		Direct,
		/** The breach charge's target piece. */
		BreachTarget,
		/** Another breakable piece with a proxy vertex inside the breach radius. */
		BreachSide
	};

	struct FOutcome
	{
		EVersePieceState State = EVersePieceState::Intact;
		float Hp = 0.f;
	};

	/** Transitions only move towards Destroyed (Repairing and Reset are the only ways back). */
	VERSEDESTRUCTION_API bool IsForward(EVersePieceState From, EVersePieceState To);

	/**
	 * Applies one damage to a piece that is not Repairing. Returns the new state and hp; the
	 * state never moves backwards. Bullets never take a wall past Holed; melee changes only
	 * glass; catwalks change only by breach charge; concrete and armor steel never change.
	 */
	VERSEDESTRUCTION_API FOutcome Apply(const FVersePieceClassTuning& Row, EVersePieceState State, float Hp,
		EVerseFractureCause Cause, EHitRole Role, float Amount);

	/** Which Noise.Fracture loudness a transition produces (destruction.md 6.2). */
	VERSEDESTRUCTION_API EVerseFractureNoise NoiseKind(EVersePieceClass Class, EVerseFractureCause Cause, EVersePieceState To);
}
