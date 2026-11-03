#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Melee/VerseMeleeWorld.h"

/**
 * Fake of the melee world seam for tests: the interim world plus a scripted rewind history
 * (WP02.8 stand-in) and per-pawn movement flags (WP01 stand-in).
 */
class FFakeMeleeWorld : public FVerseInterimMeleeWorld
{
public:
	explicit FFakeMeleeWorld(UWorld* InWorld) : FVerseInterimMeleeWorld(InWorld) {}

	/** Pawn base transforms by server time; GetBaseTransformAt answers the latest entry at or before the time. */
	TMap<const APawn*, TArray<TPair<double, FTransform>>> History;
	/** Movement flag overrides (stance, mantling, airborne); combat phase still comes from the pawn. */
	TMap<const APawn*, FVerseMeleeParticipant> Movement;

	virtual FTransform GetBaseTransformAt(const APawn* Pawn, double ServerTime) const override
	{
		if (const TArray<TPair<double, FTransform>>* Samples = History.Find(Pawn))
		{
			const FTransform* Best = nullptr;
			for (const TPair<double, FTransform>& Sample : *Samples)
			{
				if (Sample.Key <= ServerTime + 1e-6)
				{
					Best = &Sample.Value;
				}
			}
			if (Best)
			{
				return *Best;
			}
		}
		return FVerseInterimMeleeWorld::GetBaseTransformAt(Pawn, ServerTime);
	}

	virtual FVerseMeleeParticipant Describe(const APawn* Pawn) const override
	{
		FVerseMeleeParticipant P = FVerseInterimMeleeWorld::Describe(Pawn);
		if (const FVerseMeleeParticipant* Override = Movement.Find(Pawn))
		{
			P.Stance = Override->Stance;
			P.bMantling = Override->bMantling;
			P.bAirborne = Override->bAirborne;
		}
		return P;
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS
