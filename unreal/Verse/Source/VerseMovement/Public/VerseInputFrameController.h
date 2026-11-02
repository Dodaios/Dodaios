#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Controller.h"

#include "VerseInputFrameController.generated.h"

/**
 * A server-side controller that drives its AVerseCharacter only through FVerseInputFrame
 * (bot.md B1, 8.3; architecture.md 3.4): the bot and the harness person models produce frames,
 * this controller hands them to the pawn's one input consumer, exactly like the person's input.
 * A frame persists (held buttons, stick) until the next one; Pressed and look apply once.
 */
UCLASS()
class VERSEMOVEMENT_API AVerseInputFrameController : public AController
{
	GENERATED_BODY()

public:
	AVerseInputFrameController();

	/** The frame for the pawn's next tick. */
	void SubmitFrame(const FVerseInputFrame& Frame);

	/** Frames submitted so far. */
	int32 GetSubmittedCount() const { return SubmittedCount; }

private:
	int32 SubmittedCount = 0;
};
