#pragma once

#include "CoreMinimal.h"
#include "VerseCharacter.h"

/**
 * The scripted player of the integration runs: drives a person pawn through the same input frames
 * a person's keys produce (AVerseCharacter::SetInputScript), so every shot, reload, knife press and
 * gadget use takes the person's path. It reads world truth, never the bot: it turns toward the
 * opponent at a person-like rate with aim noise, fires in bursts when it has a line of sight,
 * strafes while shooting, walks the nav path toward the opponent otherwise, deploys the Bulwark
 * once per life under fire, plants a breach charge when stuck behind cover and knifes up close.
 */
namespace VerseDuelAutopilot
{
	FVerseInputScript Make(AVerseCharacter* Pawn, uint32 Seed);
}
