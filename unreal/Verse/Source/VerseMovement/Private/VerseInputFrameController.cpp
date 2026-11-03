#include "VerseInputFrameController.h"

#include "VerseCharacter.h"

AVerseInputFrameController::AVerseInputFrameController()
{
	bReplicates = false;
}

void AVerseInputFrameController::SubmitFrame(const FVerseInputFrame& Frame)
{
	if (AVerseCharacter* Driven = Cast<AVerseCharacter>(GetPawn()))
	{
		Driven->SubmitInputFrame(Frame);
		++SubmittedCount;
	}
}
