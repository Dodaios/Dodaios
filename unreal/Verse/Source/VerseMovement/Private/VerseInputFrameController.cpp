#include "VerseInputFrameController.h"

#include "VerseCharacter.h"

AVerseInputFrameController::AVerseInputFrameController()
{
	bReplicates = false;
}

void AVerseInputFrameController::SubmitFrame(const FVerseInputFrame& Frame)
{
	if (AVerseCharacter* Character = Cast<AVerseCharacter>(GetPawn()))
	{
		Character->SubmitInputFrame(Frame);
		++SubmittedCount;
	}
}
