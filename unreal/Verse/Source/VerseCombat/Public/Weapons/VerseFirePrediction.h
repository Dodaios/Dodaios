#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

/** One shot the owning client predicted and has not heard back about. */
struct FVersePredictedShot
{
	uint16 Counter = 0;
	/** Predicted server time of the shot. */
	float Time = 0.f;
	FVector Origin = FVector::ZeroVector;
	FVector Dir = FVector::ForwardVector;
	FName WeaponId;
};

/** Outcome of one confirmation for the owning client. */
struct FVerseShotReconcile
{
	bool bKnown = false;
	/** The predicted bolt has to go (Rejected or timed out). */
	bool bRemoveBolt = false;
	/** Rounds to give back to the predicted magazine (the server never spent them). */
	int32 RefundRounds = 0;
};

/**
 * Owner-side fire prediction bookkeeping (WP02.6, combat-state.md 1, 5): pending shots keyed by the
 * wrapping uint16 shot counter, answered by ClientConfirmShot. A Rejected answer removes the
 * predicted bolt and refunds its round; a shot with no answer after TimeoutS (its unreliable
 * ServerFire was lost) is treated the same way.
 */
struct VERSECOMBAT_API FVerseFirePredictor
{
	static constexpr float TimeoutS = 1.0f;

	TArray<FVersePredictedShot> Pending;

	void Add(const FVersePredictedShot& Shot) { Pending.Add(Shot); }

	FVerseShotReconcile Confirm(uint16 Counter, EVerseShotResult Result);

	/** Drops shots older than TimeoutS at Now; returns their counters. */
	TArray<uint16> Expire(float Now);

	int32 NumPending() const { return Pending.Num(); }

	const FVersePredictedShot* Find(uint16 Counter) const;
};
