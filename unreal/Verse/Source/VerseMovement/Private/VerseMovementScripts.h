#pragma once

#include "CoreMinimal.h"
#include "VerseCharacter.h"

/**
 * Seeded input scripts that exercise every move (the netcode soak, the cost test, QA). They
 * produce plain FVerseInputFrames, so they drive a pawn exactly like a person or a bot.
 */
namespace VerseMovementScripts
{
	/**
	 * A mixed session on the fixture course (whose origin is CourseOrigin): runs, sprints,
	 * slides, crouch and prone crawls, lean peeks, jumps and mantle runs at the ledge lanes.
	 * Ends after Duration seconds.
	 */
	FVerseInputScript MakeSoak(uint64 Seed, float Duration, TWeakObjectPtr<AVerseCharacter> Pawn, const FVector& CourseOrigin);
}
