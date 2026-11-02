#pragma once

#include "CoreMinimal.h"

#include "VerseBotFakePlayerState.generated.h"

/**
 * The two AVersePlayerState fields VerseBot writes (combat-state.md 2.1), as a reflected struct for
 * Verse.Bot.Controller.Identity until AVersePlayerState lands in VerseCombat. Test-only data shape.
 */
USTRUCT()
struct FVerseBotFakePlayerStateFields
{
	GENERATED_BODY()

	UPROPERTY()
	FName BotTier;

	UPROPERTY()
	float BotEffectiveSkill = -1.f;
};
